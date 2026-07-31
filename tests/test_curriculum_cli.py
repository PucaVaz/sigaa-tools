from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

from sigaa import cli as cli_module
from sigaa.parsers.curriculum import parse_curriculum
from sigaa.parsers.transcript import CraUnavailableError


FIXTURE = Path(__file__).parent / "fixtures" / "curriculum.json"


def _curriculum():
    return replace(
        parse_curriculum(FIXTURE.read_text(encoding="utf-8")),
        cra=Decimal("8.42"),
        cra_source="academic_transcript",
    )


def _settings():
    return SimpleNamespace(
        username="configured-user",
        resolve_password=lambda: "test-password",
    )


def test_cli_registers_curriculum_and_cra_commands():
    parser = cli_module._build_parser()

    curriculum = parser.parse_args(["curriculum"])
    cra = parser.parse_args(["cra"])

    assert curriculum.status == "current"
    assert curriculum.required_only is False
    assert curriculum.requirements is False
    assert curriculum.no_cra is False
    assert cra.json is False


def test_curriculum_json_uses_shared_filtered_contract(monkeypatch, capsys):
    class FakeClient:
        def __init__(self, username, password):
            assert (username, password) == ("configured-user", "test-password")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def get_curriculum_status(self, *, include_cra):
            assert include_cra is True
            return _curriculum()

    monkeypatch.setattr(cli_module, "SigaaClient", FakeClient)
    args = cli_module._build_parser().parse_args(
        ["curriculum", "--status", "pending", "--requirements", "--json"]
    )

    assert cli_module._cmd_curriculum(args, _settings()) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["cra"] == {"value": 8.42, "source": "academic_transcript"}
    assert {component["code"] for component in data["components"]} == {
        "SYN0003",
        "SYN0004",
    }
    assert all("prerequisite" in component for component in data["components"])
    assert "idDiscente" not in json.dumps(data)


def test_curriculum_human_view_is_compact_and_explains_optional_choices(
    monkeypatch,
    capsys,
):
    class FakeClient:
        def __init__(self, username, password):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def get_curriculum_status(self, *, include_cra):
            return _curriculum()

    monkeypatch.setattr(cli_module, "SigaaClient", FakeClient)
    args = cli_module._build_parser().parse_args(["curriculum"])

    assert cli_module._cmd_curriculum(args, _settings()) == 0
    output = capsys.readouterr().out

    assert "CRA: 8.42" in output
    assert "Curriculum:" not in output
    assert "Enrolled (1)" in output
    assert "Pending (1)" in output
    assert "SYN0002" in output
    assert "SYN0003" in output
    assert "SYN0004" not in output
    assert "not all individually required" in output


def test_cra_command_returns_unavailable_as_valid_state(monkeypatch, capsys):
    class FakeClient:
        def __init__(self, username, password):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def get_cra(self):
            raise CraUnavailableError("CRA is not available in transcript")

    monkeypatch.setattr(cli_module, "SigaaClient", FakeClient)
    args = cli_module._build_parser().parse_args(["cra", "--json"])

    assert cli_module._cmd_cra(args, _settings()) == 0
    assert json.loads(capsys.readouterr().out) == {
        "value": None,
        "source": "unavailable",
    }


def test_curriculum_requires_credentials(capsys):
    settings = SimpleNamespace(username=None, resolve_password=lambda: None)
    args = cli_module._build_parser().parse_args(["curriculum"])

    assert cli_module._cmd_curriculum(args, settings) == 1
    assert "missing credentials" in capsys.readouterr().err
