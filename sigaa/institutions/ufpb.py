"""UFPB endpoints and JSF beta-portal navigation."""
from urllib.parse import urlsplit

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
    # The logon form carries an ALTCHA captcha, so a password cannot be posted
    # unattended: the student signs in with a browser and the session is replayed.
    auth_mode="session",
    session_cookie_names=SESSION_COOKIE_NAMES,
    form_charset=FORM_CHARSET,
)


class UfpbNavigator:
    def __init__(self, profile=PROFILE):
        self.profile = profile

    def login(self, session):
        from . import auth_session

        return auth_session.perform_login(session, self.profile)

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


NAVIGATOR = UfpbNavigator()
