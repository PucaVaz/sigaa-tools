"""Build an iCalendar (.ics) feed from classes and deadlines.

Classes become weekly recurring events using the campus slot-time table
(UNCONFIRMED — see config). Deadlines become all-day events on their due date.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from ..config import SLOT_TIMES_UNCONFIRMED
from ..models import Deadline, Turma
from ..parsers.schedule import decode_schedule

_SLOT_MINUTES = 50
# SIGAA day digit -> (python weekday, ICS BYDAY token). 2=Mon .. 7=Sat, 1=Sun.
_DAY_MAP = {2: (0, "MO"), 3: (1, "TU"), 4: (2, "WE"), 5: (3, "TH"),
            6: (4, "FR"), 7: (5, "SA"), 1: (6, "SU")}


def build_calendar(
    turmas: list[Turma],
    deadlines: list[Deadline],
    term_start: date | None = None,
    year: int | None = None,
) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//sigaa-ai-agent//PT-BR", "CALSCALE:GREGORIAN"]
    anchor = term_start or date.today()
    for turma in turmas:
        lines.extend(_class_events(turma, anchor))
    for deadline in deadlines:
        event = _deadline_event(deadline, year or anchor.year)
        if event:
            lines.extend(event)
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _class_events(turma: Turma, anchor: date) -> list[str]:
    out: list[str] = []
    for session in decode_schedule(turma.schedule_raw):
        times = SLOT_TIMES_UNCONFIRMED.get(session.shift)
        if not times or not session.slots or not session.days:
            continue
        start_clock = times.get(min(session.slots))
        end_slot = times.get(max(session.slots))
        if not start_clock or not end_slot:
            continue
        start_t = _parse_time(start_clock)
        end_t = _add_minutes(_parse_time(end_slot), _SLOT_MINUTES)
        for day in session.days:
            if day not in _DAY_MAP:
                continue
            first = _next_weekday(anchor, _DAY_MAP[day][0])
            uid = f"class-{turma.id_turma}-{session.shift}{day}{''.join(map(str, session.slots))}@sigaa"
            out.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:{uid}",
                    f"SUMMARY:{_escape(turma.name)}",
                    f"LOCATION:{_escape(turma.room or '')}",
                    f"DTSTART:{_dt(first, start_t)}",
                    f"DTEND:{_dt(first, end_t)}",
                    f"RRULE:FREQ=WEEKLY;BYDAY={_DAY_MAP[day][1]}",
                    "END:VEVENT",
                ]
            )
    return out


def _deadline_event(deadline: Deadline, year: int) -> list[str] | None:
    due = _last_date(deadline.date, year)
    if not due:
        return None
    return [
        "BEGIN:VEVENT",
        f"UID:deadline-{deadline.id}@sigaa",
        f"SUMMARY:[{deadline.kind}] {_escape(deadline.title)}",
        f"DTSTART;VALUE=DATE:{due:%Y%m%d}",
        f"DTEND;VALUE=DATE:{(due + timedelta(days=1)):%Y%m%d}",
        "END:VEVENT",
    ]


def _last_date(text: str, year: int) -> date | None:
    """Pick the latest DD/MM in the SIGAA date text (the actual due date)."""
    import re

    days = re.findall(r"(\d{1,2})/(\d{1,2})", text or "")
    if not days:
        return None
    day, month = days[-1]
    try:
        return date(year, int(month), int(day))
    except ValueError:
        return None


def _parse_time(clock: str) -> time:
    hour, minute = clock.split(":")
    return time(int(hour), int(minute))


def _add_minutes(t: time, minutes: int) -> time:
    base = datetime.combine(date.today(), t) + timedelta(minutes=minutes)
    return base.time()


def _next_weekday(start: date, weekday: int) -> date:
    delta = (weekday - start.weekday()) % 7
    return start + timedelta(days=delta)


def _dt(d: date, t: time) -> str:
    return f"{d:%Y%m%d}T{t:%H%M%S}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")
