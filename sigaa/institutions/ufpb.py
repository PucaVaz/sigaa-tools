"""UFPB endpoints and JSF beta-portal navigation."""
from ..errors import NavigationError
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

AUTH_MARKER = "Sair do SIGAA"
# Substring of the URL we get bounced to when a session expires.
LOGIN_REDIRECT_MARKER = "logon.jsf"

KEYRING_SERVICE = "sigaa-ufpb"
KEYRING_ACTIVE_USERNAME = "__active_username__"

# UFPB class-time slots. Day digits: 2=Mon .. 7=Sat. Shift: M/T/N.
# NOTE: clock times below are an UNCONFIRMED default; confirm against a turma's
# "Plano de Curso" before trusting them for calendar/ICS export.
SLOT_TIMES_UNCONFIRMED = {
    "M": {1: "07:00", 2: "07:50", 3: "08:50", 4: "09:40", 5: "10:40", 6: "11:30"},
    "T": {1: "13:00", 2: "13:50", 3: "14:50", 4: "15:40", 5: "16:40", 6: "17:30"},
    "N": {1: "18:30", 2: "19:20", 3: "20:20", 4: "21:10"},
}


MATRICULA_INSTRUCOES_URL = f"{BASE}/graduacao/matricula/instrucoes.jsf"
MATRICULA_TURMAS_CURRICULO_URL = f"{BASE}/graduacao/matricula/turmas_curriculo.jsf"

PROFILE = InstitutionProfile(
    key="ufpb", label="UFPB", host=HOST, logon_url=LOGON_URL,
    portal_entry_url=PORTAL_ENTRY_URL, portal_action_url=PORTAL_ACTION_URL,
    ava_url=AVA_URL, curriculum_entry_url=CURRICULUM_ENTRY_URL,
    curriculum_data_url=CURRICULUM_DATA_URL,
    matricula_instrucoes_url=MATRICULA_INSTRUCOES_URL,
    matricula_turmas_curriculo_url=MATRICULA_TURMAS_CURRICULO_URL,
    auth_marker=AUTH_MARKER, login_redirect_marker=LOGIN_REDIRECT_MARKER,
    keyring_service=KEYRING_SERVICE, slot_times=SLOT_TIMES_UNCONFIRMED, slot_minutes=50,
    menu_labels={
        MenuLabel.GRADES: "Minhas Notas", MenuLabel.ENROLL: "Realizar Matrícula",
        MenuLabel.TURMA_GRADES: "Ver Notas", MenuLabel.ATTENDANCE: "Frequência",
        MenuLabel.PLAN: "Plano de Curso", MenuLabel.PARTICIPANTS: "Participantes",
        MenuLabel.HISTORICO: "Histórico acadêmico",
        MenuLabel.DECLARACAO_VINCULO: "Declaração de vínculo",
        MenuLabel.ATESTADO: "Atestado de matrícula",
        MenuLabel.EXTENSION_DOCS: "Certificados e Declarações",
    }, capabilities=frozenset(Capability),
)


class UfpbNavigator:
    def __init__(self, profile=PROFILE):
        self.profile = profile

    def login(self, session):
        return perform_login(session._client, session._username, session._password, profile=self.profile)

    def looks_logged_out(self, text, url=""):
        return (self.profile.login_redirect_marker in url or
                (self.profile.auth_marker not in text and
                 self.profile.login_redirect_marker in text))

    def portal_menu_post(self, session, portal, label):
        from ..parsers.portal import build_menu_postback
        fields = build_menu_postback(portal, label)
        if fields is None:
            raise NavigationError(f"portal menu item not found: {label!r}")
        return session.post(self.profile.portal_action_url, fields)

    def enter_turma(self, session, portal, turma):
        from ..http import extract_viewstate
        return session.post(self.profile.portal_action_url, {
            turma.form_id: turma.form_id, turma.field: turma.field,
            "idTurma": turma.id_turma, "javax.faces.ViewState": extract_viewstate(portal),
        })

    def turma_menu_post(self, session, principal, label):
        from ..http import extract_viewstate
        from ..parsers.portal import find_menu_field
        field = find_menu_field(principal, label)
        if field is None:
            raise NavigationError(f"turma menu item not found: {label!r}")
        return session.post(self.profile.ava_url, {
            "formMenu": "formMenu", field: field,
            "javax.faces.ViewState": extract_viewstate(principal, default="j_id2"),
        })

    def open_event(self, session, portal, event_id):
        from ..http import extract_viewstate
        from ..parsers.tarefa import build_event_postback
        fields = build_event_postback(portal, event_id, extract_viewstate(portal))
        if fields is None:
            raise NavigationError("event postback not found")
        return session.post(self.profile.portal_action_url, fields)


def perform_login(client, username: str, password: str, *, profile=PROFILE) -> str:
    """Authenticate and return the rendered portal HTML (with the turma list).

    Raises ``LoginRejectedError`` (a ``ValueError``) if the resulting portal is
    not authenticated.
    """
    import httpx
    from ..errors import MissingCredentialsError, LoginRejectedError
    from ..http import extract_viewstate

    if not username or not password:
        raise MissingCredentialsError("missing SIGAA username or password")
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
        raise LoginRejectedError("login failed: SIGAA rejected the credentials or showed a CAPTCHA")
    return portal.text
