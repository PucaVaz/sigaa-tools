"""High-level SIGAA client: ties the session to parsers, returns domain models."""

from __future__ import annotations

from . import config
from .http import Session, extract_viewstate
from .models import NewsItem, Student, Turma
from .parsers import news as news_parser
from .parsers import portal as portal_parser


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

    def enter_turma(self, turma: Turma) -> str:
        """Navigate into a Turma Virtual and return its Principal page HTML."""
        fields = {
            turma.form_id: turma.form_id,
            turma.field: turma.field,
            "idTurma": turma.id_turma,
            "javax.faces.ViewState": extract_viewstate(self._portal()),
        }
        return self._session.post(config.PORTAL_ACTION_URL, fields)

    def list_news(self, turma: Turma) -> list[NewsItem]:
        turma_html = self.enter_turma(turma)
        return news_parser.parse_news_list(turma_html, turma.id_turma)

    def get_news_body(self, turma: Turma, news_id: str) -> str | None:
        turma_html = self.enter_turma(turma)
        fields = news_parser.build_body_postback(
            turma_html, news_id, extract_viewstate(turma_html, default="j_id2")
        )
        if fields is None:
            return None
        body_html = self._session.post(config.AVA_URL, fields)
        return news_parser.parse_news_body(body_html)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "SigaaClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
