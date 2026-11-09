"""Shared JSON-safe presentation of extension data (CLI and MCP)."""

from __future__ import annotations

from dataclasses import asdict

from .models import (
    ExtensionOpportunity,
    ExtensionParticipation,
    ExtensionRegistration,
    ExtensionSelectionForm,
)
from .parsers._common import fold
from .parsers.extensao import KIND_AUDIENCE, KIND_EXTENSION_STUDENT, KIND_TEAM_MEMBER

PARTICIPATION_KINDS = (KIND_TEAM_MEMBER, KIND_AUDIENCE, KIND_EXTENSION_STUDENT)
# The opportunity search answers with every extension action of the year in one
# page (about 3 MB at UFPB), which SIGAA can take over a minute to render.
OPPORTUNITY_SEARCH_TIMEOUT_SECONDS = 240.0


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


def filter_opportunities(
    opportunities: list[ExtensionOpportunity], query: str | None
) -> list[ExtensionOpportunity]:
    """Opportunities whose title contains every word of the query.

    Matching ignores case and accents; an empty query keeps everything.
    """
    words = fold(query or "").split()
    return [o for o in opportunities if all(word in fold(o.title) for word in words)]


def opportunities_to_dict(
    opportunities: list[ExtensionOpportunity], *, listed: int, query: str | None
) -> dict:
    """Return the stable JSON contract shared by CLI and MCP."""
    return {
        "query": query or None,
        "listed": listed,
        "matched": len(opportunities),
        "opportunities": [asdict(o) for o in opportunities],
    }


def selection_to_dict(
    form: ExtensionSelectionForm, registration: ExtensionRegistration | None
) -> dict:
    """One selection attempt: the action and, once submitted, SIGAA's answer."""
    return {
        "action": asdict(form),
        "submitted": registration is not None,
        "status": registration.status if registration else "preview",
        "messages": registration.messages if registration else [],
    }
