"""High-level SIGAA client: ties the session to parsers, returns domain models."""

from __future__ import annotations

import re

from . import config
from .http import Session, extract_viewstate
from .models import (
    Attendance,
    CoursePlan,
    Deadline,
    Grade,
    Material,
    NewsItem,
    Student,
    Turma,
    TurmaGrade,
)
from .parsers import attendance as attendance_parser
from .parsers import grades as grades_parser
from .parsers import plano as plano_parser
from .parsers import materials as materials_parser
from .parsers import news as news_parser
from .parsers import portal as portal_parser
from .parsers import tarefa as tarefa_parser


class SigaaClient:
    def __init__(self, username: str, password: str):
        self._session = Session(username, password)
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

    def get_integralizacao(self) -> dict:
        """Curriculum progress (integralização) as raw JSON data."""
        import json

        # The dados endpoint 302s to an HTML shell unless the integralização
        # page was opened first in this session (server-side JSF context).
        self._session.get(config.INTEGRALIZACAO_URL)
        text = self._session.get_json_latin1(
            config.INTEGRALIZACAO_DADOS_URL, referer=config.INTEGRALIZACAO_URL
        )
        return json.loads(text)

    def list_curriculum_components(self):
        """Curriculum components with completion and prerequisite status."""
        from .parsers import curriculo as curriculo_parser

        return curriculo_parser.parse_components(self.get_integralizacao())

    def get_historico_pdf(self) -> bytes:
        """Download the full academic transcript (Histórico) as a PDF."""
        portal = self._portal()
        field = portal_parser.find_menu_field(portal, "Histórico acadêmico")
        if field is None:
            raise ValueError("Histórico menu item not found")
        form_id = portal_parser.portal_form_id(portal)
        fields = {form_id: form_id, field: field, "javax.faces.ViewState": extract_viewstate(portal)}
        return self._session.post_bytes(config.PORTAL_ACTION_URL, fields)

    def _portal_menu_post(self, link_text: str) -> str:
        """Click a portal sidebar menu item by its visible text via JSF postback."""
        portal = self._portal()
        field = portal_parser.find_menu_field(portal, link_text)
        if field is None:
            raise ValueError(f"portal menu item not found: {link_text!r}")
        form_id = portal_parser.portal_form_id(portal)
        fields = {
            form_id: form_id,
            field: field,
            "javax.faces.ViewState": extract_viewstate(portal),
        }
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
