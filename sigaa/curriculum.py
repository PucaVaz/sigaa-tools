"""Shared curriculum filtering and JSON-safe presentation."""

from __future__ import annotations

from typing import Literal

from .models import CurriculumComponent, CurriculumStatus

ComponentView = Literal["current", "enrolled", "pending", "completed", "all"]
COMPONENT_VIEWS: tuple[ComponentView, ...] = (
    "current",
    "enrolled",
    "pending",
    "completed",
    "all",
)


def filter_curriculum_components(
    components: list[CurriculumComponent],
    *,
    status: ComponentView = "current",
    required_only: bool = False,
    period: int | None = None,
) -> list[CurriculumComponent]:
    """Filter components without changing summary counts or progress."""
    if status not in COMPONENT_VIEWS:
        choices = ", ".join(COMPONENT_VIEWS)
        raise ValueError(f"unknown component status {status!r}; choose one of: {choices}")

    selected = []
    for component in components:
        if status == "current":
            visible = component.status == "enrolled" or (
                component.status == "pending" and component.required
            )
        elif status == "all":
            visible = True
        else:
            visible = component.status == status
        if not visible:
            continue
        if required_only and not component.required:
            continue
        if period is not None and component.period != period:
            continue
        selected.append(component)
    return selected


def curriculum_to_dict(
    curriculum: CurriculumStatus,
    *,
    status: ComponentView = "current",
    required_only: bool = False,
    period: int | None = None,
    include_requirements: bool = False,
) -> dict:
    """Return the stable JSON contract shared by CLI and MCP."""
    selected = filter_curriculum_components(
        curriculum.components,
        status=status,
        required_only=required_only,
        period=period,
    )
    counts = {
        state: sum(component.status == state for component in curriculum.components)
        for state in ("completed", "enrolled", "pending", "unknown")
    }
    counts["pending_required"] = sum(
        component.status == "pending" and component.required
        for component in curriculum.components
    )
    counts["pending_optional"] = sum(
        component.status == "pending" and not component.required
        for component in curriculum.components
    )

    return {
        "schema_version": 1,
        "curriculum": curriculum.curriculum,
        "maximum_completion_term": curriculum.maximum_completion_term,
        "semester_workload_hours": {
            "minimum": curriculum.min_semester_workload_hours,
            "maximum": curriculum.max_semester_workload_hours,
        },
        "cra": {
            "value": float(curriculum.cra) if curriculum.cra is not None else None,
            "source": curriculum.cra_source,
        },
        "progress": [
            {
                "description": item.description,
                "completed_hours": item.completed_hours,
                "total_hours": item.total_hours,
                "remaining_hours": max(item.total_hours - item.completed_hours, 0),
                "completed_percent": item.completed_percent,
            }
            for item in curriculum.progress
        ],
        "counts": counts,
        "query": {
            "status": status,
            "required_only": required_only,
            "period": period,
            "include_requirements": include_requirements,
        },
        "returned_count": len(selected),
        "components": [
            _component_to_dict(
                component,
                include_requirements=include_requirements,
            )
            for component in selected
        ],
    }


def _component_to_dict(
    component: CurriculumComponent,
    *,
    include_requirements: bool,
) -> dict:
    data = {
        "code": component.code,
        "name": component.name,
        "status": component.status,
        "status_raw": component.status_raw,
        "required": component.required,
        "period": component.period,
        "period_raw": component.period_raw,
        "workload_hours": component.workload_hours,
        "integration_type": component.integration_type,
    }
    if include_requirements:
        data["prerequisite"] = component.prerequisite
        data["corequisite"] = component.corequisite
    return data
