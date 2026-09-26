import secrets
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from sigaa.config import Settings
from sigaa.errors import (
    STAGE_AUTH,
    LoginRejectedError,
    MissingCredentialsError,
    SsoRedirectError,
    error_stage,
)
from sigaa.http import Session
from sigaa.institutions import auth_session, get

FIXTURES = Path(__file__).parent / "fixtures/ufcg"
SSO = "sso.example.edu.br"
PROFILE = replace(
    get("ufcg").profile, auth_mode="session", sso_hosts=frozenset({SSO})
)


class Navigator:
    def login(self, session):
        return auth_session.perform_login(session, PROFILE)

    def looks_logged_out(self, text, url=""):
        return url.endswith("/expired.jsp")


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
