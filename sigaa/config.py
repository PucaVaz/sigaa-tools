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

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

KEYRING_ACTIVE_USERNAME = "__active_username__"
KEYRING_ACTIVE_INSTITUTION = "__active_institution__"
KEYRING_SETTINGS_SERVICE = "sigaa-tools"

# MCP tool surfaces. Local keeps every tool; hosted is the reduced surface for a
# shared deployment. Nothing is ever removed from the local/self-hosted build.
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
        """keyring first (Keychain), then the environment fallback.

        For a ``session`` institution the secret is a browser session's Cookie
        header and the fallback is SIGAA_SESSION, so a password is never sent
        as a cookie.
        """
        profile = get(self.institution).profile
        if self.username:
            try:
                import keyring

                secret = keyring.get_password(profile.keyring_service, self.username)
                if secret:
                    return secret
            except Exception:
                pass
        return os.environ.get(_secret_env(profile))

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
            profile = get(self.institution).profile
            secret = "session" if profile.auth_mode == "session" else "password"
            raise MissingCredentialsError(
                f"missing credentials: no {secret} for account {self.username!r} "
                f"in the keyring (run `sigaa login`; {_secret_env(profile)} is an "
                "optional fallback)"
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


def _secret_env(profile) -> str:
    return "SIGAA_SESSION" if profile.auth_mode == "session" else "SIGAA_PASS"
