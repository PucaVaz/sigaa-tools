"""A hosted call acts for one tenant: its own store, its own SIGAA session."""

import secrets

import pytest

from sigaa import mcp_server
from sigaa.models import Turma
from sigaa.services.sync import SyncResult, sync
from sigaa.store.db import connect
from sigaa.store.repository import Repository
from sigaa.config import Settings
from sigaa.tenancy import Tenant, current_tenant, tenant_scope


def _tenant(tmp_path, name: str) -> Tenant:
    return Tenant(
        username=f"aluno.{name}",
        institution="ufpb",
        db_path=tmp_path / f"{name}.db",
        session_cookie=f"JSESSIONID={secrets.token_hex(16)}; sigscookie={secrets.token_hex(8)}",
    )


def _store_class(db_path, code: str) -> None:
    conn = connect(db_path)
    Repository(conn).upsert_turma(Turma(id_turma=code, name=f"CLASSE {code}", code=code))
    conn.close()


class CookieClient:
    """Stands in for SigaaClient; only the cookie-only constructor may be used."""

    opened: list[tuple[str, str, str]] = []

    def __init__(self, *args, **kwargs):
        raise AssertionError("a tenant call must not build a password client")

    @classmethod
    def from_session_cookie(cls, username, cookie_header, *, institution=None):
        cls.opened.append((username, cookie_header, institution))
        client = object.__new__(cls)
        client.closed = False
        return client

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True

    def get_cra(self):
        return 7.5


@pytest.fixture
def cookie_client(monkeypatch):
    CookieClient.opened = []
    monkeypatch.setattr(mcp_server, "SigaaClient", CookieClient)

    def server_credentials(*args, **kwargs):
        raise AssertionError("a tenant call must not read the server's keyring or env")

    monkeypatch.setattr(Settings, "resolve_password", server_credentials)
    return CookieClient


def test_scope_sets_and_restores_the_tenant(tmp_path):
    first, second = _tenant(tmp_path, "um"), _tenant(tmp_path, "dois")
    assert current_tenant() is None
    with tenant_scope(first):
        with tenant_scope(second):
            assert current_tenant() is second
        assert current_tenant() is first
    assert current_tenant() is None


def test_session_cookie_never_appears_in_repr(tmp_path):
    tenant = _tenant(tmp_path, "um")
    assert tenant.session_cookie not in repr(tenant)


def test_store_tools_read_only_the_tenants_own_store(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGAA_DB", str(tmp_path / "server.db"))
    _store_class(tmp_path / "server.db", "SERVER01")
    first, second = _tenant(tmp_path, "um"), _tenant(tmp_path, "dois")
    _store_class(first.db_path, "TEST0001")
    _store_class(second.db_path, "TEST0002")

    with tenant_scope(first):
        assert [c["code"] for c in mcp_server.sigaa_list_classes()] == ["TEST0001"]
    with tenant_scope(second):
        assert [c["code"] for c in mcp_server.sigaa_list_classes()] == ["TEST0002"]


def test_live_tools_use_the_tenants_session_cookie(tmp_path, cookie_client):
    tenant = _tenant(tmp_path, "um")

    with tenant_scope(tenant):
        result = mcp_server.sigaa_get_cra()

    assert result == {"value": 7.5, "source": "academic_transcript"}
    assert cookie_client.opened == [(tenant.username, tenant.session_cookie, "ufpb")]


def test_sync_runs_on_the_tenants_store_and_session(tmp_path, cookie_client, monkeypatch):
    tenant = _tenant(tmp_path, "um")
    seen = {}

    def fake_sync(settings, fetch_bodies=False, client=None):
        seen.update(settings=settings, client=client)
        return SyncResult()

    monkeypatch.setattr(mcp_server, "run_sync", fake_sync)
    with tenant_scope(tenant):
        assert mcp_server.sigaa_sync()["ok"]

    assert seen["settings"].db_path == tenant.db_path
    assert seen["settings"].username == tenant.username
    assert isinstance(seen["client"], CookieClient)
    assert cookie_client.opened == [(tenant.username, tenant.session_cookie, "ufpb")]


def test_sync_uses_the_given_client_and_closes_it(tmp_path):
    class FailingClient:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            FailingClient.closed = True

        def get_student(self):
            raise RuntimeError("scripted failure")

    settings = Settings(db_path=tmp_path / "store.db", username=None, institution="ufpb")
    result = sync(settings, client=FailingClient())

    assert not result.ok
    assert "scripted failure" in result.error
    assert FailingClient.closed
