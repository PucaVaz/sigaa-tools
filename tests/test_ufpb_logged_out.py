"""UFPB sends a dead session to /publico/, a page with no login form."""

import secrets

import httpx
import pytest

from sigaa.errors import STAGE_AUTH, LoginRejectedError, error_stage
from sigaa.http import Session
from sigaa.institutions import get
from sigaa.institutions.ufpb import UfpbNavigator

UFPB = get("ufpb").profile
PUBLIC_AREA_URL = UFPB.host + "/publico/"
# Synthetic: the real page is a 677-byte public shell without "Sair do SIGAA",
# a login form or a logon.jsf link.
PUBLIC_AREA_HTML = "<html><head><title>SIGAA</title></head><body></body></html>"


def _dead_session_response(request):
    if str(request.url) == PUBLIC_AREA_URL:
        return httpx.Response(200, text=PUBLIC_AREA_HTML)
    return httpx.Response(302, headers={"Location": PUBLIC_AREA_URL})


def _cookie():
    return f"JSESSIONID={secrets.token_hex(16)}; sigscookie={secrets.token_hex(8)}"


def _session(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return Session("test-student", _cookie(), profile=UFPB, navigator=UfpbNavigator(), client=client)


def test_public_area_url_is_logged_out_whatever_the_text():
    navigator = UfpbNavigator()

    assert navigator.looks_logged_out(PUBLIC_AREA_HTML, PUBLIC_AREA_URL)
    assert navigator.looks_logged_out("", UFPB.host + "/publico")
    assert not navigator.looks_logged_out(PUBLIC_AREA_HTML, UFPB.host + "/publicon/")
    assert not navigator.looks_logged_out(PUBLIC_AREA_HTML, UFPB.portal_action_url)


def test_dead_session_at_login_is_reported_as_expired():
    with _session(_dead_session_response) as session:
        with pytest.raises(LoginRejectedError, match="expired") as excinfo:
            session.login()
    assert error_stage(excinfo.value) == STAGE_AUTH


def test_session_dying_mid_run_is_an_auth_failure_not_a_parse_one():
    alive = {"value": True}

    def handler(request):
        if not alive["value"]:
            return _dead_session_response(request)
        return httpx.Response(200, text=f"<html>{UFPB.auth_marker}</html>")

    with _session(handler) as session:
        session.login()
        alive["value"] = False
        with pytest.raises(LoginRejectedError, match="expired") as excinfo:
            session.get(UFPB.ava_url)
    assert error_stage(excinfo.value) == STAGE_AUTH
