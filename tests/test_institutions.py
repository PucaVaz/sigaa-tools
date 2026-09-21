import secrets
from dataclasses import replace

import httpx
import pytest

from sigaa.config import Settings, default_db_path
from sigaa.errors import UnsafeUrlError, UnsupportedFeatureError
from sigaa.http import Session
from sigaa.institutions import Capability, get
from sigaa.institutions.base import Institution
from sigaa.institutions import registry


@pytest.fixture
def other(monkeypatch):
    original = get()
    profile = replace(original.profile, key="example", host="https://sigaa.example.edu",
                      keyring_service="sigaa-example", capabilities=frozenset())
    monkeypatch.setitem(registry._PROVIDERS, profile.key, Institution(profile, original.navigator))
    return profile


def test_store_and_account_are_isolated(other, clean_credentials, monkeypatch, tmp_path):
    monkeypatch.delenv("SIGAA_DB", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    clean_credentials[(other.keyring_service, "__active_username__")] = "other-student"
    settings = Settings(institution=other.key)
    assert settings.username == "other-student"
    assert settings.db_path == tmp_path / "sigaa-tools/example/sigaa.db"
    assert default_db_path(get().profile.key) == tmp_path / "sigaa-tools/sigaa.db"
    monkeypatch.setenv("SIGAA_DB", str(tmp_path / "override.db"))
    assert default_db_path(other.key) == tmp_path / "override.db"


def test_institution_resolution_precedence(other, clean_credentials, monkeypatch):
    from sigaa.config import KEYRING_SETTINGS_SERVICE, KEYRING_ACTIVE_INSTITUTION
    clean_credentials[(KEYRING_SETTINGS_SERVICE, KEYRING_ACTIVE_INSTITUTION)] = other.key
    assert Settings().institution == other.key
    monkeypatch.setenv("SIGAA_INSTITUTION", get().profile.key)
    assert Settings().institution == get().profile.key
    monkeypatch.setenv("SIGAA_INSTITUTION", "unknown")
    with pytest.raises(ValueError, match="unknown institution"):
        Settings()


@pytest.mark.parametrize("url", ["https://evil.example/", "http://sigaa.ufpb.br/",
                                  "https://sigaa.ufpb.br.evil.example/",
                                  "https://user@sigaa.ufpb.br/", "https://sigaa.ufpb.br:8443/"])
def test_url_allowlist(url):
    with pytest.raises(UnsafeUrlError):
        get().profile.validate_url(url)


def test_redirect_is_rejected_before_request_or_credential_send():
    sent = []
    def handler(request):
        sent.append(request)
        return httpx.Response(307, headers={"Location": "https://evil.example/"})
    raw = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    provider = get("ufpb")
    session = Session("test", secrets.token_urlsafe(), client=raw,
                      profile=provider.profile, navigator=provider.navigator)
    session._authenticated = True
    with session, pytest.raises(UnsafeUrlError):
        session.post(get().profile.logon_url, {"form:senha": secrets.token_urlsafe()})
    assert len(sent) == 1
    assert sent[0].url.host == "sigaa.ufpb.br"


def test_unsupported_feature_raises_before_navigation(other):
    from sigaa.client import SigaaClient
    with SigaaClient("test", secrets.token_urlsafe(), institution=other.key) as client:
        with pytest.raises(UnsupportedFeatureError, match="unsupported"):
            client.get_curriculum_status()


def test_client_hands_its_one_provider_to_the_session(other):
    from sigaa.client import SigaaClient
    with SigaaClient("test", secrets.token_urlsafe(), institution=other.key) as client:
        assert client.profile is other
        assert client._session.profile is other
        assert client._session.navigator is client.navigator
    assert not hasattr(SigaaClient, "profile")
    assert not hasattr(SigaaClient, "navigator")


@pytest.mark.parametrize("argv, capability", [
    (["curriculum"], Capability.CURRICULUM_JSON),
    (["cra"], Capability.DOCUMENTS),
    (["extensao"], Capability.EXTENSAO),
    (["sipac", "process", "23074.056437/2026-26"], Capability.SIPAC),
    (["sipac", "search", "--name", "x"], Capability.SIPAC),
    (["matricula"], Capability.MATRICULA),
    (["historico"], Capability.DOCUMENTS),
    (["declaracao-vinculo"], Capability.DOCUMENTS),
    (["atestado-matricula"], Capability.DOCUMENTS),
])
def test_each_gated_command_declares_its_capability(argv, capability):
    from sigaa.cli import _build_parser
    assert _build_parser().parse_args(argv).capability is capability


def test_unsupported_command_fails_before_running(other, monkeypatch, capsys):
    from sigaa import cli
    monkeypatch.setenv("SIGAA_INSTITUTION", other.key)
    monkeypatch.setattr(cli, "_cmd_academic_document", lambda args, settings: pytest.fail("ran"))
    assert cli.main(["atestado-matricula"]) == 1
    assert "unsupported feature documents" in capsys.readouterr().err


@pytest.mark.parametrize("command", [
    "classes", "grades", "deadlines", "ics", "news", "materials",
])
def test_unsupported_store_command_does_not_open_the_store(other, command, monkeypatch, tmp_path,
                                                           capsys):
    from sigaa.cli import main
    monkeypatch.setenv("SIGAA_INSTITUTION", other.key)
    monkeypatch.setenv("SIGAA_DB", str(tmp_path / "never-created.db"))
    assert main([command]) == 1
    assert "unsupported feature" in capsys.readouterr().err
    assert not (tmp_path / "never-created.db").exists()


def test_unsupported_mcp_tool_does_not_open_the_store(other, monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    from sigaa import mcp_server
    monkeypatch.setenv("SIGAA_INSTITUTION", other.key)
    monkeypatch.setenv("SIGAA_DB", str(tmp_path / "never-created.db"))
    for tool in (mcp_server.sigaa_list_grades, mcp_server.sigaa_list_news,
                 mcp_server.sigaa_export_ics):
        with pytest.raises(UnsupportedFeatureError):
            tool()
    assert not (tmp_path / "never-created.db").exists()


def test_blocked_http_hop_names_scheme_and_host_and_stages_as_network():
    from sigaa.errors import error_stage
    secret = secrets.token_urlsafe()

    def handler(request):
        return httpx.Response(302, headers={
            "Location": f"http://student:{secret}@sigaa.ufpb.br/sigaa/portal/?token={secret}"})

    provider = get("ufpb")
    raw = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    session = Session("test", secrets.token_urlsafe(), client=raw,
                      profile=provider.profile, navigator=provider.navigator)
    session._authenticated = True
    with session, pytest.raises(UnsafeUrlError) as caught:
        session.get(provider.profile.portal_entry_url)
    message = str(caught.value)
    assert "http://sigaa.ufpb.br" in message
    assert secret not in message and "student" not in message and "/portal" not in message
    assert (caught.value.scheme, caught.value.host) == ("http", "sigaa.ufpb.br")
    assert error_stage(caught.value) == "network"


def test_session_gives_the_navigator_the_final_response_url():
    seen = []

    class Recorder:
        def looks_logged_out(self, text, url=""):
            seen.append(url)
            return False

    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "https://sigaa.ufpb.br/final"})
        return httpx.Response(200, text="<html>page</html>")

    raw = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    session = Session("test", secrets.token_urlsafe(), client=raw,
                      profile=get("ufpb").profile, navigator=Recorder())
    session._authenticated = True
    with session:
        session.get("https://sigaa.ufpb.br/start")
    assert seen == ["https://sigaa.ufpb.br/final"]
