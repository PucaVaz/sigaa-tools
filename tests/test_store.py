import sqlite3

import pytest

from sigaa.models import NewsItem, Student, Turma
from sigaa.store.db import _SCHEMA
from sigaa.store.repository import Repository


@pytest.fixture
def repo():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return Repository(conn)


def test_upsert_student_idempotent(repo):
    repo.upsert_student(Student(matricula="1", name="A", course="C", email="e", semester="2026.1"))
    repo.upsert_student(Student(matricula="1", name="A2", course="C", email="e", semester="2026.1"))
    student = repo.get_student()
    assert student.name == "A2"


def test_upsert_turma_and_lookup(repo):
    repo.upsert_turma(Turma(id_turma="369279", name="SD", code="DSCO00022", schedule_raw="35M45"))
    assert len(repo.get_turmas()) == 1
    assert repo.get_turma("DSCO00022").id_turma == "369279"
    assert repo.get_turma("369279").code == "DSCO00022"


def test_news_dedup(repo):
    repo.upsert_turma(Turma(id_turma="369279", name="SD"))
    item = NewsItem(id="46214565", id_turma="369279", date="03/06/2026 10:57", title="Feriado")
    repo.insert_news(item)
    repo.insert_news(item)  # duplicate id is ignored
    assert len(repo.get_news()) == 1
    assert repo.known_news_ids("369279") == {"46214565"}


def test_news_filters_and_mark_seen(repo):
    repo.upsert_turma(Turma(id_turma="369279", name="SD"))
    repo.insert_news(NewsItem(id="a", id_turma="369279", date="2026-01-01", title="old"))
    repo.insert_news(NewsItem(id="b", id_turma="369279", date="2026-02-01", title="new"))
    assert len(repo.get_news(unread_only=True)) == 2
    repo.mark_news_seen(["a", "b"])
    assert repo.get_news(unread_only=True) == []


def test_update_news_body(repo):
    repo.upsert_turma(Turma(id_turma="369279", name="SD"))
    repo.insert_news(NewsItem(id="a", id_turma="369279", date="x", title="t"))
    repo.update_news_body("a", "full text")
    assert repo.get_news()[0].body == "full text"
