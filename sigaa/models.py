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


@dataclass
class Grade:
    """A discipline's grades for one semester from the Relatório de Notas."""

    semester: str
    code: str
    discipline: str
    units: list[str] = field(default_factory=list)  # Unidade 1..N (blank = "")
    exam: str | None = None  # Exame Final
    result: str | None = None  # Resultado (média)
    absences: str | None = None  # Faltas
    status: str | None = None  # Situação


@dataclass
class Deadline:
    """An upcoming assessment/task surfaced on the portal turma cards."""

    id: str  # SIGAA's stable event id (dedup key)
    id_turma: str
    kind: str  # avaliacao / tarefa / atividade / ...
    title: str
    date: str  # raw SIGAA date text, e.g. "Ter, 16/06" or "19/05 à 02/06"
    detail: str | None = None  # e.g. "em 10 dias"
