import json
from pathlib import Path
from types import SimpleNamespace

from sigaa import cli as cli_module
from sigaa.parsers.sipac import parse_public_process


FIXTURE = Path(__file__).parent / "fixtures" / "sipac_process.html"


def _process():
    return parse_public_process(
        FIXTURE.read_text(encoding="utf-8"),
        public_url="https://sipac.ufpb.br/public/jsp/processos/processo_detalhado.jsf?id=123",
    )


def test_cli_registers_nested_public_process_command():
    args = cli_module._build_parser().parse_args(
        ["sipac", "process", "23074.000001/2099-10"]
    )

    assert args.number == "23074.000001/2099-10"
    assert args.json is False


def test_cli_public_process_json_does_not_resolve_credentials(monkeypatch, capsys):
    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def get_public_process(self, number):
            assert number == "23074.000001/2099-10"
            return _process()

    monkeypatch.setattr(cli_module, "SipacClient", FakeClient)
    settings = SimpleNamespace(resolve_password=lambda: (_ for _ in ()).throw(AssertionError))
    args = cli_module._build_parser().parse_args(
        ["sipac", "process", "23074.000001/2099-10", "--json"]
    )

    assert cli_module._cmd_sipac_process(args, settings) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["number"] == "23074.000001/2099-10"
    assert data["documents"][0]["download_url"].startswith("https://sipac.ufpb.br/")


def test_cli_main_public_process_does_not_construct_settings(monkeypatch, capsys):
    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def get_public_process(self, number):
            return _process()

    monkeypatch.setattr(cli_module, "SipacClient", FakeClient)
    monkeypatch.setattr(
        cli_module,
        "Settings",
        lambda: (_ for _ in ()).throw(AssertionError("settings must stay untouched")),
    )

    assert cli_module.main(["sipac", "process", "23074.000001/2099-10"]) == 0
    assert "PROCESSO SINTÉTICO PARA TESTES" in capsys.readouterr().out
