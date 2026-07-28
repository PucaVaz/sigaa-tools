import json
import sys
from pathlib import Path
from types import SimpleNamespace

from sigaa import setup_wizard
from sigaa.config import KEYRING_ACTIVE_USERNAME, KEYRING_SERVICE, Settings
from sigaa.setup_wizard import (
    build_cron_line,
    build_launchd_plist,
    merge_mcp_config,
    resolve_script,
)


def test_login_persists_username_for_the_next_process(monkeypatch):
    credentials: dict[tuple[str, str], str] = {}
    events: list[str] = []

    class FakeClient:
        def __init__(self, username, password):
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
    ]


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

    changed = merge_mcp_config(path, command="/opt/bin/sigaa-mcp", username="alice")

    assert changed is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["other"] == {"command": "/bin/other"}
    assert data["mcpServers"]["sigaa"] == {
        "command": "/opt/bin/sigaa-mcp",
        "env": {"SIGAA_USER": "alice"},
    }


def test_merge_mcp_config_creates_parent_and_file(tmp_path):
    path = tmp_path / "project" / ".mcp.json"

    changed = merge_mcp_config(path, command="/opt/bin/sigaa-mcp", username="alice")

    assert changed is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {
        "mcpServers": {
            "sigaa": {
                "command": "/opt/bin/sigaa-mcp",
                "env": {"SIGAA_USER": "alice"},
            }
        }
    }


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


def test_resolve_script_prefers_path_lookup(monkeypatch):
    monkeypatch.setattr("sigaa.setup_wizard.shutil.which", lambda name: f"/usr/local/bin/{name}")

    assert resolve_script("sigaa-mcp") == "/usr/local/bin/sigaa-mcp"


def test_resolve_script_falls_back_to_current_python_dir(monkeypatch):
    monkeypatch.setattr("sigaa.setup_wizard.shutil.which", lambda name: None)
    monkeypatch.setattr("sigaa.setup_wizard.sys.executable", "/opt/venv/bin/python")

    assert resolve_script("sigaa-mcp") == str(Path("/opt/venv/bin/sigaa-mcp"))
