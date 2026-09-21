"""Configuration: endpoints, JSF constants, paths, and credential resolution.

The username resolves from ``SIGAA_USER`` first, then the active account saved
in keyring. Passwords resolve keyring-first, environment-second. Nothing is ever
written to disk in plaintext by this module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .institutions import DEFAULT, get

_DEFAULT_PROFILE = get().profile
HOST = _DEFAULT_PROFILE.host
LOGON_URL = _DEFAULT_PROFILE.logon_url
PORTAL_ENTRY_URL = _DEFAULT_PROFILE.portal_entry_url
PORTAL_ACTION_URL = _DEFAULT_PROFILE.portal_action_url
CURRICULUM_ENTRY_URL = _DEFAULT_PROFILE.curriculum_entry_url
CURRICULUM_DATA_URL = _DEFAULT_PROFILE.curriculum_data_url
AVA_URL = _DEFAULT_PROFILE.ava_url
AUTH_MARKER = _DEFAULT_PROFILE.auth_marker
LOGIN_REDIRECT_MARKER = _DEFAULT_PROFILE.login_redirect_marker
KEYRING_SERVICE = _DEFAULT_PROFILE.keyring_service
SLOT_TIMES_UNCONFIRMED = _DEFAULT_PROFILE.slot_times
MATRICULA_INSTRUCOES_URL = _DEFAULT_PROFILE.matricula_instrucoes_url
MATRICULA_TURMAS_CURRICULO_URL = _DEFAULT_PROFILE.matricula_turmas_curriculo_url
BASE = f"{HOST}/sigaa"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
KEYRING_ACTIVE_USERNAME = "__active_username__"
KEYRING_ACTIVE_INSTITUTION = "__active_institution__"
KEYRING_SETTINGS_SERVICE = "sigaa-tools"
LOCAL_MODE = "local"
HOSTED_MODE = "hosted"
SERVER_MODES = (LOCAL_MODE, HOSTED_MODE)


def default_institution() -> str:
    key = os.environ.get("SIGAA_INSTITUTION")
    if not key:
        try:
            import keyring
            key = keyring.get_password(KEYRING_SETTINGS_SERVICE, KEYRING_ACTIVE_INSTITUTION)
        except Exception:
            pass
    return get(key or DEFAULT).profile.key

def default_db_path(institution: str | None = None) -> Path:
    """Local SQLite path under the user config dir (override via SIGAA_DB)."""
    override = os.environ.get("SIGAA_DB")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    key = get(institution or default_institution()).profile.key
    directory = base / "sigaa-tools"
    return directory / "sigaa.db" if key == DEFAULT else directory / key / "sigaa.db"


def default_download_dir() -> Path:
    """Private directory used by MCP download tools (override via SIGAA_DOWNLOAD_DIR)."""
    override = os.environ.get("SIGAA_DOWNLOAD_DIR")
    if override:
        return Path(override).expanduser()
    return default_db_path().parent / "downloads"


def default_mode() -> str:
    """Which tool surface the MCP server exposes (override via SIGAA_MODE).

    ``local`` is the default and exposes everything. ``hosted`` is for a shared,
    multi-tenant deployment and drops the tools that write to the server's disk.
    An unrecognized value raises rather than falling back, so a typo cannot start
    a hosted process with the full surface.
    """
    mode = os.environ.get("SIGAA_MODE", "").strip().lower()
    if not mode:
        return LOCAL_MODE
    if mode not in SERVER_MODES:
        valid = ", ".join(SERVER_MODES)
        raise ValueError(f"SIGAA_MODE must be one of: {valid} (got {mode!r})")
    return mode


def default_username(institution: str | None = None) -> str | None:
    """Return the environment override or the last account saved by login."""
    username = os.environ.get("SIGAA_USER")
    if username:
        return username
    try:
        import keyring

        service = get(institution or default_institution()).profile.keyring_service
        saved = keyring.get_password(service, KEYRING_ACTIVE_USERNAME)
        return saved or None
    except Exception:
        return None


@dataclass
class Settings:
    db_path: Path | None = None
    username: str | None = None
    institution: str = field(default_factory=default_institution)

    def __post_init__(self):
        get(self.institution)
        if self.db_path is None:
            self.db_path = default_db_path(self.institution)
        if self.username is None:
            self.username = default_username(self.institution)

    def resolve_password(self) -> str | None:
        """keyring first (Keychain), then SIGAA_PASS env var."""
        if self.username:
            try:
                import keyring

                secret = keyring.get_password(get(self.institution).profile.keyring_service, self.username)
                if secret:
                    return secret
            except Exception:
                pass
        return os.environ.get("SIGAA_PASS")

    def require_credentials(self) -> tuple[str, str]:
        """Return ``(username, password)`` or raise ``MissingCredentialsError``.

        The message names what is missing and how to fix it, never a secret.
        """
        from .errors import MissingCredentialsError

        if not self.username:
            raise MissingCredentialsError(
                "missing credentials: no SIGAA account configured "
                "(run `sigaa login`, or set SIGAA_USER)"
            )
        password = self.resolve_password()
        if not password:
            raise MissingCredentialsError(
                f"missing credentials: no password for account {self.username!r} "
                "in the keyring (run `sigaa login`; SIGAA_PASS is an optional fallback)"
            )
        return self.username, password

    def credentials_problem(self) -> str | None:
        """Why credentials cannot be resolved, or None when they can."""
        from .errors import MissingCredentialsError

        try:
            self.require_credentials()
        except MissingCredentialsError as exc:
            return str(exc)
        return None
