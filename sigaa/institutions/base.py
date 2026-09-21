"""Institution data and the navigation boundary shared by all SIGAA forks."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from ..http import Session
    from ..models import Turma


class MenuLabel(StrEnum):
    GRADES = "grades"
    ENROLL = "enroll"
    TURMA_GRADES = "turma_grades"
    ATTENDANCE = "attendance"
    PLAN = "plan"
    PARTICIPANTS = "participants"
    HISTORICO = "historico"
    DECLARACAO_VINCULO = "declaracao_vinculo"
    ATESTADO = "atestado"
    EXTENSION_DOCS = "extension_docs"


class Capability(StrEnum):
    CALENDAR = "calendar"
    PORTAL = "portal"
    NEWS = "news"
    MATERIALS = "materials"
    GRADES = "grades"
    ATTENDANCE = "attendance"
    PLAN = "plan"
    PARTICIPANTS = "participants"
    TASKS = "tasks"
    CURRICULUM_JSON = "curriculum_json"
    MATRICULA = "matricula"
    EXTENSAO = "extensao"
    DOCUMENTS = "documents"
    SIPAC = "sipac"


@dataclass(frozen=True)
class InstitutionProfile:
    key: str
    label: str
    host: str
    logon_url: str
    portal_entry_url: str
    portal_action_url: str
    ava_url: str
    curriculum_entry_url: str
    curriculum_data_url: str
    matricula_instrucoes_url: str
    matricula_turmas_curriculo_url: str
    auth_marker: str
    login_redirect_marker: str
    keyring_service: str
    slot_times: dict[str, dict[int, str]]
    slot_minutes: int
    menu_labels: dict[MenuLabel, str]
    capabilities: frozenset[Capability]

    def require(self, capability: Capability) -> None:
        from ..errors import UnsupportedFeatureError
        if capability not in self.capabilities:
            raise UnsupportedFeatureError(f"{self.key}: unsupported feature {capability.value}")

    def validate_url(self, url: str) -> None:
        from ..errors import UnsafeUrlError
        target, origin = urlsplit(str(url)), urlsplit(self.host)
        if (target.scheme != "https" or target.hostname != origin.hostname
                or target.port not in (None, 443) or target.username or target.password):
            raise UnsafeUrlError("request blocked: URL is outside the institution HTTPS host")


class Navigator(Protocol):
    def login(self, session: Session) -> str: ...
    def looks_logged_out(self, text: str, url: str = "") -> bool: ...
    def portal_menu_post(self, session: Session, portal: str, label: str) -> str: ...
    def enter_turma(self, session: Session, portal: str, turma: Turma) -> str: ...
    def turma_menu_post(self, session: Session, principal: str, label: str) -> str: ...
    def open_event(self, session: Session, portal: str, event_id: str) -> str | None: ...


@dataclass(frozen=True)
class Institution:
    profile: InstitutionProfile
    navigator: Navigator
