from dataclasses import replace
import secrets

import httpx
import pytest

from sigaa.config import Settings, default_db_path
from sigaa.errors import UnsafeUrlError, UnsupportedFeatureError
from sigaa.http import Session
from sigaa.institutions import get
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
    session = Session("test", secrets.token_urlsafe(), client=raw)
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
