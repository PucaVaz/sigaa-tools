"""A client that runs on an exported SIGAA session and never on a password."""

import secrets
from pathlib import Path

import httpx
import pytest

from sigaa.client import SigaaClient
from sigaa.errors import LoginRejectedError
from sigaa.institutions import auth_session, get

FIXTURES = Path(__file__).parent / "fixtures"
UFPB = get("ufpb").profile
PORTAL = (FIXTURES / "portal.html").read_text()
LOGIN_FORM = (FIXTURES / "auth_redirect.html").read_text()
REAL_HTTP_CLIENT = httpx.Client


class FakeSigaa:
    """UFPB's logon form and portal, recording every request it serves."""

    def __init__(self):
        self.cookies = {"JSESSIONID": secrets.token_hex(16), "sigscookie": secrets.token_hex(8)}
        self.session_alive = True
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url == UFPB.logon_url and request.method == "GET":
            return httpx.Response(200, text=LOGIN_FORM)
        if url == UFPB.logon_url:
            headers = [("Location", UFPB.portal_entry_url)] + [
                ("Set-Cookie", f"{name}={value}; Path=/") for name, value in self.cookies.items()
            ]
            return httpx.Response(302, headers=headers)
        if not (self.session_alive and self._carries_session(request)):
            return httpx.Response(200, text=LOGIN_FORM)
        if url == UFPB.portal_entry_url:
            return httpx.Response(302, headers={"Location": UFPB.portal_action_url})
        return httpx.Response(200, text=PORTAL)

    def _carries_session(self, request: httpx.Request) -> bool:
        sent = auth_session.parse_cookie_header(request.headers.get("cookie", "a=b"))
        return all(sent.get(name) == value for name, value in self.cookies.items())

    @property
    def logon_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if str(r.url) == UFPB.logon_url]


@pytest.fixture
def sigaa(monkeypatch) -> FakeSigaa:
    fake = FakeSigaa()

    def client_factory(**kwargs):
        return REAL_HTTP_CLIENT(transport=httpx.MockTransport(fake), **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)
    return fake


def _password_client() -> SigaaClient:
    return SigaaClient("test-student", secrets.token_urlsafe(), institution="ufpb")


def _exported_cookie(sigaa: FakeSigaa) -> str:
    with _password_client() as client:
        header = client.export_session_cookie()
    sigaa.requests.clear()
    return header


def test_export_returns_the_session_cookies_of_a_password_login(sigaa):
    header = _exported_cookie(sigaa)
    assert auth_session.parse_cookie_header(header) == sigaa.cookies


def test_exported_cookie_drives_a_fresh_client_without_a_password(sigaa):
    header = _exported_cookie(sigaa)

    with SigaaClient.from_session_cookie("test-student", header, institution="ufpb") as client:
        turmas = client.list_turmas()

    assert turmas
    assert sigaa.logon_requests == []
    assert all(r.method == "GET" for r in sigaa.requests)


def test_expired_session_raises_and_never_logs_in_with_a_password(sigaa):
    header = _exported_cookie(sigaa)
    sigaa.session_alive = False

    with SigaaClient.from_session_cookie("test-student", header, institution="ufpb") as client:
        with pytest.raises(LoginRejectedError, match="expired"):
            client.list_turmas()

    assert sigaa.logon_requests == []


def test_session_dying_mid_use_raises_instead_of_falling_back(sigaa):
    header = _exported_cookie(sigaa)

    with SigaaClient.from_session_cookie("test-student", header, institution="ufpb") as client:
        client.list_turmas()
        sigaa.session_alive = False
        with pytest.raises(LoginRejectedError, match="expired"):
            client._session.get(UFPB.portal_action_url)

    assert sigaa.logon_requests == []


def test_cookie_header_carries_only_sigaa_cookies(sigaa):
    with _password_client() as client:
        client.export_session_cookie()
        client._session._client.cookies.set("tracker", secrets.token_hex(4), domain="example.org")
        header = client._session.cookie_header()

    assert auth_session.parse_cookie_header(header) == sigaa.cookies
