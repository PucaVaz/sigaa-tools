"""Parse the integralização JSON: curriculum components and prerequisite logic."""

from __future__ import annotations

import re

from ..models import CurriculumComponent

_CODE_RE = re.compile(r"[A-Z0-9]{7,9}")
_SAFE_BOOL_EXPR_RE = re.compile(r"^[\sTrueFalsandor()]+$")


def parse_components(data: dict) -> list[CurriculumComponent]:
    done = {
        d["codigo"] for d in data.get("disciplinas", []) if d.get("situacao") == "CONCLUIDO"
    }
    components = []
    for d in data.get("disciplinas", []):
        prereq = d.get("expressaoPreRequisito", "")
        components.append(
            CurriculumComponent(
                code=d.get("codigo", ""),
                name=d.get("nome", ""),
                kind=d.get("tipoIntegralizacao", ""),
                period=d.get("periodo", 0),
                hours=d.get("cargaHoraria", 0),
                mandatory=bool(d.get("obrigatoria")),
                completed=d.get("situacao") == "CONCLUIDO",
                prerequisite=prereq or None,
                prerequisite_met=prerequisite_met(prereq, done),
            )
        )
    return components


def prerequisite_met(expression: str | None, completed_codes: set[str]) -> bool:
    """Evaluate a SIGAA prerequisite expression like ``( A ) E ( B OU C )``."""
    if not expression or not expression.strip():
        return True
    expr = _CODE_RE.sub(lambda m: str(m.group(0) in completed_codes), expression)
    expr = expr.replace(" E ", " and ").replace(" OU ", " or ")
    if not _SAFE_BOOL_EXPR_RE.match(expr):
        raise ValueError(f"unparseable prerequisite expression: {expression!r}")
    return bool(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 - vetted True/False/and/or only
