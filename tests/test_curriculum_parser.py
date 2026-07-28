from dataclasses import asdict
import json
from pathlib import Path

import pytest

from sigaa.parsers.curriculum import CurriculumDataError, parse_curriculum


FIXTURE = Path(__file__).parent / "fixtures" / "curriculum.json"


def test_parse_curriculum_normalizes_progress_without_student_id():
    curriculum = parse_curriculum(FIXTURE.read_text(encoding="utf-8"))

    assert curriculum.curriculum == "999999 - 2099.1"
    assert curriculum.max_semester_workload_hours == 480
    assert curriculum.min_semester_workload_hours == 240
    assert curriculum.maximum_completion_term == "2104.2"
    assert curriculum.cra is None
    assert curriculum.cra_source == "unavailable"

    total = curriculum.progress[0]
    assert total.completed_hours == 120
    assert total.total_hours == 300
    assert total.completed_percent == 40.0
    assert total.remaining_percent_raw == "60,00"

    serialized = json.dumps(asdict(curriculum), default=str)
    assert "idDiscente" not in serialized


def test_parse_curriculum_normalizes_states_and_preserves_raw_values():
    curriculum = parse_curriculum(FIXTURE.read_bytes())
    by_code = {component.code: component for component in curriculum.components}

    assert by_code["SYN0001"].status == "completed"
    assert by_code["SYN0001"].status_raw == "CONCLUIDO"
    assert by_code["SYN0002"].status == "enrolled"
    assert by_code["SYN0002"].period is None
    assert by_code["SYN0002"].period_raw == -1
    assert by_code["SYN0003"].status == "pending"
    assert by_code["SYN0004"].period is None
    assert by_code["SYN0004"].period_raw == 0
    assert by_code["SYN0005"].status == "unknown"
    assert by_code["SYN0005"].status_raw == "EM_ANALISE"
    assert by_code["SYN0005"].integration_type == "ZX"


def test_optional_pending_components_remain_optional():
    curriculum = parse_curriculum(FIXTURE.read_text(encoding="utf-8"))
    pending = [
        component
        for component in curriculum.components
        if component.status == "pending"
    ]

    assert {component.required for component in pending} == {True, False}
    assert next(c for c in pending if c.code == "SYN0004").required is False


def test_prerequisites_and_corequisites_are_optional():
    curriculum = parse_curriculum(FIXTURE.read_text(encoding="utf-8"))
    by_code = {component.code: component for component in curriculum.components}

    assert by_code["SYN0001"].prerequisite is None
    assert by_code["SYN0001"].corequisite is None
    assert by_code["SYN0003"].prerequisite == "( SYN0001 )"
    assert by_code["SYN0003"].corequisite == "( SYN0004 )"


def test_completed_percent_uses_workload_as_source_of_truth():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["integralizacoes"][0]["porcentagem"] = "99,99"

    curriculum = parse_curriculum(payload)

    assert curriculum.progress[0].completed_percent == 40.0


@pytest.mark.parametrize(
    "payload",
    [
        "<html><body>sessao expirada</body></html>",
        b"<html><body>login</body></html>",
        '{"curriculo": "sintetico"}',
        [],
    ],
)
def test_invalid_payload_raises_without_echoing_body(payload):
    with pytest.raises(CurriculumDataError) as exc_info:
        parse_curriculum(payload)

    message = str(exc_info.value)
    assert "sessao expirada" not in message
    assert "<html>" not in message
    assert "login" not in message
