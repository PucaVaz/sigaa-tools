"""Interactive first-run setup and generated config helpers."""

from __future__ import annotations

import getpass
import json
import platform
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from xml.sax.saxutils import escape

from . import config
from .client import SigaaClient
from .config import Settings
from .services.sync import sync


@dataclass(frozen=True)
class Institution:
    key: str
    label: str


@dataclass(frozen=True)
class LoginResult:
    name: str
    matricula: str
    password_stored: bool
    storage_message: str
    password: str = field(repr=False)


INSTITUTIONS = (Institution(key="ufpb", label="UFPB"),)


def select_institution(input_func: Callable[[str], str] = input) -> Institution:
    print("Institution:")
    for index, institution in enumerate(INSTITUTIONS, start=1):
        print(f"  {index}. {institution.label}")
    answer = input_func("Choose institution [1]: ").strip()
    if not answer:
        return INSTITUTIONS[0]
    try:
        selected = INSTITUTIONS[int(answer) - 1]
    except (ValueError, IndexError):
        print(f"Unknown choice {answer!r}; using {INSTITUTIONS[0].label}.")
        return INSTITUTIONS[0]
    return selected


def verify_and_store_login(username: str, password: str) -> LoginResult:
    with SigaaClient(username, password) as client:
        student = client.get_student()

    password_stored = True
    storage_message = "password stored in keyring"
    try:
        import keyring

        keyring.set_password(config.KEYRING_SERVICE, username, password)
        keyring.set_password(
            config.KEYRING_SERVICE,
            config.KEYRING_ACTIVE_USERNAME,
            username,
        )
    except Exception:
        password_stored = False
        storage_message = (
            "keyring unavailable; set SIGAA_USER and SIGAA_PASS in your shell"
        )

    return LoginResult(
        name=student.name,
        matricula=student.matricula,
        password_stored=password_stored,
        storage_message=storage_message,
        password=password,
    )


def prompt_login(settings: Settings, input_func: Callable[[str], str] = input) -> LoginResult:
    if not settings.username:
        settings.username = input_func("SIGAA username: ").strip()
    password = getpass.getpass("SIGAA password: ")
    result = verify_and_store_login(settings.username, password)
    print(f"login ok: {result.name} ({result.matricula}) - {result.storage_message}")
    return result


def resolve_script(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    suffix = ".exe" if sys.platform == "win32" and not name.endswith(".exe") else ""
    return str(Path(sys.executable).resolve().parent / f"{name}{suffix}")


def merge_mcp_config(path: Path, *, command: str, username: str) -> bool:
    path = path.expanduser()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {}
    servers = data.setdefault("mcpServers", {})
    desired = {"command": command, "env": {"SIGAA_USER": username}}
    changed = servers.get("sigaa") != desired
    servers["sigaa"] = desired
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def build_launchd_plist(*, sigaa_cmd: str, username: str) -> str:
    sigaa_cmd_xml = escape(sigaa_cmd)
    username_xml = escape(username)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"\n'
        '  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        "  <key>Label</key><string>ai.sigaa.sync</string>\n"
        "  <key>ProgramArguments</key>\n"
        "  <array>\n"
        f"    <string>{sigaa_cmd_xml}</string>\n"
        "    <string>sync</string>\n"
        "  </array>\n"
        "  <key>EnvironmentVariables</key>\n"
        f"  <dict><key>SIGAA_USER</key><string>{username_xml}</string></dict>\n"
        "  <key>StartInterval</key><integer>1800</integer>\n"
        "</dict></plist>\n"
    )


def build_cron_line(*, sigaa_cmd: str, username: str) -> str:
    return f"*/30 * * * * SIGAA_USER={username} {sigaa_cmd} sync"


def write_env_template(path: Path, *, username: str) -> None:
    path = path.expanduser()
    path.write_text(
        f"SIGAA_USER={username}\n"
        "SIGAA_PASS=replace-with-your-password\n",
        encoding="utf-8",
    )


def run_init(settings: Settings, input_func: Callable[[str], str] = input) -> int:
    print("sigaa init")
    institution = select_institution(input_func)
    print(f"Using {institution.label}.")

    login = _prompt_login_until_ok(settings, input_func)
    if login is None:
        return 1

    print("Running first sync...")
    result = sync(_sync_settings(settings, login))
    if not result.ok:
        print(f"sync failed: {result.error}", file=sys.stderr)
        return 1
    print(f"synced {result.turma_count} classes, {len(result.new_items)} news")

    username = settings.username or ""
    if not login.password_stored:
        print("Keyring is unavailable on this machine.")
        print("Set SIGAA_PASS in your environment before running network commands.")
        if _confirm("Write a .env template without the password? [y/N]: ", input_func):
            write_env_template(Path(".env"), username=username)
            print("wrote .env template; fill SIGAA_PASS yourself and keep it private")

    if _confirm("Wire MCP for Claude Code in .mcp.json? [y/N]: ", input_func):
        default_mcp = Path.cwd() / ".mcp.json"
        answer = input_func(f"MCP config path [{default_mcp}]: ").strip()
        mcp_path = Path(answer).expanduser() if answer else default_mcp
        command = resolve_script("sigaa-mcp")
        merge_mcp_config(mcp_path, command=command, username=username)
        print(f"wrote MCP server config to {mcp_path}")

    if _confirm("Install scheduled sync? [y/N]: ", input_func):
        _write_schedule(username=username)

    _print_cheatsheet()
    return 0


def _prompt_login_until_ok(settings: Settings, input_func: Callable[[str], str]) -> LoginResult | None:
    while True:
        try:
            return prompt_login(settings, input_func)
        except Exception as exc:
            print(f"login failed: {exc}", file=sys.stderr)
            if not _confirm("Try again? [y/N]: ", input_func):
                return None


def _confirm(prompt: str, input_func: Callable[[str], str]) -> bool:
    return input_func(prompt).strip().lower() in {"y", "yes", "s", "sim"}


def _sync_settings(settings: Settings, login: LoginResult) -> Settings:
    class InitSettings(Settings):
        def resolve_password(self) -> str | None:
            return login.password

    return InitSettings(db_path=settings.db_path, username=settings.username)


def _write_schedule(*, username: str) -> None:
    sigaa_cmd = resolve_script("sigaa")
    if platform.system() == "Darwin":
        plist_path = Path.home() / "Library" / "LaunchAgents" / "ai.sigaa.sync.plist"
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_text(build_launchd_plist(sigaa_cmd=sigaa_cmd, username=username), encoding="utf-8")
        print(f"wrote {plist_path}")
        print(f"load it with: launchctl load {plist_path}")
        return
    print("Add this cron entry:")
    print(build_cron_line(sigaa_cmd=sigaa_cmd, username=username))
    print("Password must come from keyring or SIGAA_PASS.")


def _print_cheatsheet() -> None:
    print("\nNext commands:")
    print("  sigaa whatsnew")
    print("  sigaa classes --schedule")
    print("  sigaa news --unread")
    print("  sigaa sync")
