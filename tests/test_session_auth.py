import base64
import hashlib
import json
import secrets
import struct
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from sigaa.config import Settings
from sigaa.errors import (
    STAGE_AUTH,
    LoginRejectedError,
    MissingCredentialsError,
    SsoRedirectError,
    UnrecognizedPageError,
    error_stage,
)
from sigaa.http import Session
from sigaa.institutions import all as all_institutions
from sigaa.institutions import auth_session, get
from sigaa.institutions.ufpb import UfpbNavigator
from sigaa.parsers.authentication import altcha_widget, authenticated_portal

FIXTURES = Path(__file__).parent / "fixtures/ufcg"
UFPB_FIXTURES = Path(__file__).parent / "fixtures"
SSO = "sso.example.edu.br"
PROFILE = replace(
    get("ufcg").profile, auth_mode="session", sso_hosts=frozenset({SSO})
)
UFPB = get("ufpb").profile


class Navigator:
    def login(self, session):
        return auth_session.perform_login(session, PROFILE)

    def looks_logged_out(self, text, url=""):
        return url.endswith("/expired.jsp")

    def portal_reached(self, text, url=""):
        return authenticated_portal(text, url, PROFILE)


def _cookie():
    return f"JSESSIONID={secrets.token_hex(16)}; sigscookie={secrets.token_hex(8)}"


def _session(handler, secret):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Session("test-student", secret, profile=PROFILE, navigator=Navigator(), client=client)


def _sso_bounce(request):
    return httpx.Response(302, headers={"Location": f"https://{SSO}/cas/login?service=x"})


def test_imported_session_reaches_portal_with_the_stored_cookies():
    header = _cookie()
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=(FIXTURES / "portal.html").read_text())

    with _session(handler, header) as session:
        assert "dispatch=logOff" in session.login()
        assert session._authenticated
    assert len(requests) == 1
    assert requests[0].url == PROFILE.portal_entry_url
    assert requests[0].headers["cookie"] == header
    assert requests[0].method == "GET"


def test_expired_session_never_follows_the_sso_redirect():
    requests = []

    def handler(request):
        requests.append(request)
        return _sso_bounce(request)

    with _session(handler, _cookie()) as session:
        with pytest.raises(SsoRedirectError) as caught:
            session.login()
    assert all(request.url.host != SSO for request in requests)
    assert error_stage(caught.value) == STAGE_AUTH
    # Callers that catch the old ValueError/LoginRejectedError still handle it.
    assert isinstance(caught.value, LoginRejectedError)
    assert "cas/login" not in str(caught.value)


def test_sso_bounce_mid_session_is_an_auth_failure():
    portal = (FIXTURES / "portal.html").read_text()

    def handler(request):
        if request.url == PROFILE.portal_entry_url:
            return httpx.Response(200, text=portal)
        return _sso_bounce(request)

    with _session(handler, _cookie()) as session:
        session.login()
        with pytest.raises(SsoRedirectError):
            session._client.get(PROFILE.ava_url, follow_redirects=True)


def test_login_page_without_redirect_is_rejected():
    def handler(request):
        return httpx.Response(200, text=(FIXTURES / "login.html").read_text())

    with _session(handler, _cookie()) as session:
        with pytest.raises(LoginRejectedError, match="expired"):
            session.login()


@pytest.mark.parametrize("header", ["", "not a cookie", "a=b\r\nX-Injected: 1"])
def test_malformed_session_is_refused_before_any_request(header):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200)

    with _session(handler, header) as session:
        with pytest.raises(MissingCredentialsError):
            session.login()
    assert requests == []


def test_cookie_header_prefix_is_accepted():
    # Built at runtime so the literal never looks like a captured Cookie header
    # to `sigaa onboard check`.
    header = "Cookie" + ": a=1; b=2"
    assert auth_session.parse_cookie_header(header) == {"a": "1", "b": "2"}


def test_session_institution_falls_back_to_sigaa_session_not_sigaa_pass(monkeypatch):
    import sigaa.config as config_module

    monkeypatch.setattr(config_module, "get", lambda key=None: type(
        "P", (), {"profile": PROFILE})())
    monkeypatch.setenv("SIGAA_USER", "test-student")
    monkeypatch.setenv("SIGAA_PASS", secrets.token_urlsafe())
    monkeypatch.delenv("SIGAA_SESSION", raising=False)
    settings = Settings(institution="ufcg")
    settings.username = "test-student"
    monkeypatch.setattr("keyring.get_password", lambda *a: None)
    with pytest.raises(MissingCredentialsError, match="SIGAA_SESSION"):
        settings.require_credentials()
    header = _cookie()
    monkeypatch.setenv("SIGAA_SESSION", header)
    assert settings.require_credentials() == ("test-student", header)


def test_password_institutions_are_unchanged():
    assert get("ufcg").profile.auth_mode == "password"
    assert get("ufcg").profile.sso_hosts == frozenset()
    assert get("ufpb").profile.auth_mode == "password"
    assert get("ufpb").profile.sso_hosts == frozenset()


def test_navigator_expired_page_without_login_form_is_an_expired_session():
    # Some forks bounce a dead session to an empty page of their own, not a form.
    def handler(request):
        if request.url.path.endswith("/expired.jsp"):
            return httpx.Response(200, text="<html><body></body></html>")
        return httpx.Response(302, headers={"Location": PROFILE.host + "/sigaa/expired.jsp"})

    with _session(handler, _cookie()) as session:
        with pytest.raises(LoginRejectedError, match="expired"):
            session.login()


def _ufpb_session(handler, secret):
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return Session(
        "test-student", secret, profile=UFPB, navigator=UfpbNavigator(), client=client
    )


def test_every_navigator_judges_the_portal():
    for institution in all_institutions():
        assert callable(institution.navigator.portal_reached), institution.profile.key


def test_ufpb_signs_in_by_password_after_solving_the_captcha():
    challenge = _challenge_json()
    posts = []
    challenge_fetches = []

    def handler(request):
        if request.url.path == "/sigaa/logon.jsf" and request.method == "POST":
            posts.append(parse_qs(request.content.decode()))
            # The post-login redirect targets a classic URL that 404s; the real
            # flow ignores it and enters through portal_entry_url instead.
            return httpx.Response(
                302, headers={"Location": "http://sigaa.ufpb.br/sigaa/portais/discente/discente.jsf"}
            )
        if request.url.path == "/sigaa/gerarDesafioCaptcha":
            challenge_fetches.append(request)
            return httpx.Response(200, text=json.dumps(challenge))
        if request.url.path == "/sigaa/logon.jsf":
            return httpx.Response(200, text=(UFPB_FIXTURES / "ufpb_logon.html").read_text())
        if str(request.url) == UFPB.portal_entry_url:
            return httpx.Response(302, headers={"Location": UFPB.portal_action_url})
        return httpx.Response(200, text=(UFPB_FIXTURES / "portal.html").read_text())

    password = secrets.token_urlsafe(16)
    with _ufpb_session(handler, password) as session:
        assert UFPB.auth_marker in session.login()
        assert session._authenticated

    assert [r.method for r in challenge_fetches] == ["GET"]
    assert len(posts) == 1
    fields = posts[0]
    assert fields["form:login"] == ["test-student"]
    assert fields["form:senha"] == [password]
    assert fields["form:entrar"] == ["Entrar"]
    payload = json.loads(base64.b64decode(fields["altcha"][0]))
    assert payload["challenge"]["parameters"] == challenge["parameters"]
    assert payload["challenge"]["signature"] == challenge["signature"]
    # Verify the answer the way the server does: one derivation at the posted counter.
    parameters = challenge["parameters"]
    key = hashlib.pbkdf2_hmac(
        "sha256",
        bytes.fromhex(parameters["nonce"]) + struct.pack(">I", payload["solution"]["counter"]),
        bytes.fromhex(parameters["salt"]),
        parameters["cost"],
        parameters["keyLength"],
    ).hex()
    assert payload["solution"]["derivedKey"] == key
    assert key.startswith(parameters["keyPrefix"])


def test_ufpb_rejected_credentials_or_captcha_is_reported():
    def handler(request):
        if request.url.path == "/sigaa/logon.jsf" and request.method == "POST":
            return httpx.Response(200, text=(UFPB_FIXTURES / "ufpb_logon.html").read_text())
        if request.url.path == "/sigaa/gerarDesafioCaptcha":
            return httpx.Response(200, text=json.dumps(_challenge_json()))
        if request.url.path == "/sigaa/logon.jsf":
            return httpx.Response(200, text=(UFPB_FIXTURES / "ufpb_logon.html").read_text())
        return httpx.Response(200, text=(UFPB_FIXTURES / "auth_redirect.html").read_text())

    with _ufpb_session(handler, secrets.token_urlsafe(16)) as session:
        with pytest.raises(LoginRejectedError, match="rejected the credentials or captcha"):
            session.login()


def test_ufpb_login_page_without_the_altcha_widget_is_never_posted():
    # A captcha-protected login page that no longer shows the widget has changed
    # shape; posting a bare password to it would be a guess.
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=(UFPB_FIXTURES / "auth_redirect.html").read_text())

    with _ufpb_session(handler, secrets.token_urlsafe(16)) as session:
        with pytest.raises(UnrecognizedPageError, match="unrecognized login page"):
            session.login()
    assert all(r.method == "GET" for r in requests)
    assert all(r.url.path == "/sigaa/logon.jsf" for r in requests)


def test_altcha_widget_is_read_from_the_login_page():
    widget = altcha_widget((UFPB_FIXTURES / "ufpb_logon.html").read_text())

    assert widget.name == "altcha"
    assert widget.challenge == "/sigaa/gerarDesafioCaptcha"


def test_altcha_widget_without_a_challenge_url_is_unrecognized():
    with pytest.raises(UnrecognizedPageError):
        altcha_widget('<html><body><altcha-widget name="altcha"></altcha-widget></body></html>')


def test_ufpb_navigator_tells_the_portal_from_the_login_form():
    portal = (UFPB_FIXTURES / "portal.html").read_text()
    assert UfpbNavigator().portal_reached(portal, UFPB.portal_action_url)
    assert not UfpbNavigator().portal_reached(
        (UFPB_FIXTURES / "auth_redirect.html").read_text(), UFPB.logon_url
    )


def test_ufpb_posts_the_password_only_after_the_captcha_is_solved():
    # The logon form carries an ALTCHA captcha, which the navigator solves before
    # posting; the session-replay path of #54 is no longer UFPB's login.
    assert UFPB.auth_mode == "password"
    assert "gerarDesafioCaptcha" in (UFPB_FIXTURES / "ufpb_logon.html").read_text()


@pytest.mark.parametrize("with_extra_cookie", [False, True])
def test_ufpb_stored_browser_session_is_refused_before_any_request(with_extra_cookie):
    # Students who onboarded while the captcha was unsolved hold a Cookie header
    # in the password slot. One containing "=" must never parse as form data.
    stored = f"JSESSIONID={secrets.token_hex(16)}"
    if with_extra_cookie:
        stored += f"; sigscookie={secrets.token_hex(8)}"
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200)

    with _ufpb_session(handler, stored) as session:
        with pytest.raises(MissingCredentialsError) as excinfo:
            session.login()
    assert error_stage(excinfo.value) == STAGE_AUTH
    assert stored not in str(excinfo.value)
    assert requests == []


def test_ufpb_session_variable_alone_is_named_as_unused(monkeypatch):
    monkeypatch.setenv("SIGAA_SESSION", _cookie())
    monkeypatch.delenv("SIGAA_PASS", raising=False)
    monkeypatch.setattr("keyring.get_password", lambda *a: None)
    settings = Settings(institution="ufpb")
    settings.username = "test-student"

    problem = settings.credentials_problem()

    assert "SIGAA_PASS" in problem
    assert "SIGAA_SESSION is not used for UFPB" in problem


def _challenge_json(cost=10):
    """A challenge like the endpoint serves: random nonce and salt, future expiry."""
    return {
        "parameters": {
            "algorithm": "PBKDF2/SHA-256",
            "cost": cost,
            "expiresAt": int(time.time()) + 600,
            "keyLength": 32,
            "keyPrefix": "00",
            "nonce": secrets.token_hex(16),
            "salt": secrets.token_hex(16),
        },
        "signature": secrets.token_hex(32),
    }
