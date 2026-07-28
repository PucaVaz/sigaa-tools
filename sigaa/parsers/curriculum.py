"""Parse SIGAA's curriculum integration JSON response."""

from __future__ import annotations

import json
import math
from typing import Any

from ..models import CurriculumComponent, CurriculumStatus, WorkloadProgress


class CurriculumDataError(ValueError):
    """Raised when SIGAA does not return a valid curriculum payload."""


_STATUS_MAP = {
    "CONCLUIDO": "completed",
    "MATRICULADO": "enrolled",
    "PENDENTE": "pending",
}


def parse_curriculum(data: object) -> CurriculumStatus:
    """Validate and normalize a curriculum integration payload.

    ``data`` may be an already-decoded JSON object, a JSON string, or UTF-8
    bytes. Error messages intentionally omit response bodies because an
    authentication failure can return a page containing private data.
    """

    payload = _decode_payload(data)
    progress_data = _required_list(payload, "integralizacoes")
    components_data = _required_list(payload, "disciplinas")

    progress = [
        _parse_progress(item, index)
        for index, item in enumerate(progress_data)
    ]
    components = [
        _parse_component(item, index)
        for index, item in enumerate(components_data)
    ]

    return CurriculumStatus(
        curriculum=_required_string(payload, "curriculo"),
        max_semester_workload_hours=_optional_int(
            payload.get("cargaHorariaMaximaSemestre")
        ),
        min_semester_workload_hours=_optional_int(
            payload.get("cargaHorariaMinimaSemestre")
        ),
        maximum_completion_term=_optional_string(payload.get("prazoMaximo")),
        progress=progress,
        components=components,
    )


def _decode_payload(data: object) -> dict[str, Any]:
    decoded: object
    if isinstance(data, bytes):
        try:
            decoded = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise CurriculumDataError("Invalid curriculum response") from None
    elif isinstance(data, str):
        try:
            decoded = json.loads(data)
        except json.JSONDecodeError:
            raise CurriculumDataError("Invalid curriculum response") from None
    else:
        decoded = data

    if not isinstance(decoded, dict):
        raise CurriculumDataError("Invalid curriculum response")
    return decoded


def _required_list(payload: dict[str, Any], key: str) -> list[object]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise CurriculumDataError(f"Invalid curriculum field: {key}")
    return value


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CurriculumDataError(f"Invalid curriculum field: {key}")
    return value.strip()


def _parse_progress(item: object, index: int) -> WorkloadProgress:
    if not isinstance(item, dict):
        raise CurriculumDataError(
            f"Invalid curriculum progress entry at index {index}"
        )

    completed = _required_non_negative_int(item.get("concluido"), "concluido")
    total = _required_non_negative_int(item.get("total"), "total")
    remaining_raw = item.get("porcentagem")
    reported_completed = _completed_from_remaining(remaining_raw)

    if total > 0:
        completed_percent = round((completed / total) * 100, 2)
    elif completed == 0 and reported_completed is not None:
        completed_percent = reported_completed
    else:
        completed_percent = 0.0

    if not isinstance(remaining_raw, (str, int, float)) or isinstance(
        remaining_raw, bool
    ):
        remaining_raw = None

    return WorkloadProgress(
        description=_required_string(item, "descricao"),
        completed_hours=completed,
        total_hours=total,
        completed_percent=completed_percent,
        remaining_percent_raw=remaining_raw,
    )


def _completed_from_remaining(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        normalized = value.strip().replace(",", ".")
        if not normalized:
            return None
        try:
            remaining = float(normalized)
        except ValueError:
            return None
    elif isinstance(value, (int, float)):
        remaining = float(value)
    else:
        return None

    if not math.isfinite(remaining):
        return None
    return round(100.0 - remaining, 2)


def _parse_component(item: object, index: int) -> CurriculumComponent:
    if not isinstance(item, dict):
        raise CurriculumDataError(
            f"Invalid curriculum component entry at index {index}"
        )

    period_raw = item.get("periodo")
    period_number = _optional_int(period_raw)
    period = period_number if period_number is not None and period_number > 0 else None

    status_raw = item.get("situacao")
    if status_raw is not None and not isinstance(status_raw, str):
        raise CurriculumDataError(
            f"Invalid curriculum component status at index {index}"
        )
    status_key = status_raw.strip().upper() if status_raw is not None else ""
    status = _STATUS_MAP.get(status_key, "unknown")

    required = item.get("obrigatoria")
    if not isinstance(required, bool):
        raise CurriculumDataError(
            f"Invalid curriculum component requirement at index {index}"
        )

    return CurriculumComponent(
        code=_required_string(item, "codigo"),
        name=_required_string(item, "nome"),
        integration_type=_required_string(item, "tipoIntegralizacao"),
        period=period,
        workload_hours=_required_non_negative_int(
            item.get("cargaHoraria"), "cargaHoraria"
        ),
        required=required,
        status=status,
        status_raw=status_raw,
        prerequisite=_optional_string(item.get("expressaoPreRequisito")),
        corequisite=_optional_string(item.get("expressaoCoRequisito")),
        period_raw=_safe_raw_period(period_raw),
    )


def _required_non_negative_int(value: object, field: str) -> int:
    parsed = _optional_int(value)
    if parsed is None or parsed < 0:
        raise CurriculumDataError(f"Invalid curriculum field: {field}")
    return parsed


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        return int(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return int(normalized)
        except ValueError:
            return None
    return None


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _safe_raw_period(value: object) -> int | float | str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, str)):
        return value
    return None
