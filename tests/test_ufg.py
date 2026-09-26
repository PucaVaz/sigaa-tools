import secrets
from pathlib import Path

import httpx
import pytest

from sigaa import setup_wizard
from sigaa.config import Settings
from sigaa.errors import (
    STAGE_AUTH,
    LoginRejectedError,
    NavigationError,
    SsoRedirectError,
    UnsupportedFeatureError,
    error_stage,
)
from sigaa.http import Session
from sigaa.institutions import Capability, get
from sigaa.institutions import all as providers

# UFG has no live capture yet. The classic-portal contract fixture from UFCG
# stands in until one exists; it establishes nothing about UFG's own markup.
PORTAL = (Path(__file__).parent / "fixtures/ufcg/portal.html").read_text()
PROFILE = get("ufg").profile
NAVIGATOR = get("ufg").navigator
BASE = "https://sigaa.sistemas.ufg.br/sigaa"
CAS = (
    "https://sso.ufg.br/cas/login?locale=pt_BR&service="
    "https%3A%2F%2Fsigaa.sistemas.ufg.br%2Fsigaa%2FverTelaLogin.do"
)


def _session(handler, secret):
    # Follows redirects like the real Session client does.
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return Session("test-student", secret, profile=PROFILE, navigator=NAVIGATOR, client=client)


def test_ufg_is_a_provisional_session_profile_with_probed_features_only():
    assert PROFILE.host == "https://sigaa.sistemas.ufg.br"
    assert PROFILE.auth_mode == "session"
    assert PROFILE.sso_hosts == frozenset({"sso.ufg.br"})
    assert PROFILE.provisional
    assert PROFILE.capabilities == {
        Capability.PORTAL, Capability.NEWS, Capability.MATERIALS, Capability.GRADES,
        Capability.ATTENDANCE, Capability.PLAN, Capability.PARTICIPANTS,
    }
    for missing in (Capability.TASKS, Capability.CALENDAR,
                    Capability.MATRICULA, Capability.DOCUMENTS):
        with pytest.raises(UnsupportedFeatureError):
            PROFILE.require(missing)


def test_setup_wizard_does_not_offer_ufg():
    offered = [p.profile.key for p in providers() if not p.profile.provisional]
    assert "ufg" not in offered
    inputs = iter([""])
    chosen = setup_wizard.select_institution(lambda _: next(inputs))
    assert chosen.key != "ufg"


def test_ufg_login_replays_the_imported_session_on_sigaa_only():
    header = f"JSESSIONID={secrets.token_hex(16)}"
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=PORTAL)

    with _session(handler, header) as session:
        assert "dispatch=logOff" in session.login()
    assert [str(r.url) for r in requests] == [PROFILE.portal_entry_url]
    assert requests[0].headers["cookie"] == header


def test_ufg_expired_session_stops_at_the_cas_redirect():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": CAS})

    with _session(handler, f"JSESSIONID={secrets.token_hex(16)}") as session:
        with pytest.raises(SsoRedirectError, match="sso.ufg.br"):
            session.login()
    assert requests and all(r.url.host == "sigaa.sistemas.ufg.br" for r in requests)


def test_ufg_dead_session_bounces_to_expirada_and_is_an_auth_failure():
    # Observed live: a portal GET with a dead JSESSIONID 302s to an empty
    # /sigaa/expirada.jsp on the SIGAA host itself, not to CAS.
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("expirada.jsp"):
            return httpx.Response(200, text="<html><body></body></html>")
        return httpx.Response(302, headers={"Location": BASE + "/expirada.jsp"})

    with _session(handler, f"JSESSIONID={secrets.token_hex(16)}") as session:
        with pytest.raises(LoginRejectedError, match="expired") as caught:
            session.login()
    assert error_stage(caught.value) == STAGE_AUTH
    assert NAVIGATOR.looks_logged_out("", BASE + "/expirada.jsp")


def test_ufg_dead_session_mid_sync_triggers_relogin_not_a_parse():
    portal_calls = []

    def handler(request):
        if request.url == PROFILE.portal_entry_url:
            portal_calls.append(request)
            if len(portal_calls) == 1:
                return httpx.Response(200, text=PORTAL)
        return httpx.Response(302, headers={"Location": BASE + "/expirada.jsp"}) \
            if not request.url.path.endswith("expirada.jsp") \
            else httpx.Response(200, text="<html></html>")

    with _session(handler, f"JSESSIONID={secrets.token_hex(16)}") as session:
        session.login()
        with pytest.raises(LoginRejectedError, match="expired"):
            session.get(PROFILE.ava_url)
    # The expired page was never handed back as content: a re-login was attempted.
    assert len(portal_calls) == 2


def test_ufg_login_prompts_for_a_cookie_not_a_password(monkeypatch):
    header = f"JSESSIONID={secrets.token_hex(16)}"
    prompts, stored = [], {}
    monkeypatch.setattr(setup_wizard.getpass, "getpass", lambda p: prompts.append(p) or header)

    def verify(username, secret, *, institution=None):
        stored.update(username=username, secret=secret, institution=institution)
        return setup_wizard.LoginResult("n", "m", True, "stored", secret)

    monkeypatch.setattr(setup_wizard, "verify_and_store_login", verify)
    settings = Settings(institution="ufg")
    settings.username = "test-student"
    setup_wizard.prompt_login(settings)
    assert prompts == ["SIGAA Cookie header: "]
    assert stored == {"username": "test-student", "secret": header, "institution": "ufg"}


def test_ufg_enter_turma_replays_the_portal_class_form():
    from urllib.parse import parse_qs

    from sigaa.parsers import portal as portal_parser

    page = (Path(__file__).parent / "fixtures/ufg/portal.html").read_text()
    turma = portal_parser.parse_turmas(page)[1]
    posts = []

    def handler(request):
        if request.method == "POST":
            posts.append((str(request.url), parse_qs(request.content.decode())))
            return httpx.Response(200, text="<html>principal</html>")
        return httpx.Response(200, text=PORTAL)

    with _session(handler, f"JSESSIONID={secrets.token_hex(16)}") as session:
        session.login()
        assert NAVIGATOR.enter_turma(session, page, turma) == "<html>principal</html>"
    assert posts == [(PROFILE.portal_action_url, {
        "form_acessarTurmaVirtualj_id_3": ["form_acessarTurmaVirtualj_id_3"],
        "form_acessarTurmaVirtualj_id_3:turmaVirtualj_id_3":
            ["form_acessarTurmaVirtualj_id_3:turmaVirtualj_id_3"],
        "idTurma": ["1050315"],
        "javax.faces.ViewState": ["j_id4"],
    })]


def test_ufg_class_menu_posts_the_form_to_the_turma_virtual():
    from urllib.parse import parse_qs

    menu = (Path(__file__).parent / "fixtures/ufg/turma_menu.html").read_text()
    posts = []

    def handler(request):
        if request.method == "POST":
            posts.append((str(request.url), parse_qs(request.content.decode())))
            return httpx.Response(200, text="<html>notas</html>")
        return httpx.Response(200, text=PORTAL)

    with _session(handler, f"JSESSIONID={secrets.token_hex(16)}") as session:
        session.login()
        assert NAVIGATOR.turma_menu_post(session, menu, "Ver Notas") == "<html>notas</html>"
        with pytest.raises(NavigationError):
            NAVIGATOR.turma_menu_post(session, menu, "Situação dos Discentes")
    assert posts == [(PROFILE.ava_url, {
        "formMenu": ["formMenu"],
        "formMenu:j_id_jsp_2083335174_44": ["formMenu:j_id_jsp_2083335174_45"],
        "formMenu:j_id_jsp_2083335174_70": ["formMenu:j_id_jsp_2083335174_70"],
        "javax.faces.ViewState": ["j_id8"],
    })]


def test_ufg_menu_labels_match_the_turma_virtual():
    from sigaa.institutions import MenuLabel

    assert PROFILE.menu_labels == {
        MenuLabel.GRADES: "Minhas Notas",
        MenuLabel.TURMA_GRADES: "Ver Notas",
        MenuLabel.ATTENDANCE: "Frequência",
        MenuLabel.PLAN: "Plano de Curso",
        MenuLabel.PARTICIPANTS: "Participantes",
    }


def test_ufg_portal_menu_posts_the_jscook_form():
    from urllib.parse import parse_qs

    menu = (Path(__file__).parent / "fixtures/ufg/portal_menu.html").read_text()
    posts = []

    def handler(request):
        if request.method == "POST":
            posts.append((str(request.url), parse_qs(request.content.decode(),
                                                     keep_blank_values=True)))
            return httpx.Response(200, text="<html>notas</html>")
        return httpx.Response(200, text=PORTAL)

    with _session(handler, f"JSESSIONID={secrets.token_hex(16)}") as session:
        session.login()
        assert NAVIGATOR.portal_menu_post(session, menu, "Minhas Notas") == "<html>notas</html>"
        with pytest.raises(NavigationError):
            NAVIGATOR.portal_menu_post(session, menu, "Consultar Histórico")
    url, fields = posts[0]
    assert url == PROFILE.portal_action_url and len(posts) == 1
    assert fields["jscook_action"] == [
        "menu_form_menu_discente_j_id_jsp_1051041857_97_menu:A]#{ relatorioNotasAluno.gerarRelatorio }"]
    assert set(fields) == {"menu:form_menu_discente", "id", "jscook_action", "javax.faces.ViewState"}
