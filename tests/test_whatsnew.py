from sigaa.models import Deadline, Material, NewsItem, Turma, TurmaGrade
from sigaa.services import whatsnew
from sigaa.store.db import connect
from sigaa.store.repository import Repository

ID_TURMA = "369279"


def _seeded_repo(tmp_path) -> Repository:
    repo = Repository(connect(tmp_path / "t.db"))
    repo.upsert_turma(Turma(id_turma=ID_TURMA, name="SD", code="DSCO00022"))
    repo.insert_news(NewsItem(id="n1", id_turma=ID_TURMA, date="03/06/2026 10:00", title="aviso"))
    repo.insert_material(
        Material(id="m1", id_turma=ID_TURMA, topic="t", title="slides", kind="file")
    )
    repo.upsert_deadline(
        Deadline(id="d1", id_turma=ID_TURMA, kind="avaliacao", title="prova", date="11/06")
    )
    repo.upsert_turma_grade(TurmaGrade(id_turma=ID_TURMA, units=["8.0"], result="8.0"))
    return repo


def test_collect_gathers_all_channels(tmp_path):
    feed = whatsnew.collect(_seeded_repo(tmp_path))
    assert feed.total() == 4
    assert len(feed.news) == 1
    assert len(feed.materials) == 1
    assert len(feed.deadlines) == 1
    assert len(feed.grades) == 1


def test_mark_seen_empties_the_feed(tmp_path):
    repo = _seeded_repo(tmp_path)
    feed = whatsnew.collect(repo)
    whatsnew.mark_seen(repo, feed)
    assert whatsnew.collect(repo).total() == 0


def test_empty_grade_excluded_from_feed(tmp_path):
    repo = Repository(connect(tmp_path / "t.db"))
    repo.upsert_turma(Turma(id_turma=ID_TURMA, name="SD", code="DSCO00022"))
    repo.upsert_turma_grade(TurmaGrade(id_turma=ID_TURMA, units=[], status="MATRICULADO"))
    assert whatsnew.collect(repo).total() == 0
