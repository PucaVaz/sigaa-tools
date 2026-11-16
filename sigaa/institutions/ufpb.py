"""UFPB endpoints and JSF beta-portal navigation."""
from urllib.parse import urljoin, urlsplit

import httpx

from ..altcha import form_field_value, parse_challenge, solve
from ..errors import (
    LoginRejectedError,
    MissingCredentialsError,
    NavigationError,
    UnrecognizedPageError,
)
from ..parsers._common import page_fingerprint
from ..parsers.authentication import altcha_widget
from . import auth_session
from .base import Capability, InstitutionProfile, MenuLabel

HOST = "https://sigaa.ufpb.br"
BASE = f"{HOST}/sigaa"
LOGON_URL = f"{BASE}/logon.jsf"
# Entry point that 302-redirects to the fully rendered beta portal. A plain GET
# of the beta URL returns only a loading shell, so this slash-terminated classic
# URL is the reliable way in.
PORTAL_ENTRY_URL = f"{BASE}/portal/discente/"
# Form action used for in-portal JSF postbacks (entering a turma).
PORTAL_ACTION_URL = f"{BASE}/portais/discente/beta/discente.jsf"
# Curriculum-progress shell and the JSON request it issues after rendering.
CURRICULUM_ENTRY_URL = f"{BASE}/portal/discente/integralizacao/"
CURRICULUM_DATA_URL = f"{BASE}/portal/discente/integralizacao/dados/"
# Turma Virtual base; news bodies are fetched here.
AVA_URL = f"{BASE}/ava/index.jsf"

# Marker proving an authenticated page; absence means the session is dead.
AUTH_MARKER = "Sair do SIGAA"
# Substring of the URL we get bounced to when a session expires.
LOGIN_REDIRECT_MARKER = "logon.jsf"
# A dead session is redirected here (/sigaa/portal/discente/ -> /sigaa/ ->
# /publico/): a small public page with no login form and no logon.jsf link.
PUBLIC_AREA_PATH = "/publico"

KEYRING_SERVICE = "sigaa-ufpb"
SESSION_COOKIE_NAMES = frozenset({"JSESSIONID"})

# UFPB class-time slots. Day digits: 2=Mon .. 7=Sat. Shift: M/T/N.
# NOTE: clock times below are an UNCONFIRMED default; confirm against a turma's
# "Plano de Curso" before trusting them for calendar/ICS export.
SLOT_TIMES_UNCONFIRMED = {
    "M": {1: "07:00", 2: "07:50", 3: "08:50", 4: "09:40", 5: "10:40", 6: "11:30"},
    "T": {1: "13:00", 2: "13:50", 3: "14:50", 4: "15:40", 5: "16:40", 6: "17:30"},
    "N": {1: "18:30", 2: "19:20", 3: "20:20", 4: "21:10"},
}

# Matrícula on-line (enrollment request) flow.
MATRICULA_INSTRUCOES_URL = f"{BASE}/graduacao/matricula/instrucoes.jsf"
MATRICULA_TURMAS_CURRICULO_URL = f"{BASE}/graduacao/matricula/turmas_curriculo.jsf"

# Pages are served as ISO-8859-1 and form posts are decoded the way browsers
# encode them for that label: Windows-1252 (an en dash arrives as 0x96).
FORM_CHARSET = "cp1252"

PROFILE = InstitutionProfile(
    key="ufpb",
    label="UFPB",
    host=HOST,
    logon_url=LOGON_URL,
    portal_entry_url=PORTAL_ENTRY_URL,
    portal_action_url=PORTAL_ACTION_URL,
    ava_url=AVA_URL,
    curriculum_entry_url=CURRICULUM_ENTRY_URL,
    curriculum_data_url=CURRICULUM_DATA_URL,
    matricula_instrucoes_url=MATRICULA_INSTRUCOES_URL,
    matricula_turmas_curriculo_url=MATRICULA_TURMAS_CURRICULO_URL,
    auth_marker=AUTH_MARKER,
    login_redirect_marker=LOGIN_REDIRECT_MARKER,
    keyring_service=KEYRING_SERVICE,
    slot_times=SLOT_TIMES_UNCONFIRMED,
    slot_minutes=50,
    menu_labels={
        MenuLabel.GRADES: "Minhas Notas",
        MenuLabel.ENROLL: "Realizar Matrícula",
        MenuLabel.TURMA_GRADES: "Ver Notas",
        MenuLabel.ATTENDANCE: "Frequência",
        MenuLabel.PLAN: "Plano de Curso",
        MenuLabel.PARTICIPANTS: "Participantes",
        MenuLabel.HISTORICO: "Histórico acadêmico",
        MenuLabel.DECLARACAO_VINCULO: "Declaração de vínculo",
        MenuLabel.ATESTADO: "Atestado de matrícula",
        MenuLabel.EXTENSION_DOCS: "Certificados e Declarações",
        MenuLabel.TASK_LIST: "Tarefas",
        MenuLabel.OPPORTUNITIES: "Inscrever-se em Seleção de Projeto de Ensino",
    },
    capabilities=frozenset(Capability),
    # The logon form's captcha is ALTCHA proof-of-work, which this tool solves
    # (sigaa.altcha), so the classic password post works unattended again.
    auth_mode="password",
    # Cookies identifying an imported browser session. In password mode a stored
    # secret parsing as a Cookie header with them is refused instead of sent.
    session_cookie_names=SESSION_COOKIE_NAMES,
    form_charset=FORM_CHARSET,
)


class UfpbNavigator:
    def __init__(self, profile=PROFILE):
        self.profile = profile

    def login(self, session):
        return perform_login(
            session._client, session._username, session._password, profile=self.profile
        )

    def looks_logged_out(self, text, url=""):
        if _is_public_area(url):
            return True
        return (
            self.profile.auth_marker not in text
            and self.profile.login_redirect_marker in text
        )

    def portal_reached(self, text, url=""):
        return _portal_reached(text, self.profile)

    def portal_menu_post(self, session, portal, label):
        from ..parsers.portal import build_menu_postback
        fields = build_menu_postback(portal, label)
        if fields is None:
            raise NavigationError(f"portal menu item not found: {label!r}")
        return session.post(self.profile.portal_action_url, fields)

    def enter_turma(self, session, portal, turma):
        from ..http import extract_viewstate

        fields = {
            turma.form_id: turma.form_id,
            turma.field: turma.field,
            "idTurma": turma.id_turma,
            "javax.faces.ViewState": extract_viewstate(portal),
        }
        return session.post(self.profile.portal_action_url, fields)

    def turma_menu_post(self, session, principal, label):
        from ..http import extract_viewstate
        from ..parsers.portal import find_menu_field
        field = find_menu_field(principal, label)
        if field is None:
            raise NavigationError(f"turma menu item not found: {label!r}")
        fields = {
            "formMenu": "formMenu",
            field: field,
            "javax.faces.ViewState": extract_viewstate(principal, default="j_id2"),
        }
        return session.post(self.profile.ava_url, fields)

    def open_event(self, session, portal, event_id):
        from ..http import extract_viewstate
        from ..parsers.tarefa import build_event_postback
        fields = build_event_postback(portal, event_id, extract_viewstate(portal))
        if fields is None:
            raise NavigationError(f"portal event not found: {event_id!r}")
        return session.post(self.profile.portal_action_url, fields)


def _is_public_area(url: str) -> bool:
    path = urlsplit(url).path
    return path == PUBLIC_AREA_PATH or path.startswith(PUBLIC_AREA_PATH + "/")


def _portal_reached(text: str, profile: InstitutionProfile) -> bool:
    # The entry URL 302s to the beta portal, which links sign-out as /sigaa/logoff/
    # with no dispatch=logOff, so the shared authenticated_portal check rejects it.
    return profile.auth_marker in text


def perform_login(client, username: str, password: str, *, profile: InstitutionProfile) -> str:
    """Authenticate and return the rendered portal HTML (with the turma list).

    The logon form carries an ALTCHA captcha: the challenge is fetched from the
    widget's endpoint, solved (proof-of-work) and posted in its hidden field
    alongside the credentials. Raises ``LoginRejectedError`` if the resulting
    portal is not authenticated.
    """
    from ..http import extract_viewstate

    _refuse_browser_session(profile, password)
    login_page = client.get(profile.logon_url)
    login_page.raise_for_status()
    fields = {
        "form": "form",
        "form:width": "1280",
        "form:height": "800",
        "form:login": username,
        "form:senha": password,
        "form:entrar": "Entrar",
        "javax.faces.ViewState": extract_viewstate(login_page.text),
        **_answer_captcha(client, login_page.text, str(login_page.url), profile),
    }
    # The post-login redirect targets the deprecated classic portal, whose
    # http->https hop drops a trailing slash and 404s. The session cookie is set
    # regardless, so the status of this response is irrelevant.
    try:
        client.post(profile.logon_url, data=fields, follow_redirects=False)
    except httpx.HTTPError:
        pass

    # Enter via the slash-terminated classic URL, which 302s to the full beta
    # portal. A plain GET of the beta URL returns only a loading shell.
    portal = client.get(profile.portal_entry_url)
    portal.raise_for_status()
    if profile.auth_marker not in portal.text:
        raise LoginRejectedError("login failed: SIGAA rejected the credentials or captcha")
    return portal.text


def _refuse_browser_session(profile: InstitutionProfile, password: str) -> None:
    # While the captcha was unsolved, students stored a browser session's Cookie
    # header in the password slot. It must be refused before any request, and one
    # containing "=" must never parse as form data.
    if not profile.session_cookie_names:
        return
    try:
        cookies = auth_session.parse_cookie_header(password)
    except MissingCredentialsError:
        return
    if profile.session_cookie_names <= cookies.keys():
        raise MissingCredentialsError(
            f"stored secret for {profile.label} is a browser session Cookie header, "
            "not a password; run `sigaa login` again and paste the password"
        )


def _answer_captcha(client, login_html: str, page_url: str, profile: InstitutionProfile) -> dict:
    """Solve the login page's ALTCHA challenge; return its hidden form field.

    The page is expected to carry the widget; its absence means the login page
    changed shape, which is never answered by posting a bare password.
    """
    widget = altcha_widget(login_html)
    if widget is None:
        raise UnrecognizedPageError("login", page_fingerprint(login_html))
    url = urljoin(page_url, widget.challenge)
    profile.validate_url(url)
    response = client.get(url)
    response.raise_for_status()
    challenge = parse_challenge(response.text)
    return {widget.name: form_field_value(challenge, solve(challenge))}


NAVIGATOR = UfpbNavigator()
