from pathlib import Path

import pytest

from sigaa.errors import NavigationError
from sigaa.models import CoursePlan, PlanEvaluation, Turma
from sigaa.parsers.plano import parse_course_plan
from sigaa.services.sync import _plan_deadline_id, _slug, _sync_turma_plan
from sigaa.store.db import connect
from sigaa.store.repository import Repository

FIXTURES = Path(__file__).parent / "fixtures"
PLANO = (FIXTURES / "plano.html").read_text(encoding="utf-8")
ID_TURMA = "369279"
OTHER_ID_TURMA = "379107"


class _StubClient:
    """Returns a canned plan for every turma, like a bounced Turma Virtual would."""

    def __init__(self, plan: CoursePlan | None):
        self.plan = plan

    def get_course_plan(self, turma: Turma, turma_html: str | None = None) -> CoursePlan | None:
        return self.plan


def _repo(tmp_path, *id_turmas: str) -> Repository:
    repo = Repository(connect(tmp_path / "t.db"))
    for id_turma in id_turmas or (ID_TURMA,):
        repo.upsert_turma(Turma(id_turma=id_turma, name="SD", code="DSCO00022"))
    return repo


def _turma(id_turma: str = ID_TURMA) -> Turma:
    return Turma(id_turma=id_turma, name="SD", code="DSCO00022")


def test_slug_normalizes_accents_and_spaces():
    assert _slug("1ª avaliação") == "1a-avaliacao"
    assert _slug("Exame Final") == "exame-final"


def test_plan_deadline_ids_are_scoped_to_the_turma():
    assert _plan_deadline_id(ID_TURMA, _slug("1ª avaliação"), 0) == "plan:369279:1a-avaliacao"
    assert _plan_deadline_id(OTHER_ID_TURMA, _slug("1ª avaliação"), 0) != _plan_deadline_id(
        ID_TURMA, _slug("1ª avaliação"), 0
    )


def test_plan_deadline_id_ignores_the_evaluation_date():
    """A rescheduled evaluation keeps its identity instead of looking brand new."""
    assert _plan_deadline_id(ID_TURMA, "exame-final", 0) == "plan:369279:exame-final"


def test_repeated_evaluation_descriptions_get_distinct_ids():
    first = _plan_deadline_id(ID_TURMA, "reposicao", 0)
    second = _plan_deadline_id(ID_TURMA, "reposicao", 1)
    assert first != second


def test_syncing_the_same_plan_twice_yields_no_new_deadlines(tmp_path):
    repo = _repo(tmp_path)
    client = _StubClient(parse_course_plan(PLANO, ID_TURMA))
    first = _sync_turma_plan(client, repo, _turma(), PLANO)
    assert len(first) == 5
    assert _sync_turma_plan(client, repo, _turma(), PLANO) == []


def test_rescheduled_evaluation_updates_in_place(tmp_path):
    repo = _repo(tmp_path)
    plan = CoursePlan(
        id_turma=ID_TURMA,
        evaluations=[PlanEvaluation(date="17/12/2026", description="Exame Final")],
    )
    assert len(_sync_turma_plan(_StubClient(plan), repo, _turma(), PLANO)) == 1

    moved = CoursePlan(
        id_turma=ID_TURMA,
        evaluations=[PlanEvaluation(date="21/12/2026", description="Exame Final")],
    )
    assert _sync_turma_plan(_StubClient(moved), repo, _turma(), PLANO) == []
    stored = repo.get_deadlines(id_turma=ID_TURMA)
    assert len(stored) == 1
    assert stored[0].date == "21/12/2026"


def test_plan_from_another_turma_is_refused(tmp_path):
    """A page that cannot be attributed to this turma must not be persisted."""
    repo = _repo(tmp_path, ID_TURMA, OTHER_ID_TURMA)
    plan = CoursePlan(
        id_turma=OTHER_ID_TURMA,
        evaluations=[PlanEvaluation(date="17/12/2026", description="Exame Final")],
    )
    with pytest.raises(NavigationError):
        _sync_turma_plan(_StubClient(plan), repo, _turma(ID_TURMA), PLANO)
    assert repo.get_deadlines() == []


def test_plan_rows_do_not_leak_across_turmas(tmp_path):
    repo = _repo(tmp_path, ID_TURMA, OTHER_ID_TURMA)
    for id_turma in (ID_TURMA, OTHER_ID_TURMA):
        plan = parse_course_plan(PLANO, id_turma)
        _sync_turma_plan(_StubClient(plan), repo, _turma(id_turma), PLANO)

    mine = repo.get_deadlines(id_turma=ID_TURMA)
    theirs = repo.get_deadlines(id_turma=OTHER_ID_TURMA)
    assert len(mine) == len(theirs) == 5
    assert all(d.id.startswith(f"plan:{ID_TURMA}:") for d in mine)
    assert all(d.id.startswith(f"plan:{OTHER_ID_TURMA}:") for d in theirs)


def test_legacy_date_keyed_plan_deadlines_are_dropped_on_connect(tmp_path):
    db = tmp_path / "t.db"
    repo = _repo(tmp_path)
    repo._conn.execute(
        "INSERT INTO deadline (id, id_turma, kind, title, date) VALUES (?, ?, ?, ?, ?)",
        (f"plan:{ID_TURMA}:17/12/2026:exame-final", ID_TURMA, "avaliacao", "Exame Final", "17/12/2026"),
    )
    repo._conn.execute(
        "INSERT INTO deadline (id, id_turma, kind, title, date) VALUES (?, ?, ?, ?, ?)",
        ("portal-event-1", ID_TURMA, "avaliacao", "Prova", "11/06/2026"),
    )
    repo._conn.commit()
    repo._conn.close()

    survivors = [d.id for d in Repository(connect(db)).get_deadlines()]
    assert survivors == ["portal-event-1"]
