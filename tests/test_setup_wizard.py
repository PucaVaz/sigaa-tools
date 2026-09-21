import json
import sys
from pathlib import Path
from types import SimpleNamespace

from sigaa import setup_wizard
from sigaa.config import KEYRING_ACTIVE_USERNAME, Settings
from sigaa.institutions.ufpb import KEYRING_SERVICE
from sigaa.setup_wizard import (
    MCP_PACKAGE_SPEC,
    build_cron_line,
    build_launchd_plist,
    build_mcp_server,
    merge_mcp_config,
    resolve_script,
)


def test_login_persists_username_for_the_next_process(monkeypatch):
    credentials: dict[tuple[str, str], str] = {}
    events: list[str] = []

    class FakeClient:
        def __init__(self, username, password, **kwargs):
            assert (username, password) == ("alice", "test-password")

        def __enter__(self):
            events.append("verified")
            return self

        def __exit__(self, *exc):
            return None

        def get_student(self):
            return SimpleNamespace(name="ALICE", matricula="00000000000")

    def set_password(service, username, password):
        events.append(f"stored:{username}")
        credentials[(service, username)] = password

    fake_keyring = SimpleNamespace(
        set_password=set_password,
        get_password=lambda service, username: credentials.get((service, username)),
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    monkeypatch.setattr(setup_wizard, "SigaaClient", FakeClient)
    monkeypatch.delenv("SIGAA_USER", raising=False)
    monkeypatch.delenv("SIGAA_PASS", raising=False)

    setup_wizard.verify_and_store_login("alice", "test-password")
    fresh_settings = Settings()

    assert credentials[(KEYRING_SERVICE, KEYRING_ACTIVE_USERNAME)] == "alice"
    assert fresh_settings.username == "alice"
    assert fresh_settings.resolve_password() == "test-password"
    assert events == [
        "verified",
        "stored:alice",
        f"stored:{KEYRING_ACTIVE_USERNAME}",
        "stored:__active_institution__",
    ]


def test_build_mcp_server_prefers_uvx_when_uv_is_installed(monkeypatch):
    monkeypatch.setattr("sigaa.setup_wizard.shutil.which", lambda name: "/opt/bin/uv")

    assert build_mcp_server() == {
        "command": "uvx",
        "args": ["--from", MCP_PACKAGE_SPEC, "sigaa-mcp"],
    }


def test_build_mcp_server_falls_back_to_console_script_without_uv(monkeypatch):
    monkeypatch.setattr(
        "sigaa.setup_wizard.shutil.which",
        lambda name: None if name == "uv" else f"/opt/bin/{name}",
    )

    assert build_mcp_server() == {"command": "/opt/bin/sigaa-mcp"}


def test_build_mcp_server_sets_username_only_when_keyring_cannot_hold_it(monkeypatch):
    monkeypatch.setattr("sigaa.setup_wizard.shutil.which", lambda name: "/opt/bin/uv")

    assert build_mcp_server(username="alice") == {
        "command": "uvx",
        "args": ["--from", MCP_PACKAGE_SPEC, "sigaa-mcp"],
        "env": {"SIGAA_USER": "alice"},
    }


def test_merge_mcp_config_preserves_existing_servers(tmp_path):
    path = tmp_path / ".mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "other": {"command": "/bin/other"},
                    "sigaa": {"command": "/old/sigaa-mcp", "env": {"SIGAA_USER": "old"}},
                }
            }
        ),
        encoding="utf-8",
    )

    changed = merge_mcp_config(path, server={"command": "uvx", "args": ["sigaa-mcp"]})

    assert changed is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["other"] == {"command": "/bin/other"}
    assert data["mcpServers"]["sigaa"] == {"command": "uvx", "args": ["sigaa-mcp"]}


def test_merge_mcp_config_creates_parent_and_file(tmp_path):
    path = tmp_path / "project" / ".mcp.json"

    changed = merge_mcp_config(path, server={"command": "/opt/bin/sigaa-mcp"})

    assert changed is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"mcpServers": {"sigaa": {"command": "/opt/bin/sigaa-mcp"}}}


def test_merge_mcp_config_reports_unchanged_when_server_already_matches(tmp_path):
    path = tmp_path / ".mcp.json"
    server = {"command": "uvx", "args": ["sigaa-mcp"]}
    merge_mcp_config(path, server=server)

    assert merge_mcp_config(path, server=server) is False


def _unexpected_rebuild(key):
    raise AssertionError(f"settings rebuilt for {key}")


def _run_init_writing_mcp(monkeypatch, tmp_path, *, password_stored: bool) -> dict:
    """Drive run_init far enough to write .mcp.json, declining everything else."""
    login = setup_wizard.LoginResult(
        name="ALICE",
        matricula="00000000000",
        password_stored=password_stored,
        storage_message="stored",
        password="test-password",
    )
    monkeypatch.setattr(setup_wizard, "_prompt_login_until_ok", lambda *a, **k: login)
    monkeypatch.setattr(
        setup_wizard,
        "sync",
        lambda settings: SimpleNamespace(ok=True, turma_count=1, new_items=[], error=None),
    )
    monkeypatch.setattr("sigaa.setup_wizard.shutil.which", lambda name: "/opt/bin/uv")

    mcp_path = tmp_path / ".mcp.json"
    answers = ["1"]  # institution
    if not password_stored:
        answers.append("n")  # .env template, only offered when keyring failed
    answers += [
        "y",  # wire MCP
        str(mcp_path),  # config path
        "n",  # scheduled sync
    ]
    replies = iter(answers)
    settings = Settings(db_path=tmp_path / "sigaa.db", username="alice")

    assert setup_wizard.run_init(
        settings, lambda _prompt: next(replies), settings_for=_unexpected_rebuild
    ) == 0

    return json.loads(mcp_path.read_text(encoding="utf-8"))["mcpServers"]["sigaa"]


def test_run_init_writes_mcp_config_without_personal_data(monkeypatch, tmp_path):
    server = _run_init_writing_mcp(monkeypatch, tmp_path, password_stored=True)

    assert "SIGAA_USER" not in server["env"]
    assert server == {
        "command": "uvx",
        "args": ["--from", MCP_PACKAGE_SPEC, "sigaa-mcp"],
        "env": {"SIGAA_INSTITUTION": "ufpb"},
    }


def test_run_init_pins_username_when_keyring_is_unavailable(monkeypatch, tmp_path):
    server = _run_init_writing_mcp(monkeypatch, tmp_path, password_stored=False)

    assert server["env"] == {"SIGAA_USER": "alice", "SIGAA_INSTITUTION": "ufpb"}


def test_build_launchd_plist_uses_resolved_command_and_username():
    plist = build_launchd_plist(sigaa_cmd="/opt/bin/sigaa", username="alice")

    assert "<key>Label</key><string>ai.sigaa.sync</string>" in plist
    assert "<string>/opt/bin/sigaa</string>" in plist
    assert "<string>sync</string>" in plist
    assert "<dict><key>SIGAA_USER</key><string>alice</string></dict>" in plist
    assert "<key>StartInterval</key><integer>1800</integer>" in plist


def test_build_cron_line_uses_resolved_command_and_username():
    line = build_cron_line(sigaa_cmd="/opt/bin/sigaa", username="alice")

    assert line == "*/30 * * * * SIGAA_USER=alice /opt/bin/sigaa sync"


def test_schedules_pin_the_institution():
    plist = build_launchd_plist(sigaa_cmd="/opt/bin/sigaa", username="alice", institution="ufpb")
    line = build_cron_line(sigaa_cmd="/opt/bin/my sigaa", username="alice", institution="ufpb")

    assert "<key>SIGAA_INSTITUTION</key><string>ufpb</string></dict>" in plist
    assert line == "*/30 * * * * SIGAA_USER=alice SIGAA_INSTITUTION=ufpb '/opt/bin/my sigaa' sync"


def test_resolve_script_prefers_path_lookup(monkeypatch):
    monkeypatch.setattr("sigaa.setup_wizard.shutil.which", lambda name: f"/usr/local/bin/{name}")

    assert resolve_script("sigaa-mcp") == "/usr/local/bin/sigaa-mcp"


def test_resolve_script_falls_back_to_current_python_dir(monkeypatch):
    monkeypatch.setattr("sigaa.setup_wizard.shutil.which", lambda name: None)
    monkeypatch.setattr("sigaa.setup_wizard.sys.executable", "/opt/venv/bin/python")

    assert resolve_script("sigaa-mcp") == str(Path("/opt/venv/bin/sigaa-mcp"))


def test_init_offers_the_picker_only_without_an_explicit_institution(monkeypatch):
    from sigaa import cli

    calls = []
    monkeypatch.setattr(
        setup_wizard, "run_init", lambda settings, **kwargs: calls.append(kwargs) or 0
    )
    monkeypatch.delenv("SIGAA_INSTITUTION", raising=False)
    assert cli.main(["init"]) == 0
    assert cli.main(["init", "--institution", "ufpb"]) == 0
    monkeypatch.setenv("SIGAA_INSTITUTION", "ufpb")
    assert cli.main(["init"]) == 0
    assert [bool(kwargs.get("settings_for")) for kwargs in calls] == [True, False, False]


def test_picker_rebuilds_settings_for_another_institution(monkeypatch, tmp_path, capsys):
    from dataclasses import replace

    from sigaa.institutions import get, registry
    from sigaa.institutions.base import Institution

    ufpb = get("ufpb")
    other = replace(ufpb.profile, key="example", label="EXAMPLE")
    monkeypatch.setitem(registry._PROVIDERS, other.key, Institution(other, ufpb.navigator))
    rebuilt = Settings(db_path=tmp_path / "other.db", username="bob", institution=other.key)
    logins = []
    monkeypatch.setattr(
        setup_wizard, "_prompt_login_until_ok", lambda settings, _: logins.append(settings)
    )

    replies = iter(["2"])
    settings = Settings(db_path=tmp_path / "sigaa.db", username="alice", institution="ufpb")
    assert setup_wizard.run_init(
        settings, lambda _prompt: next(replies), settings_for=lambda key: rebuilt
    ) == 1
    output = capsys.readouterr().out
    assert "1. UFPB" in output and "2. EXAMPLE" in output
    assert "UFCG" not in output
    assert "Using EXAMPLE." in output
    assert logins == [rebuilt]


def test_provisional_institutions_are_selectable_only_explicitly(monkeypatch):
    from sigaa import cli
    from sigaa.institutions import get

    assert get("ufcg").profile.provisional and not get("ufpb").profile.provisional
    picked = []
    monkeypatch.setattr(
        setup_wizard, "run_init", lambda settings, **kwargs: picked.append(settings.institution) or 0
    )
    monkeypatch.delenv("SIGAA_INSTITUTION", raising=False)
    assert cli.main(["init", "--institution", "ufcg"]) == 0
    monkeypatch.setenv("SIGAA_INSTITUTION", "ufcg")
    assert cli.main(["init"]) == 0
    assert picked == ["ufcg", "ufcg"]

    replies = iter([""])
    offered = setup_wizard.select_institution(lambda _prompt: next(replies), default="ufcg")
    assert offered.key == "ufpb"
