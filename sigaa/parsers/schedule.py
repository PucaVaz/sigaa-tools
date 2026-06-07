"""Decode SIGAA schedule codes into structured ``Schedule`` objects.

Format: ``<days><shift><slots>`` per token, possibly several tokens.
Days: 2=Mon .. 7=Sat. Shift: M/T/N. e.g. ``7M1 35N34`` -> Sat morning slot 1,
plus Tue+Thu night slots 3-4.
"""

from __future__ import annotations

import re

from ..models import Schedule

_TOKEN_RE = re.compile(r"(\d+)([MTN])(\d+)")
_DAY_NAMES = {2: "Seg", 3: "Ter", 4: "Qua", 5: "Qui", 6: "Sex", 7: "Sáb", 1: "Dom"}


def decode_schedule(raw: str | None) -> list[Schedule]:
    if not raw:
        return []
    # Drop trailing date ranges like "(27/04/2026 - 13/08/2026)".
    cleaned = re.sub(r"\([^)]*\)", " ", raw)
    schedules: list[Schedule] = []
    for days, shift, slots in _TOKEN_RE.findall(cleaned):
        schedules.append(
            Schedule(
                raw=f"{days}{shift}{slots}",
                days=[int(d) for d in days],
                shift=shift,
                slots=[int(s) for s in slots],
            )
        )
    return schedules


def day_name(day: int) -> str:
    return _DAY_NAMES.get(day, str(day))
