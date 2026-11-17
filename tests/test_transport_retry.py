"""One slow or dropped response must not fail a whole sync run.

A sync is ~75 sequential requests; before this, a single read timeout on any of
them failed the run. Read-only requests are now resent a bounded number of times.
A form that changes account state is never resent: SIGAA may already have
processed it when the response was lost.
"""

import secrets

import httpx
import pytest

from sigaa import http
from sigaa.errors import STAGE_NETWORK, error_stage
from sigaa.http import Session
from sigaa.institutions.ufpb import PROFILE as UFPB
from sigaa.institutions.ufpb import UfpbNavigator

PAGE = "<html><body>turma virtual</body></html>"
FORM = {"formMenu": "formMenu"}


class _FlakyServer:
    """Drops the first ``failures`` requests with ``error``, then answers."""

    def __init__(self, failures: int, error: type[httpx.TransportError] = httpx.ReadTimeout):
        self.failures = failures
        self.error = error
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if len(self.requests) <= self.failures:
            raise self.error("The read operation timed out", request=request)
        return httpx.Response(200, text=PAGE)


def _session(server: _FlakyServer, waits: list[float]) -> Session:
    session = Session(
        "test-student",
        secrets.token_urlsafe(16),
        profile=UFPB,
        navigator=UfpbNavigator(),
        client=httpx.Client(transport=httpx.MockTransport(server), follow_redirects=True),
        sleep=waits.append,
    )
    session._authenticated = True
    return session


def test_a_get_is_resent_after_a_read_timeout():
    server, waits = _FlakyServer(failures=1), []

    assert _session(server, waits).get(UFPB.ava_url) == PAGE
    assert len(server.requests) == 2
    assert len(waits) == 1


def test_a_navigation_postback_is_resent_after_a_read_timeout():
    server, waits = _FlakyServer(failures=1), []

    assert _session(server, waits).post_navigation(UFPB.ava_url, FORM) == PAGE
    assert len(server.requests) == 2
    assert server.requests[1].content == server.requests[0].content


def test_a_navigation_postback_is_resent_after_a_dropped_connection():
    server, waits = _FlakyServer(failures=1, error=httpx.RemoteProtocolError), []

    assert _session(server, waits).post_navigation(UFPB.ava_url, FORM) == PAGE


def test_a_state_changing_form_is_never_resent():
    server, waits = _FlakyServer(failures=1), []

    with pytest.raises(httpx.ReadTimeout):
        _session(server, waits).post(UFPB.ava_url, FORM)

    assert len(server.requests) == 1
    assert waits == []


def test_resending_stops_at_the_bound_and_stays_a_network_failure():
    server, waits = _FlakyServer(failures=http.MAX_RESENDS + 1), []

    with pytest.raises(httpx.ReadTimeout) as failure:
        _session(server, waits).post_navigation(UFPB.ava_url, FORM)

    assert len(server.requests) == http.MAX_RESENDS + 1
    assert error_stage(failure.value) == STAGE_NETWORK


def test_each_resend_waits_longer_than_the_one_before():
    server, waits = _FlakyServer(failures=http.MAX_RESENDS), []

    _session(server, waits).get(UFPB.ava_url)

    assert waits == sorted(waits)
    assert len(set(waits)) == len(waits) == http.MAX_RESENDS


def test_an_http_error_status_is_not_resent():
    requests: list[httpx.Request] = []

    def unavailable(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503)

    waits: list[float] = []
    session = Session(
        "test-student",
        secrets.token_urlsafe(16),
        profile=UFPB,
        navigator=UfpbNavigator(),
        client=httpx.Client(transport=httpx.MockTransport(unavailable)),
        sleep=waits.append,
    )
    session._authenticated = True

    with pytest.raises(httpx.HTTPStatusError):
        session.get(UFPB.ava_url)

    assert len(requests) == 1


def test_the_default_client_retries_a_connection_that_was_never_established(monkeypatch):
    """Connection failures happen before any byte is sent, so every request,
    login included, may retry them."""
    captured: dict[str, object] = {}

    class RecordingTransport(httpx.HTTPTransport):
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(httpx, "HTTPTransport", RecordingTransport)

    Session(
        "test-student", secrets.token_urlsafe(16), profile=UFPB, navigator=UfpbNavigator()
    ).close()

    assert captured["retries"] == http.CONNECT_RETRIES
    assert http.CONNECT_RETRIES > 0


def test_ufpb_turma_navigation_uses_resendable_postbacks():
    class RecordingSession:
        def __init__(self) -> None:
            self.navigation_posts = 0

        def post_navigation(self, url: str, fields: dict) -> str:
            self.navigation_posts += 1
            return PAGE

    principal = (
        '<form id="formMenu">'
        """<a href="#" onclick="jsfcljs(document.getElementById('formMenu'),"""
        """{'menu:plano':'menu:plano'},'');">Plano de Curso</a>"""
        '<input name="javax.faces.ViewState" value="j_id2"/></form>'
    )
    session = RecordingSession()

    UfpbNavigator().turma_menu_post(session, principal, "Plano de Curso")

    assert session.navigation_posts == 1
