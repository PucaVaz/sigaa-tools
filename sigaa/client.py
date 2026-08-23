"""High-level SIGAA client: ties the session to parsers, returns domain models."""

from __future__ import annotations

import re
from dataclasses import replace
from decimal import Decimal

import httpx

from . import config
from .documents import (
    ATESTADO_MATRICULA,
    DECLARACAO_VINCULO,
    HISTORICO,
    AcademicDocument,
    AcademicDocumentError,
    document_spec,
    validate_academic_document,
)
from .http import AuthError, Session, extract_viewstate
from .models import (
    Attendance,
    CoursePlan,
    CurriculumStatus,
    Deadline,
    Grade,
    Material,
    NewsItem,
    Student,
    Turma,
    TurmaGrade,
)
from .parsers import attendance as attendance_parser
from .parsers import curriculum as curriculum_parser
from .parsers import grades as grades_parser
from .parsers import plano as plano_parser
from .parsers import materials as materials_parser
from .parsers import news as news_parser
from .parsers import portal as portal_parser
from .parsers import tarefa as tarefa_parser
from .parsers import transcript as transcript_parser


class SigaaClient:
    def __init__(
        self,
        username: str,
        password: str,
        *,
        timeout: float | httpx.Timeout = 30.0,
    ):
        self._session = Session(username, password, timeout=timeout)
        self._portal_html: str | None = None

    def _portal(self) -> str:
        if self._portal_html is None:
            self._portal_html = self._session.login()
        return self._portal_html

    def get_student(self) -> Student:
        return portal_parser.parse_student(self._portal())

    def list_turmas(self) -> list[Turma]:
        return portal_parser.parse_turmas(self._portal())

    def list_deadlines(self) -> list[Deadline]:
        """Assessment/task deadlines (already present in the portal HTML)."""
        return portal_parser.parse_deadlines(self._portal())

    def get_grades(self) -> list[Grade]:
        html = self._portal_menu_post("Minhas Notas")
        return grades_parser.parse_grades(html)

    def get_cra(self) -> Decimal:
        """Return the official CRA recorded in the academic transcript."""
        return transcript_parser.parse_cra_pdf(self.get_historico_pdf())

    def get_curriculum_status(
        self,
        *,
        include_cra: bool = True,
    ) -> CurriculumStatus:
        """Return live curriculum progress and, by default, the official CRA.

        SIGAA renders a curriculum shell and then fetches its JSON payload. A
        fresh login changes the active student context, so an invalid/auth
        response retries the complete two-request flow once.
        """
        status: CurriculumStatus | None = None
        for attempt in range(2):
            try:
                self._session.get(config.CURRICULUM_ENTRY_URL)
                payload = self._session.get(config.CURRICULUM_DATA_URL)
                status = curriculum_parser.parse_curriculum(payload)
                break
            except (AuthError, curriculum_parser.CurriculumDataError):
                if attempt == 1:
                    raise
                self._portal_html = self._session.login()

        if status is None:  # pragma: no cover - loop either succeeds or raises
            raise curriculum_parser.CurriculumDataError(
                "Invalid curriculum response"
            )
        if not include_cra:
            return replace(status, cra_source="not_requested")

        try:
            cra = self.get_cra()
        except transcript_parser.CraUnavailableError:
            return status
        return replace(
            status,
            cra=cra,
            cra_source="academic_transcript",
        )

    def get_historico_pdf(self) -> bytes:
        """Download the full academic transcript (Histórico) as a PDF."""
        return self.download_academic_document(HISTORICO).content

    def get_declaracao_vinculo_pdf(self) -> bytes:
        """Download the current enrollment declaration as a PDF."""
        return self.download_academic_document(DECLARACAO_VINCULO).content

    def get_atestado_matricula_html(self) -> bytes:
        """Download the enrollment certificate as printable HTML."""
        return self.download_academic_document(ATESTADO_MATRICULA).content

    def download_academic_document(self, kind: str) -> AcademicDocument:
        """Download and validate one document exposed on the student portal.

        A session refresh changes the JSF component ids and ViewState.  If the
        first response is an auth bounce or an unexpected page, log in once more
        and rebuild the payload from the newly rendered portal before retrying.
        """
        spec = document_spec(kind)
        for attempt in range(2):
            portal = self._portal()
            fields = portal_parser.build_menu_postback(portal, spec.menu_label)
            if fields is None:
                raise ValueError(f"portal document menu item not found: {spec.menu_label!r}")
            try:
                content, content_type, _ = self._session.post_download(
                    config.PORTAL_ACTION_URL,
                    fields,
                    retry_on_auth=False,
                )
                return validate_academic_document(kind, content, content_type)
            except (AuthError, AcademicDocumentError):
                if attempt == 1:
                    raise
                self._portal_html = self._session.login()

    def _portal_menu_post(self, link_text: str) -> str:
        """Click a portal sidebar menu item by its visible text via JSF postback."""
        portal = self._portal()
        fields = portal_parser.build_menu_postback(portal, link_text)
        if fields is None:
            raise ValueError(f"portal menu item not found: {link_text!r}")
        return self._session.post(config.PORTAL_ACTION_URL, fields)

    def enter_turma(self, turma: Turma) -> str:
        """Navigate into a Turma Virtual and return its Principal page HTML."""
        fields = {
            turma.form_id: turma.form_id,
            turma.field: turma.field,
            "idTurma": turma.id_turma,
            "javax.faces.ViewState": extract_viewstate(self._portal()),
        }
        return self._session.post(config.PORTAL_ACTION_URL, fields)

    def _turma_menu_post(self, turma: Turma, link_text: str, turma_html: str | None = None) -> str:
        """Click a Turma Virtual (formMenu) menu item by its visible text.

        Pass ``turma_html`` (an already-fetched Principal page) to skip a redundant
        ``enter_turma`` round-trip.
        """
        principal = turma_html or self.enter_turma(turma)
        field = portal_parser.find_menu_field(principal, link_text)
        if field is None:
            raise ValueError(f"turma menu item not found: {link_text!r}")
        fields = {
            "formMenu": "formMenu",
            field: field,
            "javax.faces.ViewState": extract_viewstate(principal, default="j_id2"),
        }
        return self._session.post(config.AVA_URL, fields)

    def get_turma_grades(self, turma: Turma, turma_html: str | None = None) -> TurmaGrade | None:
        """Per-turma grade report (Ver Notas), linked to the turma."""
        html = self._turma_menu_post(turma, "Ver Notas", turma_html)
        return grades_parser.parse_turma_grades(html, turma.id_turma)

    def get_attendance(self, turma: Turma, turma_html: str | None = None) -> Attendance | None:
        """Per-date attendance map (Frequência)."""
        html = self._turma_menu_post(turma, "Frequência", turma_html)
        return attendance_parser.parse_attendance(html, turma.id_turma)

    def get_course_plan(self, turma: Turma, turma_html: str | None = None) -> CoursePlan | None:
        """Plano de Curso: class schedule (cronograma) and evaluation dates."""
        html = self._turma_menu_post(turma, "Plano de Curso", turma_html)
        return plano_parser.parse_course_plan(html, turma.id_turma)

    def list_news(self, turma: Turma, turma_html: str | None = None) -> list[NewsItem]:
        html = turma_html or self.enter_turma(turma)
        return news_parser.parse_news_list(html, turma.id_turma)

    def get_news_body(self, turma: Turma, news_id: str, turma_html: str | None = None) -> str | None:
        html = turma_html or self.enter_turma(turma)
        fields = news_parser.build_body_postback(
            html, news_id, extract_viewstate(html, default="j_id2")
        )
        if fields is None:
            return None
        body_html = self._session.post(config.AVA_URL, fields)
        return news_parser.parse_news_body(body_html)

    def _open_event(self, event_id: str) -> str | None:
        """Replay the portal deadline anchor's postback to render the event page."""
        portal = self._portal()
        fields = tarefa_parser.build_event_postback(
            portal, event_id, extract_viewstate(portal)
        )
        if fields is None:
            return None
        return self._session.post(config.PORTAL_ACTION_URL, fields)

    def get_tarefa_body(self, event_id: str) -> dict | None:
        """Open a portal deadline event (tarefa/atividade) and scrape its details.

        The deadline's portal anchor carries the idTurma, so only the event id is
        needed. Returns the detail rows as a dict, or None if the event has no
        scrapeable form (e.g. it is not a tarefa).
        """
        html = self._open_event(event_id)
        if html is None:
            return None
        return tarefa_parser.parse_tarefa_body(html)

    def download_tarefa_attachment(self, event_id: str) -> tuple[bytes, str] | None:
        """Download a tarefa's teacher attachment (Arquivo do Professor).

        Returns (bytes, suggested filename), or None if the event has no
        attachment. The filename falls back to the task's own name + extension.
        """
        html = self._open_event(event_id)
        if html is None:
            return None
        href = tarefa_parser.find_professor_attachment(html)
        if href is None:
            return None
        url = href if href.startswith("http") else config.HOST + href
        content, content_type, disposition = self._session.get_download(url)
        fields = tarefa_parser.parse_tarefa_body(html) or {}
        title = fields.get("Nome da Tarefa") or f"tarefa-{event_id}"
        filename = materials_parser.filename_for(title, content_type, disposition)
        return content, filename

    def list_materials(self, turma: Turma, turma_html: str | None = None) -> list[Material]:
        html = turma_html or self.enter_turma(turma)
        return materials_parser.parse_materials(html, turma.id_turma)

    def download_material(self, turma: Turma, material_id: str) -> tuple[bytes, str]:
        """Download one uploaded material. Returns (bytes, suggested filename)."""
        turma_html = self.enter_turma(turma)
        material = next(
            (m for m in materials_parser.parse_materials(turma_html, turma.id_turma)
             if m.id == material_id),
            None,
        )
        if material is None or material.kind != "file":
            raise ValueError(f"downloadable material {material_id!r} not found in {turma.code}")
        fields = materials_parser.build_download_postback(
            turma_html, material_id, extract_viewstate(turma_html, default="j_id2")
        )
        if fields is None:
            raise ValueError(f"could not build download request for material {material_id!r}")
        content, content_type, disposition = self._session.post_download(config.AVA_URL, fields)
        filename = materials_parser.filename_for(material.title, content_type, disposition)
        return content, filename

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "SigaaClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
