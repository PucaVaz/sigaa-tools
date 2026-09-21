"""Provisional UFCG profile: classic authentication, pending live onboarding."""
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from ..errors import NavigationError
from . import auth_classic
from .base import Capability, InstitutionProfile

HOST = "https://sigaa.ufcg.edu.br"
BASE = HOST + "/sigaa"
# Slot identifiers from the onboarding plan. Clock times await live confirmation;
# no guessed clock values are exported as calendar events.
SLOT_GRID = {"M": range(1, 6), "T": range(1, 6), "N": range(1, 5)}
PROFILE = InstitutionProfile(
    key="ufcg",
    label="UFCG (provisional)",
    host=HOST,
    logon_url=BASE + "/verTelaLogin.do",
    portal_entry_url=BASE + "/portais/discente/discente.jsf",
    portal_action_url=BASE + "/portais/discente/discente.jsf",
    ava_url=BASE + "/ava/index.jsf",
    curriculum_entry_url="",
    curriculum_data_url="",
    matricula_instrucoes_url="",
    matricula_turmas_curriculo_url="",
    auth_marker="dispatch=logOff",
    login_redirect_marker="verTelaLogin.do",
    keyring_service="sigaa-ufcg",
    slot_times={shift: {slot: "" for slot in slots} for shift, slots in SLOT_GRID.items()},
    slot_minutes=50,
    menu_labels={},
    capabilities=frozenset({Capability.PORTAL}),
    provisional=True,
)
_LOGIN_FORM = 'input[type="password"], form[name="loginForm"]'


class UfcgNavigator:
    def login(self, session):
        return auth_classic.perform_login(session, PROFILE)

    def looks_logged_out(self, text, url=""):
        if urlsplit(url).path.endswith(("verTelaLogin.do", "logar.do")):
            return True
        return BeautifulSoup(text, "lxml").select_one(_LOGIN_FORM) is not None

    def portal_menu_post(self, session, portal, label):
        raise NavigationError("UFCG portal navigation requires live onboarding captures")

    def enter_turma(self, session, portal, turma):
        raise NavigationError("UFCG class navigation requires live onboarding captures")

    def turma_menu_post(self, session, principal, label):
        raise NavigationError("UFCG class menu requires live onboarding captures")

    def open_event(self, session, portal, event_id):
        raise NavigationError("UFCG event navigation requires live onboarding captures")


NAVIGATOR = UfcgNavigator()
