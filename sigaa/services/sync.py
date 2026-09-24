"""Sync: fetch live SIGAA state, diff against the store, persist new news.

Idempotent. A news id already in the store is not new, so re-running is safe and
reports zero new items once caught up.

Every failure is recorded in ``sync_run`` and tagged with a stage (see
``sigaa.errors``). A class whose news panel cannot be parsed is reported in its
``ClassSummary`` and fails the run, while the other classes still sync.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from ..client import SigaaClient
from ..config import Settings
from ..errors import NavigationError, error_stage
from ..institutions import get
from ..models import (
    Attendance,
    Deadline,
    Material,
    NewsItem,
    Professor,
    Student,
    Turma,
    TurmaGrade,
)
from ..store.db import connect
from ..store.repository import Repository

UNTITLED_EVALUATION_SLUG = "avaliacao"


@dataclass
class SyncIssue:
    stage: str
    message: str


@dataclass
class ClassSummary:
    """Per-class counts for one run; ``errors`` is empty when the class synced cleanly."""

    id_turma: str
    code: str | None = None
    news_found: int = 0
    news_new: int = 0
    materials_new: int = 0
    deadlines_new: int = 0
    grades_changed: int = 0
    attendance_changed: int = 0
    errors: list[SyncIssue] = field(default_factory=list)


@dataclass
class SyncResult:
    student: Student | None = None
    turma_count: int = 0
    new_items: list[NewsItem] = field(default_factory=list)
    new_materials: list[Material] = field(default_factory=list)
    grade_updates: list[TurmaGrade] = field(default_factory=list)
    attendance_updates: list[Attendance] = field(default_factory=list)
    new_deadlines: list[Deadline] = field(default_factory=list)
    grade_count: int = 0
    ok: bool = True
    error: str | None = None
    # auth / network / parse / sync; set whenever ok is False.
    error_stage: str | None = None
    classes: list[ClassSummary] = field(default_factory=list)


def sync(settings: Settings, fetch_bodies: bool = False) -> SyncResult:
    get(settings.institution).profile.require_store_access()
    conn = connect(settings.db_path)
    repo = Repository(conn)
    result = SyncResult()
    try:
        username, password = settings.require_credentials()
        with SigaaClient(username, password, institution=settings.institution) as client:
            result.student = client.get_student()
            repo.upsert_student(result.student)

            turmas = client.list_turmas()
            result.turma_count = len(turmas)
            for turma in turmas:
                result.classes.append(_sync_turma(client, repo, turma, fetch_bodies, result))
            summaries = {summary.id_turma: summary for summary in result.classes}

            for deadline in client.list_deadlines():
                if repo.upsert_deadline(deadline):
                    result.new_deadlines.append(deadline)
                    if deadline.id_turma in summaries:
                        summaries[deadline.id_turma].deadlines_new += 1

            grades = client.get_grades()
            for grade in grades:
                repo.upsert_grade(grade)
            result.grade_count = len(grades)

        _fail_on_class_errors(result)
    except Exception as exc:  # noqa: BLE001 - every failure is recorded and staged
        _fail(result, exc)
    finally:
        repo.record_sync(len(result.new_items), ok=result.ok, detail=result.error)
        conn.close()
    return result


def _sync_turma(
    client: SigaaClient, repo: Repository, turma: Turma, fetch_bodies: bool, result: SyncResult
) -> ClassSummary:
    summary = ClassSummary(id_turma=turma.id_turma, code=turma.code)
    repo.upsert_turma(turma)
    turma_html = client.enter_turma(turma)  # one fetch feeds all parsers
    try:
        found, fresh_news = _sync_turma_news(client, repo, turma, fetch_bodies, turma_html)
        summary.news_found = len(found)
    except Exception as exc:
        fresh_news = []
        summary.errors.append(SyncIssue(stage=error_stage(exc), message=str(exc)))
    context = (client, repo, turma, turma_html)
    fresh_materials = _class_fetch(summary, "materials", _sync_turma_materials, *context)
    grade_updates = _class_fetch(summary, "grades", _sync_turma_grades, *context)
    plan_deadlines = _class_fetch(summary, "plan", _sync_turma_plan, *context)
    attendance_updates = _class_fetch(summary, "attendance", _sync_turma_attendance, *context)
    _class_fetch(summary, "professors", _sync_turma_professors, *context)

    summary.news_new = len(fresh_news)
    summary.materials_new = len(fresh_materials)
    summary.grades_changed = len(grade_updates)
    summary.deadlines_new = len(plan_deadlines)
    summary.attendance_changed = len(attendance_updates)
    result.new_items.extend(fresh_news)
    result.new_materials.extend(fresh_materials)
    result.grade_updates.extend(grade_updates)
    result.new_deadlines.extend(plan_deadlines)
    result.attendance_updates.extend(attendance_updates)
    return summary


def _fail(result: SyncResult, exc: Exception) -> None:
    result.ok = False
    result.error = str(exc)
    result.error_stage = error_stage(exc)


def _fail_on_class_errors(result: SyncResult) -> None:
    """A class that could not be read fails the run, even though the rest synced."""
    broken = [s for s in result.classes if s.errors]
    if not broken:
        return
    details = "; ".join(f"{s.code or s.id_turma}: {s.errors[0].message}" for s in broken)
    result.ok = False
    result.error = f"{len(broken)} class(es) could not be read: {details}"
    result.error_stage = broken[0].errors[0].stage


def _sync_turma_news(
    client: SigaaClient, repo: Repository, turma: Turma, fetch_bodies: bool, turma_html: str
) -> tuple[list[NewsItem], list[NewsItem]]:
    """Return ``(all news on the page, the ones not stored before)``."""
    known = repo.known_news_ids(turma.id_turma)
    found = client.list_news(turma, turma_html)
    fresh: list[NewsItem] = []
    for item in found:
        if item.id in known:
            continue
        if fetch_bodies:
            item.body = client.get_news_body(turma, item.id, turma_html)
        repo.insert_news(item)
        fresh.append(item)
    return found, fresh


def _sync_turma_materials(
    client: SigaaClient, repo: Repository, turma: Turma, turma_html: str
) -> list[Material]:
    known = repo.known_material_ids(turma.id_turma)
    fresh: list[Material] = []
    for item in client.list_materials(turma, turma_html):
        if item.id in known:
            continue
        repo.insert_material(item)
        fresh.append(item)
    return fresh


def _sync_turma_grades(
    client: SigaaClient, repo: Repository, turma: Turma, turma_html: str
) -> list[TurmaGrade]:
    """Persist the class grade report; failures are recorded by the caller.
    Returns the grade in a list only when a real grade was posted or changed."""
    grade = client.get_turma_grades(turma, turma_html)
    if grade is None:
        return []
    return [grade] if repo.upsert_turma_grade(grade) else []


def _sync_turma_plan(
    client: SigaaClient, repo: Repository, turma: Turma, turma_html: str
) -> list[Deadline]:
    """Persist Plano de Curso evaluation dates as deadlines."""
    plan = client.get_course_plan(turma, turma_html)
    if plan is None:
        return []
    if plan.id_turma != turma.id_turma:
        # Never stored, and never read as "no evaluations": the navigation went wrong.
        raise NavigationError("course plan belongs to a different class")
    fresh: list[Deadline] = []
    seen: Counter[str] = Counter()
    for ev in plan.evaluations:
        slug = _slug(ev.description) or UNTITLED_EVALUATION_SLUG
        occurrence = seen[slug]
        seen[slug] += 1
        deadline = Deadline(
            id=_plan_deadline_id(turma.id_turma, slug, occurrence),
            id_turma=turma.id_turma,
            kind="avaliacao",
            title=ev.description,
            date=ev.date,
            detail="plano de curso",
        )
        if repo.upsert_deadline(deadline):
            fresh.append(deadline)
    return fresh


def _plan_deadline_id(id_turma: str, slug: str, occurrence: int) -> str:
    """Identify a plan evaluation by turma and evaluation, never by its date.

    Teachers reschedule evaluations, so a date in the id turns every move into a
    brand-new deadline. ``occurrence`` disambiguates a plan that lists the same
    evaluation description more than once.
    """
    suffix = f":{occurrence}" if occurrence else ""
    return f"plan:{id_turma}:{slug}{suffix}"


def _sync_turma_attendance(
    client: SigaaClient, repo: Repository, turma: Turma, turma_html: str
) -> list[Attendance]:
    """Persist the Frequência map; notable only after a baseline."""
    attendance = client.get_attendance(turma, turma_html)
    if attendance is None:
        return []
    return [attendance] if repo.upsert_attendance(attendance) else []


def _sync_turma_professors(
    client: SigaaClient, repo: Repository, turma: Turma, turma_html: str
) -> list[Professor]:
    """Persist the turma's teaching staff (Participantes)."""
    professors = client.list_professors(turma, turma_html)
    if professors:
        repo.replace_professors(turma.id_turma, professors)
    return professors


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.casefold()).strip("-")


def _class_fetch(summary: ClassSummary, feature: str, fetch, *args):
    """Run one class read; a failure is recorded against the class, never swallowed."""
    try:
        return fetch(*args)
    except Exception as exc:
        summary.errors.append(SyncIssue(stage=error_stage(exc), message=f"{feature}: {exc}"))
        return []
