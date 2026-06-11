"""Sync: fetch live SIGAA state, diff against the store, persist new news.

Idempotent. A news id already in the store is not new, so re-running is safe and
reports zero new items once caught up.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from ..client import SigaaClient
from ..config import Settings
from ..models import Attendance, Deadline, Material, NewsItem, Student, Turma, TurmaGrade
from ..store.db import connect
from ..store.repository import Repository


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


def sync(settings: Settings, fetch_bodies: bool = False) -> SyncResult:
    password = settings.resolve_password()
    if not settings.username or not password:
        return SyncResult(ok=False, error="missing credentials (set SIGAA_USER and keyring/SIGAA_PASS)")

    conn = connect(settings.db_path)
    repo = Repository(conn)
    result = SyncResult()
    try:
        with SigaaClient(settings.username, password) as client:
            result.student = client.get_student()
            repo.upsert_student(result.student)

            turmas = client.list_turmas()
            result.turma_count = len(turmas)
            for turma in turmas:
                repo.upsert_turma(turma)
                turma_html = client.enter_turma(turma)  # one fetch feeds all parsers
                result.new_items.extend(
                    _sync_turma_news(client, repo, turma, fetch_bodies, turma_html)
                )
                result.new_materials.extend(
                    _sync_turma_materials(client, repo, turma, turma_html)
                )
                result.grade_updates.extend(
                    _sync_turma_grades(client, repo, turma, turma_html)
                )
                result.new_deadlines.extend(
                    _sync_turma_plan(client, repo, turma, turma_html)
                )
                result.attendance_updates.extend(
                    _sync_turma_attendance(client, repo, turma, turma_html)
                )

            for deadline in client.list_deadlines():
                if repo.upsert_deadline(deadline):
                    result.new_deadlines.append(deadline)

            grades = client.get_grades()
            for grade in grades:
                repo.upsert_grade(grade)
            result.grade_count = len(grades)

        repo.record_sync(len(result.new_items))
    except Exception as exc:  # noqa: BLE001 - record and surface the failure
        result.ok = False
        result.error = str(exc)
        repo.record_sync(len(result.new_items), ok=False, detail=str(exc))
    finally:
        conn.close()
    return result


def _sync_turma_news(
    client: SigaaClient, repo: Repository, turma: Turma, fetch_bodies: bool, turma_html: str
) -> list[NewsItem]:
    known = repo.known_news_ids(turma.id_turma)
    fresh: list[NewsItem] = []
    for item in client.list_news(turma, turma_html):
        if item.id in known:
            continue
        if fetch_bodies:
            item.body = client.get_news_body(turma, item.id, turma_html)
        repo.insert_news(item)
        fresh.append(item)
    return fresh


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
    """Best-effort: a turma whose Ver Notas is missing/bounces must not abort sync.
    Returns the grade in a list only when a real grade was posted or changed."""
    try:
        grade = client.get_turma_grades(turma, turma_html)
    except Exception:  # noqa: BLE001 - per-turma report is optional
        return []
    if grade is None:
        return []
    return [grade] if repo.upsert_turma_grade(grade) else []


def _sync_turma_plan(
    client: SigaaClient, repo: Repository, turma: Turma, turma_html: str
) -> list[Deadline]:
    """Best-effort: persist Plano de Curso evaluation dates as deadlines."""
    try:
        plan = client.get_course_plan(turma, turma_html)
    except Exception:  # noqa: BLE001 - per-turma plan is optional
        return []
    if plan is None:
        return []
    fresh: list[Deadline] = []
    for ev in plan.evaluations:
        deadline = Deadline(
            id=f"plan:{plan.id_turma}:{ev.date}:{_slug(ev.description)}",
            id_turma=plan.id_turma,
            kind="avaliacao",
            title=ev.description,
            date=ev.date,
            detail="plano de curso",
        )
        if repo.upsert_deadline(deadline):
            fresh.append(deadline)
    return fresh


def _sync_turma_attendance(
    client: SigaaClient, repo: Repository, turma: Turma, turma_html: str
) -> list[Attendance]:
    """Best-effort: persist the Frequência map; notable only after a baseline."""
    try:
        attendance = client.get_attendance(turma, turma_html)
    except Exception:  # noqa: BLE001 - per-turma attendance is optional
        return []
    if attendance is None:
        return []
    return [attendance] if repo.upsert_attendance(attendance) else []


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.casefold()).strip("-")
