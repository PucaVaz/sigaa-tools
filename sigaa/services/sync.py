"""Sync: fetch live SIGAA state, diff against the store, persist new news.

Idempotent. A news id already in the store is not new, so re-running is safe and
reports zero new items once caught up.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..client import SigaaClient
from ..config import Settings
from ..models import Deadline, Material, NewsItem, Student, Turma
from ..store.db import connect
from ..store.repository import Repository


@dataclass
class SyncResult:
    student: Student | None = None
    turma_count: int = 0
    new_items: list[NewsItem] = field(default_factory=list)
    new_materials: list[Material] = field(default_factory=list)
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
                result.new_items.extend(_sync_turma_news(client, repo, turma, fetch_bodies))
                result.new_materials.extend(_sync_turma_materials(client, repo, turma))

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
    client: SigaaClient, repo: Repository, turma: Turma, fetch_bodies: bool
) -> list[NewsItem]:
    known = repo.known_news_ids(turma.id_turma)
    fresh: list[NewsItem] = []
    for item in client.list_news(turma):
        if item.id in known:
            continue
        if fetch_bodies:
            item.body = client.get_news_body(turma, item.id)
        repo.insert_news(item)
        fresh.append(item)
    return fresh


def _sync_turma_materials(
    client: SigaaClient, repo: Repository, turma: Turma
) -> list[Material]:
    known = repo.known_material_ids(turma.id_turma)
    fresh: list[Material] = []
    for item in client.list_materials(turma):
        if item.id in known:
            continue
        repo.insert_material(item)
        fresh.append(item)
    return fresh
