"""Shared JSON-safe presentation of extension participations (CLI and MCP)."""

from __future__ import annotations

from dataclasses import asdict

from .models import ExtensionParticipation
from .parsers.extensao import KIND_AUDIENCE, KIND_EXTENSION_STUDENT, KIND_TEAM_MEMBER

PARTICIPATION_KINDS = (KIND_TEAM_MEMBER, KIND_AUDIENCE, KIND_EXTENSION_STUDENT)


def participations_to_dict(participations: list[ExtensionParticipation]) -> dict:
    """Return the stable JSON contract shared by CLI and MCP."""
    counts = {kind: 0 for kind in PARTICIPATION_KINDS}
    for participation in participations:
        counts[participation.kind] = counts.get(participation.kind, 0) + 1
    counts["declarations_available"] = sum(p.declaration_available for p in participations)
    counts["certificates_available"] = sum(p.certificate_available for p in participations)
    return {
        "participations": [asdict(p) for p in participations],
        "counts": counts,
    }
