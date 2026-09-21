"""High-level SIGAA client: ties the session to parsers, returns domain models."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from decimal import Decimal

import httpx

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
from .institutions import Capability, MenuLabel, get
from .models import (
    Attendance,
    CoursePlan,
    CurriculumStatus,
    Deadline,
    ExtensionParticipation,
    Grade,
    Material,
    NewsItem,
    Professor,
    Student,
    Turma,
    TurmaGrade,
)
from .parsers import attendance as attendance_parser
from .parsers import curriculum as curriculum_parser
from .parsers import extensao as extensao_parser
from .parsers import grades as grades_parser
from .parsers import plano as plano_parser
from .parsers import materials as materials_parser
from .parsers import news as news_parser
from .parsers import participantes as participantes_parser
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
        institution: str | None = None,
    ):
        provider = get(institution)
        self.profile = provider.profile
        self.navigator = provider.navigator
        self._session = Session(
            username,
            password,
            timeout=timeout,
            profile=self.profile,
            navigator=self.navigator,
        )
        self._portal_html: str | None = None
        self._spent_principals: set[str] = set()

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
        self.profile.require(Capability.GRADES)
        html = self._portal_menu_post(self.profile.menu_labels[MenuLabel.GRADES])
        return grades_parser.parse_grades(html)

    def list_extension_participations(self) -> list[ExtensionParticipation]:
        """Extension participations and which of their documents can be issued now.

        Read-only: opens the 'Certificados e Declarações' page and never
        triggers a declaration or certificate emission.
        """
        self.profile.require(Capability.EXTENSAO)
        html = self._portal_menu_post(self.profile.menu_labels[MenuLabel.EXTENSION_DOCS])
        return extensao_parser.parse_extension_participations(html)

    def open_matricula_curriculo(self) -> str:
        """Navigate Portal -> Realizar Matrícula -> Iniciar Seleção; return the
        'Turmas Abertas do Currículo' page HTML."""
        self.profile.require(Capability.MATRICULA)
        intro = self._portal_menu_post(self.profile.menu_labels[MenuLabel.ENROLL])
        return self._session.post(
            self.profile.matricula_instrucoes_url,
            {
                "form": "form",
                "form:btnIniciarSolicit": "x",
                "javax.faces.ViewState": extract_viewstate(intro),
            },
        )

    def list_open_turmas(self, curriculo_html: str | None = None):
        """Open sections offered for the student's curriculum."""
        from .parsers import matricula as matricula_parser

        html = curriculo_html or self.open_matricula_curriculo()
        return matricula_parser.parse_open_turmas(html)

    def select_matricula_turmas(self, turma_ids: list[str], curriculo_html: str | None = None) -> str:
        """Add sections to the enrollment request (not yet confirmed).

        Returns the 'Turmas Selecionadas' page HTML; feedback messages on it
        report which sections were accepted or rejected.
        """
        self.profile.require(Capability.MATRICULA)
        html = curriculo_html or self.open_matricula_curriculo()
        form_match = re.search(
            r'<form id="([^"]+)"[^>]*>(?:(?!</form>).)*?name="selecaoTurmas"', html, re.S
        )
        if not form_match:
            raise ValueError("selection form not found on the matrícula page")
        form = form_match.group(1)
        return self._session.post(
            self.profile.matricula_turmas_curriculo_url,
            {
                form: form,
                f"{form}:btaoSelecionarTurmas": f"{form}:btaoSelecionarTurmas",
                "javax.faces.ViewState": extract_viewstate(html),
                "selecaoTurmas": turma_ids,
            },
        )

    def confirm_matricula(self, selecionadas_html: str) -> str:
        """Press CONFIRMAR MATRÍCULAS on the 'Turmas Selecionadas' page.

        Submits the enrollment request for processing. Returns the receipt
        page HTML (contains the Solicitação de Matrícula number).
        """
        self.profile.require(Capability.MATRICULA)
        form = "formBotoesSuperiores"
        return self._session.post(
            self.profile.matricula_turmas_curriculo_url.replace(
                "turmas_curriculo.jsf", "turmas_selecionadas.jsf"
            ),
            {
                form: form,
                f"{form}:botaoSubmissao": f"{form}:botaoSubmissao",
                "javax.faces.ViewState": extract_viewstate(selecionadas_html),
            },
        )

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
        self.profile.require(Capability.CURRICULUM_JSON)
        status: CurriculumStatus | None = None
        for attempt in range(2):
            try:
                self._session.get(self.profile.curriculum_entry_url)
                payload = self._session.get(self.profile.curriculum_data_url)
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
        self.profile.require(Capability.DOCUMENTS)
        spec = document_spec(kind)
        menu_label = self.profile.menu_labels[spec.menu_label]
        for attempt in range(2):
            portal = self._portal()
            fields = portal_parser.build_menu_postback(portal, menu_label)
            if fields is None:
                raise ValueError(f"portal document menu item not found: {menu_label!r}")
            try:
                content, content_type, _ = self._session.post_download(
                    self.profile.portal_action_url,
                    fields,
                    retry_on_auth=False,
                )
                return validate_academic_document(kind, content, content_type, profile=self.profile)
            except (AuthError, AcademicDocumentError):
                if attempt == 1:
                    raise
                self._portal_html = self._session.login()

    def _portal_menu_post(self, link_text: str) -> str:
        """Click a portal sidebar menu item by its visible text via JSF postback."""
        return self.navigator.portal_menu_post(self._session, self._portal(), link_text)

    def enter_turma(self, turma: Turma) -> str:
        return self.navigator.enter_turma(self._session, self._portal(), turma)

    def _principal_for_postback(self, turma: Turma, turma_html: str | None) -> str:
        """Return a Principal page that is safe to build one postback from.

        A Turma Virtual postback consumes the server-side navigation state: the
        session moves to the page that was opened, so a second postback built
        from the same cached Principal page is answered with whatever turma the
        session currently sits on -- silently returning another turma's content.
        A cached page may therefore be used exactly once; every later postback
        re-enters the turma first.
        """
        if turma_html:
            digest = hashlib.sha256(turma_html.encode("utf-8", "replace")).hexdigest()
            if digest not in self._spent_principals:
                self._spent_principals.add(digest)
                return turma_html
        return self.enter_turma(turma)

    def _turma_menu_post(self, turma: Turma, link_text: str, turma_html: str | None = None) -> str:
        """Click a Turma Virtual (formMenu) menu item by its visible text.

        Pass ``turma_html`` (an already-fetched Principal page) to skip a redundant
        ``enter_turma`` round-trip -- honoured only for the first postback built
        from that page, see :meth:`_principal_for_postback`.
        """
        principal = self._principal_for_postback(turma, turma_html)
        return self.navigator.turma_menu_post(self._session, principal, link_text)

    def get_turma_grades(self, turma: Turma, turma_html: str | None = None) -> TurmaGrade | None:
        """Per-turma grade report (Ver Notas), linked to the turma."""
        self.profile.require(Capability.GRADES)
        label = self.profile.menu_labels[MenuLabel.TURMA_GRADES]
        html = self._turma_menu_post(turma, label, turma_html)
        return grades_parser.parse_turma_grades(html, turma.id_turma)

    def get_attendance(self, turma: Turma, turma_html: str | None = None) -> Attendance | None:
        """Per-date attendance map (Frequência)."""
        self.profile.require(Capability.ATTENDANCE)
        label = self.profile.menu_labels[MenuLabel.ATTENDANCE]
        html = self._turma_menu_post(turma, label, turma_html)
        return attendance_parser.parse_attendance(html, turma.id_turma)

    def get_course_plan(self, turma: Turma, turma_html: str | None = None) -> CoursePlan | None:
        """Plano de Curso: class schedule (cronograma) and evaluation dates."""
        self.profile.require(Capability.PLAN)
        label = self.profile.menu_labels[MenuLabel.PLAN]
        html = self._turma_menu_post(turma, label, turma_html)
        return plano_parser.parse_course_plan(html, turma.id_turma)

    def list_professors(self, turma: Turma, turma_html: str | None = None) -> list[Professor]:
        """Teaching staff of a turma (Participantes)."""
        self.profile.require(Capability.PARTICIPANTS)
        label = self.profile.menu_labels[MenuLabel.PARTICIPANTS]
        html = self._turma_menu_post(turma, label, turma_html)
        return participantes_parser.parse_professors(html, turma.id_turma)

    def list_news(self, turma: Turma, turma_html: str | None = None) -> list[NewsItem]:
        self.profile.require(Capability.NEWS)
        html = turma_html or self.enter_turma(turma)
        return news_parser.parse_news_list(html, turma.id_turma)

    def get_news_body(self, turma: Turma, news_id: str, turma_html: str | None = None) -> str | None:
        html = self._principal_for_postback(turma, turma_html)
        fields = news_parser.build_body_postback(
            html, news_id, extract_viewstate(html, default="j_id2")
        )
        if fields is None:
            return None
        body_html = self._session.post(self.profile.ava_url, fields)
        return news_parser.parse_news_body(body_html)

    def _open_event(self, event_id: str) -> str | None:
        """Replay the portal deadline anchor's postback to render the event page."""
        return self.navigator.open_event(self._session, self._portal(), event_id)

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
        url = href if href.startswith("http") else self.profile.host + href
        content, content_type, disposition = self._session.get_download(url)
        fields = tarefa_parser.parse_tarefa_body(html) or {}
        title = fields.get("Nome da Tarefa") or f"tarefa-{event_id}"
        filename = materials_parser.filename_for(title, content_type, disposition)
        return content, filename

    def list_materials(self, turma: Turma, turma_html: str | None = None) -> list[Material]:
        self.profile.require(Capability.MATERIALS)
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
        content, content_type, disposition = self._session.post_download(
            self.profile.ava_url, fields
        )
        filename = materials_parser.filename_for(material.title, content_type, disposition)
        return content, filename

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "SigaaClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
