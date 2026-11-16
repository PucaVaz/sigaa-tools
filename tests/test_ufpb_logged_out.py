"""UFPB sends a dead session to /publico/, a page with no login form."""

import json
import secrets
import time
from pathlib import Path

import httpx

from sigaa.http import Session
from sigaa.institutions import get
from sigaa.institutions.ufpb import UfpbNavigator

FIXTURES = Path(__file__).parent / "fixtures"
UFPB = get("ufpb").profile
PUBLIC_AREA_URL = UFPB.host + "/publico/"
# Synthetic: the real page is a 677-byte public shell without "Sair do SIGAA",
# a login form or a logon.jsf link.
PUBLIC_AREA_HTML = "<html><head><title>SIGAA</title></head><body></body></html>"


def _challenge():
    return {
        "parameters": {
            "algorithm": "PBKDF2/SHA-256",
            "cost": 10,
            "expiresAt": int(time.time()) + 600,
            "keyLength": 32,
            "keyPrefix": "00",
            "nonce": secrets.token_hex(16),
            "salt": secrets.token_hex(16),
        },
        "signature": secrets.token_hex(32),
    }


def test_public_area_url_is_logged_out_whatever_the_text():
    navigator = UfpbNavigator()

    assert navigator.looks_logged_out(PUBLIC_AREA_HTML, PUBLIC_AREA_URL)
    assert navigator.looks_logged_out("", UFPB.host + "/publico")
    assert not navigator.looks_logged_out(PUBLIC_AREA_HTML, UFPB.host + "/publicon/")
    assert not navigator.looks_logged_out(PUBLIC_AREA_HTML, UFPB.portal_action_url)


def test_session_dying_mid_run_signs_in_again_instead_of_reaching_the_parsers():
    alive = {"value": False}
    posts = []
    page = f"<html>{UFPB.auth_marker}</html>"

    def handler(request):
        path = request.url.path
        if path == "/sigaa/logon.jsf" and request.method == "POST":
            posts.append(request)
            alive["value"] = True
            return httpx.Response(200, text=page)
        if path == "/sigaa/gerarDesafioCaptcha":
            return httpx.Response(200, text=json.dumps(_challenge()))
        if path == "/sigaa/logon.jsf":
            return httpx.Response(200, text=(FIXTURES / "ufpb_logon.html").read_text())
        if str(request.url) == PUBLIC_AREA_URL:
            return httpx.Response(200, text=PUBLIC_AREA_HTML)
        if not alive["value"]:
            return httpx.Response(302, headers={"Location": PUBLIC_AREA_URL})
        return httpx.Response(200, text=page)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    with Session(
        "test-student", secrets.token_urlsafe(16), profile=UFPB,
        navigator=UfpbNavigator(), client=client,
    ) as session:
        session.login()
        alive["value"] = False

        assert session.get(UFPB.ava_url) == page

    assert len(posts) == 2
