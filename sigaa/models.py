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
class Material:
    """A course material on the Turma Virtual Principal page (Tópicos de Aula).

    ``kind == "file"`` is a teacher upload downloadable via formAva postback;
    ``id`` is SIGAA's stable material id (dedup key). ``kind == "link"`` is an
    external URL (e.g. SharePoint slides); ``id`` is that URL and ``url`` holds it.
    """

    id: str
    id_turma: str
    topic: str  # the Tópico de Aula heading + date range
    title: str
    kind: str  # file / link
    url: str | None = None  # set for external links


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
class TurmaGrade:
    """The student's own grade row from a turma's Ver Notas report.

    Per-class and linked to ``id_turma`` (unlike the all-semester Relatório,
    which is keyed by discipline code). Columns mirror the report: Unid. 1..N,
    Exame Final, Resultado, Faltas, Situação.
    """

    id_turma: str
    units: list[str] = field(default_factory=list)
    exam: str | None = None
    result: str | None = None
    absences: str | None = None
    status: str | None = None


@dataclass
class AttendanceRecord:
    """One row of a turma's Mapa de Frequências."""

    date: str  # DD/MM/YYYY
    status: str  # e.g. "2 Falta(s)" or "Presente"
    justified: bool = False


@dataclass
class Attendance:
    """The student's attendance map for one turma (Frequência page)."""

    id_turma: str
    records: list[AttendanceRecord] = field(default_factory=list)
    total_absences: int | None = None
    justified_absences: int | None = None
    max_absences: int | None = None


@dataclass
class PlanEntry:
    """One Cronograma de Aulas row from a turma's Plano de Curso."""

    start: str  # DD/MM/YYYY
    end: str
    description: str


@dataclass
class PlanEvaluation:
    """One Avaliações row (exam date) from a turma's Plano de Curso."""

    date: str  # DD/MM/YYYY
    description: str


@dataclass
class CoursePlan:
    """A turma's Plano de Curso: class schedule and scheduled evaluations."""

    id_turma: str
    schedule: list[PlanEntry] = field(default_factory=list)
    evaluations: list[PlanEvaluation] = field(default_factory=list)


@dataclass
class Deadline:
    """An upcoming assessment/task surfaced on the portal turma cards."""

    id: str  # SIGAA's stable event id (dedup key)
    id_turma: str
    kind: str  # avaliacao / tarefa / atividade / ...
    title: str
    date: str  # raw SIGAA date text, e.g. "Ter, 16/06" or "19/05 à 02/06"
    detail: str | None = None  # e.g. "em 10 dias"
    # JSON of the scraped event detail rows (Descrição, Período, ...), cached on demand.
    body: str | None = None


@dataclass
class CurriculumComponent:
    """A curriculum component from the integralização report."""

    code: str
    name: str
    kind: str  # OB / CO / CF / OP / EC
    period: int
    hours: int
    mandatory: bool
    completed: bool
    prerequisite: str | None = None
    prerequisite_met: bool = True
