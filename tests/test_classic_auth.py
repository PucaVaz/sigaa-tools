import hashlib
import json
import secrets
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from sigaa.errors import (
    LoginRejectedError,
    UnrecognizedPageError,
    UnsafeUrlError,
    UnsupportedFeatureError,
)
from sigaa.exporters.ics import build_calendar
from sigaa.http import Session
from sigaa.institutions import get
from sigaa.institutions.auth_classic import login_action
from sigaa.onboard.probe import probe

FIXTURES = Path(__file__).parent / "fixtures/ufcg"
PROFILE = get("ufcg").profile
NAVIGATOR = get("ufcg").navigator


@pytest.mark.parametrize("portal", ["portal.html", "portal_script_menu.html"])
def test_classic_login_uses_rendered_fields_and_redirects(portal):
    secret = secrets.token_urlsafe()
    requests = []
    login = (FIXTURES / "login.html").read_text()
    login = login.replace("user.login", "account").replace("user.senha", "passcode")

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("verTelaLogin.do"):
            return httpx.Response(200, text=login)
        if request.method == "POST":
            fields = parse_qs(request.content.decode())
            assert fields["account"] == ["test-student"]
            assert fields["passcode"] == [secret]
            assert fields["width"] == ["1280"]
            return httpx.Response(302, headers={"Location": PROFILE.portal_entry_url})
        return httpx.Response(200, text=(FIXTURES / portal).read_text())

    with Session("test-student", secret, profile=PROFILE, navigator=NAVIGATOR,
                 client=httpx.Client(transport=httpx.MockTransport(handler))) as session:
        html = session.login()
        assert "dispatch=logOff" in html
        assert session._authenticated
    assert len(requests) == 3
    assert all(request.url.host == "sigaa.ufcg.edu.br" for request in requests)


@pytest.mark.parametrize("redirect", [False, True])
def test_classic_login_blocks_foreign_action_and_redirect(redirect):
    requests = []
    login = (FIXTURES / "login.html").read_text()
    if not redirect:
        login = login.replace('/sigaa/logar.do', 'https://foreign.example/logar.do')

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, text=login)
        return httpx.Response(307, headers={"Location": "https://foreign.example/"})

    with Session("test", secrets.token_urlsafe(), profile=PROFILE, navigator=NAVIGATOR,
                 client=httpx.Client(transport=httpx.MockTransport(handler))) as session:
        with pytest.raises(UnsafeUrlError):
            session.login()
    assert len(requests) == (2 if redirect else 1)
    assert all(request.url.host == "sigaa.ufcg.edu.br" for request in requests)


def test_classic_rejection_does_not_fall_back_past_login():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, text=(FIXTURES / "login.html").read_text())

    with Session("test", secrets.token_urlsafe(), profile=PROFILE, navigator=NAVIGATOR,
                 client=httpx.Client(transport=httpx.MockTransport(handler))) as session:
        with pytest.raises(LoginRejectedError):
            session.login()
    assert len(calls) == 2


def test_classic_ambiguous_form_is_rejected():
    html = (FIXTURES / "login.html").read_text()
    with pytest.raises(UnrecognizedPageError):
        login_action(html + html, PROFILE.logon_url)


def test_ufcg_portal_probe_is_loud_and_calendar_is_unsupported(tmp_path):
    body = (FIXTURES / "portal.html").read_bytes()
    (tmp_path / "portal.body").write_bytes(body)
    (tmp_path / "manifest.json").write_text(json.dumps({"institution": "ufcg", "entries": [
        {"feature": feature, "status": "captured", "file": "portal.body",
         "sha256": hashlib.sha256(body).hexdigest()}
        for feature in ("student", "turmas", "deadlines")
    ]}))
    portal_features = {"student", "turmas", "deadlines"}
    rows = [row for row in probe(tmp_path)["features"] if row["feature"] in portal_features]
    assert rows and all(row["status"] == "unrecognized" for row in rows)
    with pytest.raises(UnsupportedFeatureError):
        build_calendar([], [], institution="ufcg")


def test_unsupported_ufcg_features_do_not_read_store(monkeypatch, capsys, tmp_path):
    from sigaa.cli import main
    monkeypatch.setenv("SIGAA_INSTITUTION", "ufcg")
    monkeypatch.setenv("SIGAA_DB", str(tmp_path / "never-created.db"))
    assert main(["grades", "--json"]) == 1
    assert '"unsupported"' in capsys.readouterr().out
    assert not (tmp_path / "never-created.db").exists()
    from sigaa.mcp_server import sigaa_list_grades
    with pytest.raises(UnsupportedFeatureError):
        sigaa_list_grades()


@pytest.mark.parametrize("name", [
    "sigaa_list_classes", "sigaa_get_schedule", "sigaa_list_deadlines",
    "sigaa_whats_new", "sigaa_sync",
])
def test_ufcg_portal_tools_reject_before_store_or_network(name, monkeypatch):
    from sigaa import mcp_server
    monkeypatch.setenv("SIGAA_INSTITUTION", "ufcg")
    monkeypatch.setattr(mcp_server, "_repo", lambda: pytest.fail("opened database"))
    monkeypatch.setattr(mcp_server, "run_sync", lambda *a, **kw: pytest.fail("ran sync"))
    with pytest.raises(UnsupportedFeatureError):
        getattr(mcp_server, name)()


@pytest.mark.parametrize("method", ["get_student", "list_turmas", "list_deadlines"])
def test_ufcg_public_portal_client_is_disabled(method, monkeypatch):
    from sigaa.client import SigaaClient
    with SigaaClient("synthetic", secrets.token_urlsafe(), institution="ufcg") as client:
        monkeypatch.setattr(client, "_portal", lambda: pytest.fail("requested portal"))
        with pytest.raises(UnsupportedFeatureError):
            getattr(client, method)()


def test_ufcg_auth_only_capture_still_diagnoses_portal(monkeypatch, tmp_path):
    from sigaa.client import SigaaClient
    from sigaa.config import Settings
    from sigaa.onboard import capture as capture_module

    body = (FIXTURES / "portal.html").read_bytes()
    def factory(username, password, **kwargs):
        client = SigaaClient(username, password, **kwargs)
        client._session._client.close()
        client._session._client = httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=body)))
        client._session.login = lambda: client._session._client.get(PROFILE.portal_entry_url).text
        return client
    monkeypatch.setattr(capture_module, "SigaaClient", factory)
    monkeypatch.setenv("SIGAA_PASS", secrets.token_urlsafe())
    directory, manifest = capture_module.capture(
        Settings(username="synthetic", institution="ufcg"), output=tmp_path / "captures")
    assert sum(e["status"] == "captured" for e in manifest["entries"]) == 3
    assert any(e["status"] == "nav_failed" for e in manifest["entries"])
    rows = probe(directory)["features"]
    assert all(row["status"] == "unrecognized" for row in rows
               if row["feature"] in {"student", "turmas", "deadlines"})
    assert any(row["status"] == "nav_failed" for row in rows)
