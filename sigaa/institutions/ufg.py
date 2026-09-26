"""Provisional UFG profile: CAS single sign-on with reCAPTCHA, pending live onboarding.

UFG's SIGAA sends every login to CAS at sso.ufg.br, which enforces reCAPTCHA, so
the password form can never be submitted unattended. The student logs in with a
browser and stores the SIGAA session's Cookie header with
``sigaa login --institution ufg``; see docs/institutions/ufg.md.
"""
from urllib.parse import urlsplit

from ..errors import NavigationError
from ..parsers.authentication import has_login_form
from . import auth_session
from .base import Capability, InstitutionProfile

HOST = "https://sigaa.sistemas.ufg.br"
BASE = HOST + "/sigaa"
SSO_HOST = "sso.ufg.br"
# Slot identifiers only. Clock times await live confirmation; no guessed clock
# values are exported as calendar events.
SLOT_GRID = {"M": range(1, 7), "T": range(1, 7), "N": range(1, 6)}
PROFILE = InstitutionProfile(
    key="ufg",
    label="UFG (provisional)",
    host=HOST,
    # 302s to CAS; kept for `sigaa onboard login-probe` and the bounce check.
    logon_url=BASE + "/verTelaLogin.do",
    # Classic discente portal; a direct GET with a live session lands here with
    # no vínculo picker (live check 2026-09-25, docs/institutions/ufg.md).
    portal_entry_url=BASE + "/portais/discente/discente.jsf",
    portal_action_url=BASE + "/portais/discente/discente.jsf",
    ava_url=BASE + "/ava/index.jsf",
    curriculum_entry_url="",
    curriculum_data_url="",
    matricula_instrucoes_url="",
    matricula_turmas_curriculo_url="",
    auth_marker="dispatch=logOff",
    login_redirect_marker="verTelaLogin.do",
    keyring_service="sigaa-ufg",
    slot_times={shift: {slot: "" for slot in slots} for shift, slots in SLOT_GRID.items()},
    slot_minutes=50,
    menu_labels={},
    # Only what passed `sigaa onboard probe` on live UFG captures (2026-09-26).
    capabilities=frozenset({Capability.PORTAL, Capability.NEWS, Capability.MATERIALS}),
    provisional=True,
    auth_mode="session",
    sso_hosts=frozenset({SSO_HOST}),
)


class UfgNavigator:
    def login(self, session):
        return auth_session.perform_login(session, PROFILE)

    def looks_logged_out(self, text, url=""):
        # A bounce to sso.ufg.br never gets here: the request guard raises
        # SsoRedirectError first. A dead session on a portal page 302s to an
        # empty expirada.jsp (observed live 2026-09-25), which has no form.
        if urlsplit(url).path.endswith(("verTelaLogin.do", "logar.do", "expirada.jsp")):
            return True
        return has_login_form(text)

    def portal_menu_post(self, session, portal, label):
        raise NavigationError("UFG portal navigation requires live onboarding captures")

    def enter_turma(self, session, portal, turma):
        # Replays the class row's own form_acessarTurmaVirtual* postback: the form
        # marker, the link's field, the hidden idTurma and the portal ViewState.
        if not (turma.form_id and turma.field):
            raise NavigationError(f"class {turma.id_turma!r} has no portal form to replay")
        from ..http import extract_viewstate

        fields = {
            turma.form_id: turma.form_id,
            turma.field: turma.field,
            "idTurma": turma.id_turma,
            "javax.faces.ViewState": extract_viewstate(portal),
        }
        return session.post(PROFILE.portal_action_url, fields)

    def turma_menu_post(self, session, principal, label):
        raise NavigationError("UFG class menu requires live onboarding captures")

    def open_event(self, session, portal, event_id):
        raise NavigationError("UFG event navigation requires live onboarding captures")


NAVIGATOR = UfgNavigator()
