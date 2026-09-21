from pathlib import Path
import secrets
from urllib.parse import parse_qs

import httpx
import pytest

from sigaa.errors import LoginRejectedError, UnsafeUrlError, UnrecognizedPageError, UnsupportedFeatureError
from sigaa.http import Session
from sigaa.institutions import get
from sigaa.institutions.auth_classic import login_action
from sigaa.onboard.probe import probe

FIXTURES = Path(__file__).parent / "fixtures/ufcg"
PROFILE = get("ufcg").profile


@pytest.mark.parametrize("portal", ["portal.html", "portal_script_menu.html"])
def test_classic_login_uses_rendered_fields_and_redirects(portal):
    secret = secrets.token_urlsafe()
    requests = []
    login = (FIXTURES / "login.html").read_text().replace("user.login", "account").replace("user.senha", "passcode")
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
    with Session("test-student", secret, profile=PROFILE,
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
    with Session("test", secrets.token_urlsafe(), profile=PROFILE,
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
    with Session("test", secrets.token_urlsafe(), profile=PROFILE,
                 client=httpx.Client(transport=httpx.MockTransport(handler))) as session:
        with pytest.raises(LoginRejectedError):
            session.login()
    assert len(calls) == 2


def test_classic_ambiguous_form_is_rejected():
    html = (FIXTURES / "login.html").read_text()
    with pytest.raises(UnrecognizedPageError):
        login_action(html + html, PROFILE.logon_url)


def test_ufcg_portal_probe_is_loud_and_calendar_is_unsupported(tmp_path):
    import hashlib
    import json
    from sigaa.exporters.ics import build_calendar
    body = (FIXTURES / "portal.html").read_bytes()
    (tmp_path / "portal.body").write_bytes(body)
    (tmp_path / "manifest.json").write_text(json.dumps({"institution": "ufcg", "entries": [
        {"feature": feature, "status": "captured", "file": "portal.body",
         "sha256": hashlib.sha256(body).hexdigest()}
        for feature in ("student", "turmas", "deadlines")
    ]}))
    rows = probe(tmp_path)["features"]
    assert all(row["status"] == "unrecognized" for row in rows if row["feature"] in {"student", "turmas", "deadlines"})
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
