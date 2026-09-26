import secrets
from pathlib import Path

import httpx
import pytest

from sigaa import setup_wizard
from sigaa.config import Settings
from sigaa.errors import (
    STAGE_AUTH,
    LoginRejectedError,
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


def test_ufg_is_a_provisional_session_profile_without_features():
    assert PROFILE.host == "https://sigaa.sistemas.ufg.br"
    assert PROFILE.auth_mode == "session"
    assert PROFILE.sso_hosts == frozenset({"sso.ufg.br"})
    assert PROFILE.provisional
    assert PROFILE.capabilities == frozenset()
    with pytest.raises(UnsupportedFeatureError):
        PROFILE.require(Capability.PORTAL)


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
