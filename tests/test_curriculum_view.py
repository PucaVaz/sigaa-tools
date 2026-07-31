from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path

from sigaa.curriculum import curriculum_to_dict, filter_curriculum_components
from sigaa.parsers.curriculum import parse_curriculum


FIXTURE = Path(__file__).parent / "fixtures" / "curriculum.json"


def _curriculum():
    return parse_curriculum(FIXTURE.read_text(encoding="utf-8"))


def test_current_view_returns_enrolled_and_required_pending_only():
    curriculum = _curriculum()

    selected = filter_curriculum_components(curriculum.components)

    assert {component.code for component in selected} == {"SYN0002", "SYN0003"}


def test_filters_compose_without_changing_source_components():
    curriculum = _curriculum()

    selected = filter_curriculum_components(
        curriculum.components,
        status="pending",
        required_only=True,
        period=2,
    )

    assert [component.code for component in selected] == ["SYN0003"]
    assert len(curriculum.components) == 5


def test_json_contract_is_private_and_exposes_official_cra_source():
    curriculum = replace(
        _curriculum(),
        cra=Decimal("8.42"),
        cra_source="academic_transcript",
    )

    data = curriculum_to_dict(curriculum, status="all")

    assert data["schema_version"] == 1
    assert data["cra"] == {"value": 8.42, "source": "academic_transcript"}
    assert data["counts"] == {
        "completed": 1,
        "enrolled": 1,
        "pending": 2,
        "unknown": 1,
        "pending_required": 1,
        "pending_optional": 1,
    }
    assert data["returned_count"] == 5
    assert "idDiscente" not in json.dumps(data)


def test_requirements_are_opt_in():
    curriculum = _curriculum()

    compact = curriculum_to_dict(curriculum, status="pending")
    detailed = curriculum_to_dict(
        curriculum,
        status="pending",
        include_requirements=True,
    )

    assert "prerequisite" not in compact["components"][0]
    by_code = {item["code"]: item for item in detailed["components"]}
    assert by_code["SYN0003"]["prerequisite"] == "( SYN0001 )"
    assert by_code["SYN0004"]["prerequisite"] is None


def test_progress_uses_derived_remaining_hours():
    data = curriculum_to_dict(_curriculum())

    assert data["progress"][0] == {
        "description": "Total",
        "completed_hours": 120,
        "total_hours": 300,
        "remaining_hours": 180,
        "completed_percent": 40.0,
    }
