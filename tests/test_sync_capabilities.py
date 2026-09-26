import secrets
from dataclasses import replace

import pytest

from sigaa.config import Settings
from sigaa.institutions import Capability, get, registry
from sigaa.institutions.base import Institution
from sigaa.models import Student, Turma
from sigaa.services import sync as sync_module

PARTIAL = frozenset({Capability.PORTAL, Capability.NEWS, Capability.MATERIALS})
NEWS_PAGE = """<html><body><div class="headerBloco">Notícias</div>
<div class="hidden"></div><div>Não há notícias cadastradas</div></body></html>"""


def _client(calls):
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def get_student(self):
            return Student(matricula="000", name="ALUNO TESTE")

        def list_turmas(self):
            return [Turma(id_turma="1050315", name="SISTEMAS DISTRIBUÍDOS 1")]

        def enter_turma(self, turma):
            calls.append("enter_turma")
            return NEWS_PAGE

        def list_news(self, turma, turma_html=None):
            calls.append("news")
            return []

        def list_materials(self, turma, turma_html=None):
            calls.append("materials")
            return []

        def list_deadlines(self):
            calls.append("deadlines")
            return []

        def __getattr__(self, name):
            # Any feature the profile does not declare must never be called.
            raise AssertionError(f"sync called unsupported {name}")

    return Client


@pytest.fixture
def partial_institution(monkeypatch, tmp_path):
    provider = registry._PROVIDERS["ufg"]
    monkeypatch.setitem(registry._PROVIDERS, "ufg", Institution(
        replace(provider.profile, capabilities=PARTIAL), provider.navigator))
    monkeypatch.setenv("SIGAA_USER", "test-student")
    monkeypatch.setenv("SIGAA_SESSION", f"JSESSIONID={secrets.token_hex(16)}")
    monkeypatch.setattr("keyring.get_password", lambda *a: None)
    return Settings(institution="ufg", db_path=tmp_path / "t.db")


def test_sync_skips_only_what_the_institution_does_not_declare(partial_institution, monkeypatch):
    calls = []
    monkeypatch.setattr(sync_module, "SigaaClient", _client(calls))

    result = sync_module.sync(partial_institution)

    assert result.ok, result.error
    assert calls == ["enter_turma", "news", "materials", "deadlines"]
    assert result.unsupported == ["grades", "plan", "attendance", "participants"]


def test_full_institution_reports_nothing_unsupported():
    assert get("ufpb").profile.capabilities >= {
        Capability.GRADES, Capability.PLAN, Capability.ATTENDANCE, Capability.PARTICIPANTS}


def test_sync_json_names_the_skipped_features(partial_institution, monkeypatch, capsys):
    import json

    from sigaa import cli

    monkeypatch.setattr(sync_module, "SigaaClient", _client([]))
    monkeypatch.setattr(cli, "sync", sync_module.sync)
    monkeypatch.setenv("SIGAA_INSTITUTION", "ufg")
    cli.main(["--db", str(partial_institution.db_path), "sync", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["unsupported"] == ["grades", "plan", "attendance", "participants"]
