from sigaa.services.sync import _slug
from sigaa.models import CoursePlan, PlanEvaluation


def test_slug_normalizes_accents_and_spaces():
    assert _slug("1ª avaliação") == "1a-avaliacao"
    assert _slug("Exame Final") == "exame-final"


def test_plan_evaluation_deadline_ids_are_stable():
    plan = CoursePlan(
        id_turma="369279",
        evaluations=[PlanEvaluation(date="11/06/2026", description="1ª avaliação")],
    )
    ev = plan.evaluations[0]
    deadline_id = f"plan:{plan.id_turma}:{ev.date}:{_slug(ev.description)}"
    assert deadline_id == "plan:369279:11/06/2026:1a-avaliacao"
