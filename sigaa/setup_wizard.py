"""Interactive first-run setup and generated config helpers."""

from __future__ import annotations

import getpass
import json
import platform
import shlex
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from xml.sax.saxutils import escape

from . import config
from .client import SigaaClient
from .config import Settings
from .institutions import InstitutionProfile, all, get
from .services.sync import sync


@dataclass(frozen=True)
class LoginResult:
    name: str
    matricula: str
    password_stored: bool
    storage_message: str
    password: str = field(repr=False)


def select_institution(
    input_func: Callable[[str], str] = input, *, default: str | None = None
) -> InstitutionProfile:
    institutions = tuple(
        provider.profile for provider in all() if not provider.profile.provisional
    )
    fallback = next(
        (index for index, profile in enumerate(institutions) if profile.key == default), 0
    )
    print("Institution:")
    for index, institution in enumerate(institutions, start=1):
        print(f"  {index}. {institution.label}")
    answer = input_func(f"Choose institution [{fallback + 1}]: ").strip()
    if not answer:
        return institutions[fallback]
    try:
        selected = institutions[int(answer) - 1]
    except (ValueError, IndexError):
        print(f"Unknown choice {answer!r}; using {institutions[fallback].label}.")
        return institutions[fallback]
    return selected


def verify_and_store_login(
    username: str, password: str, *, institution: str | None = None
) -> LoginResult:
    try:
        with SigaaClient(username, password, institution=institution) as client:
            student = client.get_student()
    except Exception as e:
        error_msg = str(e).lower()
        if "unauthorized" in error_msg or "401" in error_msg or "login" in error_msg:
            raise ValueError(
                "incorrect username or password. check credentials and try again."
            ) from e
        elif "connection" in error_msg or "network" in error_msg or "timeout" in error_msg:
            raise ValueError(
                "network error. check your internet connection and try again."
            ) from e
        else:
            raise ValueError(f"login failed: {e}") from e

    password_stored = True
    storage_message = "password stored in keyring"
    try:
        import keyring

        profile = get(institution).profile
        keyring.set_password(profile.keyring_service, username, password)
        keyring.set_password(
            profile.keyring_service,
            config.KEYRING_ACTIVE_USERNAME,
            username,
        )
        keyring.set_password(
            config.KEYRING_SETTINGS_SERVICE,
            config.KEYRING_ACTIVE_INSTITUTION,
            profile.key,
        )
    except Exception:
        password_stored = False
        secret_env = "SIGAA_SESSION" if get(institution).profile.auth_mode == "session" else "SIGAA_PASS"
        storage_message = (
            f"keyring unavailable; set SIGAA_USER and {secret_env} in your shell"
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
    if get(settings.institution).profile.auth_mode == "session":
        # SSO with reCAPTCHA: the student logs in with a browser; we store the
        # SIGAA session's Cookie header in place of a password.
        print("Log in to SIGAA in your browser, then copy the request's Cookie header")
        print("(DevTools > Network > any SIGAA page > Request Headers > Cookie).")
        password = getpass.getpass("SIGAA Cookie header: ").strip()
    else:
        password = getpass.getpass("SIGAA password: ")
    result = verify_and_store_login(settings.username, password, institution=settings.institution)
    print(f"login ok: {result.name} ({result.matricula}) - {result.storage_message}")
    return result


def resolve_script(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    suffix = ".exe" if sys.platform == "win32" and not name.endswith(".exe") else ""
    return str(Path(sys.executable).resolve().parent / f"{name}{suffix}")


# Source uvx resolves the server from. Switch to "sigaa-tools[mcp]" once the
# package is published to PyPI; the generated config keeps working either way.
MCP_PACKAGE_SPEC = "sigaa-tools[mcp] @ git+https://github.com/PucaVaz/sigaa-tools"


def build_mcp_server(
    *, username: str | None = None, institution: str | None = None
) -> dict[str, object]:
    """Return an MCP server entry, preferring a portable ``uvx`` invocation.

    Pass ``username`` only when keyring cannot store the active account; the
    server otherwise reads it back itself, keeping the config free of personal
    data so it can be committed alongside the project.
    """
    if shutil.which("uv"):
        server: dict[str, object] = {
            "command": "uvx",
            "args": ["--from", MCP_PACKAGE_SPEC, "sigaa-mcp"],
        }
    else:
        server = {"command": resolve_script("sigaa-mcp")}
    env = {}
    if username:
        env["SIGAA_USER"] = username
    if institution:
        env["SIGAA_INSTITUTION"] = institution
    if env:
        server["env"] = env
    return server


def merge_mcp_config(path: Path, *, server: dict[str, object]) -> bool:
    path = path.expanduser()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {}
    servers = data.setdefault("mcpServers", {})
    changed = servers.get("sigaa") != server
    servers["sigaa"] = server
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def build_launchd_plist(*, sigaa_cmd: str, username: str, institution: str | None = None) -> str:
    sigaa_cmd_xml = escape(sigaa_cmd)
    username_xml = escape(username)
    institution_xml = (
        f"<key>SIGAA_INSTITUTION</key><string>{escape(institution)}</string>"
        if institution else ""
    )
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
        f"  <dict><key>SIGAA_USER</key><string>{username_xml}</string>{institution_xml}</dict>\n"
        "  <key>StartInterval</key><integer>1800</integer>\n"
        "</dict></plist>\n"
    )


def build_cron_line(*, sigaa_cmd: str, username: str, institution: str | None = None) -> str:
    selection = f" SIGAA_INSTITUTION={shlex.quote(institution)}" if institution else ""
    user = shlex.quote(username)
    return f"*/30 * * * * SIGAA_USER={user}{selection} {shlex.quote(sigaa_cmd)} sync"


def write_env_template(path: Path, *, username: str) -> None:
    path = path.expanduser()
    path.write_text(
        f"SIGAA_USER={username}\n"
        "SIGAA_PASS=replace-with-your-password\n",
        encoding="utf-8",
    )


def run_init(
    settings: Settings,
    input_func: Callable[[str], str] = input,
    *,
    settings_for: Callable[[str], Settings] | None = None,
) -> int:
    """Run the wizard. ``settings_for`` enables the institution picker; pass it
    only when the institution was not chosen explicitly."""
    print("sigaa init")
    if settings_for is None:
        institution = get(settings.institution).profile
    else:
        institution = select_institution(input_func, default=settings.institution)
        if institution.key != settings.institution:
            settings = settings_for(institution.key)
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
        # The active account comes back from keyring, so only pin it in the
        # config when keyring could not store it.
        server = build_mcp_server(
            username=None if login.password_stored else username,
            institution=settings.institution,
        )
        merge_mcp_config(mcp_path, server=server)
        print(f"wrote MCP server config to {mcp_path}")

    if _confirm("Install scheduled sync? [y/N]: ", input_func):
        _write_schedule(username=username, institution=settings.institution)

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

    return InitSettings(
        db_path=settings.db_path,
        username=settings.username,
        institution=settings.institution,
    )


def _write_schedule(*, username: str, institution: str | None = None) -> None:
    sigaa_cmd = resolve_script("sigaa")
    if platform.system() == "Darwin":
        plist_path = Path.home() / "Library" / "LaunchAgents" / "ai.sigaa.sync.plist"
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist = build_launchd_plist(sigaa_cmd=sigaa_cmd, username=username, institution=institution)
        plist_path.write_text(plist, encoding="utf-8")
        print(f"wrote {plist_path}")
        print(f"load it with: launchctl load {plist_path}")
        return
    print("Add this cron entry:")
    print(build_cron_line(sigaa_cmd=sigaa_cmd, username=username, institution=institution))
    print("Password must come from keyring or SIGAA_PASS.")


def _print_cheatsheet() -> None:
    print("\nNext commands:")
    print("  sigaa whatsnew")
    print("  sigaa classes --schedule")
    print("  sigaa news --unread")
    print("  sigaa sync")
