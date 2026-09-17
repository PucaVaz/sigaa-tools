"""Watcher: sync, then turn store changes into a deterministic event stream.

Each run ends with exactly one ``sync`` event whose status is ``changes``,
``no_changes``, ``failed``, or ``baseline``. A failed sync always yields
``error`` events and a ``failed`` status, never ``no_changes``.

What was already emitted lives in the ``watch_state`` table, keyed by SIGAA's
stable ids, so the watcher's memory is independent of the ``is_new`` flags that
``whatsnew`` and the MCP server clear. Item events carry ``detected_at``; the
closing ``sync`` event and error events carry no clock, so an unchanged state
serializes to identical bytes run after run.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..config import Settings
from ..store.db import connect
from ..store.repository import Repository
from .sync import SyncResult, sync

EVENT_NEWS = "news"
EVENT_DEADLINE = "deadline"
EVENT_MATERIAL = "material"
EVENT_GRADE = "grade"
EVENT_ATTENDANCE = "attendance"
EVENT_ERROR = "error"
EVENT_SYNC = "sync"

STATUS_NEW = "new"
STATUS_CHANGED = "changed"
STATUS_FAILED = "failed"
STATUS_CHANGES = "changes"
STATUS_NO_CHANGES = "no_changes"
STATUS_BASELINE = "baseline"

# Emission order: what a student must act on first.
_TYPE_ORDER = (EVENT_NEWS, EVENT_DEADLINE, EVENT_ATTENDANCE, EVENT_GRADE, EVENT_MATERIAL)
_URL_RE = re.compile(r"https?://[^\s)<>\"']+")

SyncRunner = Callable[[Settings, bool], SyncResult]


@dataclass
class WatchRun:
    status: str
    events: list[dict] = field(default_factory=list)
    classes: list[dict] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.status == STATUS_FAILED

    def summary_event(self) -> dict:
        return {
            "type": EVENT_SYNC,
            "status": self.status,
            "event_count": len(self.events),
            "classes": self.classes,
        }

    def document(self) -> dict:
        """The single JSON document printed by ``--once --json``."""
        return {**self.summary_event(), "events": self.events}


@dataclass
class _Candidate:
    key: str
    fingerprint: str
    event: dict


def run_once(
    settings: Settings,
    *,
    fetch_bodies: bool = False,
    baseline: bool = False,
    now: Callable[[], datetime] | None = None,
    runner: SyncRunner = sync,
) -> WatchRun:
    """Sync once and report what changed since the watcher last emitted.

    ``baseline`` records the current store as already seen without emitting
    item events, so a first run does not replay every old announcement.
    """
    result = runner(settings, fetch_bodies)
    conn = connect(settings.db_path)
    try:
        repo = Repository(conn)
        errors = _error_events(result)
        candidates = _changed_candidates(repo)
        if baseline and not errors:
            repo.save_watch_fingerprints({c.key: c.fingerprint for c in candidates})
            return WatchRun(status=STATUS_BASELINE, classes=class_summaries(result))

        detected_at = _timestamp(now)
        events = []
        for candidate in candidates:
            candidate.event["detected_at"] = detected_at
            events.append(candidate.event)
        repo.save_watch_fingerprints({c.key: c.fingerprint for c in candidates})
    finally:
        conn.close()

    if errors:
        status = STATUS_FAILED
    elif events:
        status = STATUS_CHANGES
    else:
        status = STATUS_NO_CHANGES
    return WatchRun(status=status, events=events + errors, classes=class_summaries(result))


def _changed_candidates(repo: Repository) -> list[_Candidate]:
    emitted = repo.watch_fingerprints()
    changed = []
    for candidate in _candidates(repo):
        previous = emitted.get(candidate.key)
        if previous == candidate.fingerprint:
            continue
        candidate.event["status"] = STATUS_NEW if previous is None else STATUS_CHANGED
        changed.append(candidate)
    changed.sort(key=_sort_key)
    return changed


def _sort_key(candidate: _Candidate) -> tuple:
    event = candidate.event
    return (_TYPE_ORDER.index(event["type"]), event["class_id"] or "", event["item_id"])


def _candidates(repo: Repository) -> list[_Candidate]:
    codes = {t.id_turma: t.code for t in repo.get_turmas()}
    candidates = []
    for news in repo.get_news():
        candidates.append(_candidate(
            EVENT_NEWS, news.id, (news.date, news.title),
            _item_event(EVENT_NEWS, codes, news.id_turma, news.id, news.title,
                        published_at=news.date, body=news.body, url=_first_url(news.body)),
        ))
    for deadline in repo.get_deadlines():
        candidates.append(_candidate(
            EVENT_DEADLINE, deadline.id, (deadline.date, deadline.title),
            _item_event(EVENT_DEADLINE, codes, deadline.id_turma, deadline.id, deadline.title,
                        body=deadline.detail, kind=deadline.kind, due=deadline.date),
        ))
    for material in repo.get_materials():
        candidates.append(_candidate(
            EVENT_MATERIAL, material.id, (material.title, material.url),
            _item_event(EVENT_MATERIAL, codes, material.id_turma, material.id, material.title,
                        url=material.url, kind=material.kind, topic=material.topic),
        ))
    for grade in repo.get_turma_grades():
        values = {"units": grade.units, "exam": grade.exam, "result": grade.result,
                  "absences": grade.absences, "grade_status": grade.status}
        candidates.append(_candidate(
            EVENT_GRADE, grade.id_turma, values,
            _item_event(EVENT_GRADE, codes, grade.id_turma, grade.id_turma, "grade", **values),
        ))
    for attendance in repo.get_attendance():
        values = {"total_absences": attendance.total_absences,
                  "justified_absences": attendance.justified_absences,
                  "max_absences": attendance.max_absences,
                  "record_count": len(attendance.records)}
        candidates.append(_candidate(
            EVENT_ATTENDANCE, attendance.id_turma, values,
            _item_event(EVENT_ATTENDANCE, codes, attendance.id_turma, attendance.id_turma,
                        "attendance", **values),
        ))
    return candidates


def _candidate(event_type: str, item_id: str, watched, event: dict) -> _Candidate:
    fingerprint = json.dumps(watched, ensure_ascii=False, sort_keys=True)
    return _Candidate(key=f"{event_type}:{item_id}", fingerprint=fingerprint, event=event)


def _item_event(
    event_type: str,
    codes: dict[str, str | None],
    class_id: str | None,
    item_id: str,
    title: str,
    *,
    published_at: str | None = None,
    body: str | None = None,
    url: str | None = None,
    **extra,
) -> dict:
    return {
        "type": event_type,
        "status": STATUS_NEW,
        "class_id": class_id,
        "class_code": codes.get(class_id) if class_id else None,
        "item_id": item_id,
        "title": title,
        "published_at": published_at,
        "body": body,
        "url": url,
        **extra,
    }


def _error_events(result: SyncResult) -> list[dict]:
    per_class = [
        _error_event(issue.stage, issue.message, summary.id_turma, summary.code)
        for summary in result.classes
        for issue in summary.errors
    ]
    if per_class:
        return per_class
    if not result.ok:
        return [_error_event(result.error_stage or "sync", result.error or "sync failed")]
    return []


def _error_event(stage: str, message: str, class_id: str | None = None,
                 class_code: str | None = None) -> dict:
    return {
        "type": EVENT_ERROR,
        "status": STATUS_FAILED,
        "stage": stage,
        "message": message,
        "class_id": class_id,
        "class_code": class_code,
    }


def class_summaries(result: SyncResult) -> list[dict]:
    return [
        {
            "class_id": s.id_turma,
            "class_code": s.code,
            "news_found": s.news_found,
            "news_new": s.news_new,
            "materials_new": s.materials_new,
            "deadlines_new": s.deadlines_new,
            "grades_changed": s.grades_changed,
            "attendance_changed": s.attendance_changed,
            "errors": [{"stage": e.stage, "message": e.message} for e in s.errors],
        }
        for s in sorted(result.classes, key=lambda s: s.id_turma)
    ]


def _first_url(text: str | None) -> str | None:
    match = _URL_RE.search(text or "")
    return match.group(0) if match else None


def _timestamp(now: Callable[[], datetime] | None) -> str:
    moment = now() if now else datetime.now(timezone.utc)
    return moment.isoformat(timespec="seconds")
