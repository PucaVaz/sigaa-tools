"""Domain models. Plain dataclasses, no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Student:
    matricula: str
    name: str
    course: str | None = None
    email: str | None = None
    semester: str | None = None


@dataclass
class Schedule:
    """Decoded SIGAA schedule code, e.g. ``6M2345`` -> Fri morning slots 2-5."""

    raw: str
    days: list[int] = field(default_factory=list)  # 2=Mon .. 7=Sat
    shift: str = ""  # M / T / N
    slots: list[int] = field(default_factory=list)


@dataclass
class Turma:
    """An enrolled class. ``id_turma`` is SIGAA's internal navigation id."""

    id_turma: str
    name: str
    code: str | None = None
    room: str | None = None
    schedule_raw: str | None = None
    semester: str | None = None
    # JSF postback hooks captured from the portal card, needed to enter the turma.
    field: str | None = None
    form_id: str | None = None


@dataclass
class NewsItem:
    """A class announcement. ``id`` is SIGAA's stable news id (dedup key)."""

    id: str
    id_turma: str
    date: str
    title: str
    body: str | None = None
    # JSF form id for the per-row "Visualizar" body postback.
    form_id: str | None = None
