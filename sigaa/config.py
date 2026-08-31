"""Configuration: endpoints, JSF constants, paths, and credential resolution.

The username resolves from ``SIGAA_USER`` first, then the active account saved
in keyring. Passwords resolve keyring-first, environment-second. Nothing is ever
written to disk in plaintext by this module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

HOST = "https://sigaa.ufpb.br"
BASE = f"{HOST}/sigaa"
LOGON_URL = f"{BASE}/logon.jsf"
# Entry point that 302-redirects to the fully rendered beta portal. A plain GET
# of the beta URL returns only a loading shell, so this slash-terminated classic
# URL is the reliable way in.
PORTAL_ENTRY_URL = f"{BASE}/portal/discente/"
# Form action used for in-portal JSF postbacks (entering a turma).
PORTAL_ACTION_URL = f"{BASE}/portais/discente/beta/discente.jsf"
# Curriculum-progress shell and the JSON request it issues after rendering.
CURRICULUM_ENTRY_URL = f"{BASE}/portal/discente/integralizacao/"
CURRICULUM_DATA_URL = f"{BASE}/portal/discente/integralizacao/dados/"
# Turma Virtual base; news bodies are fetched here.
AVA_URL = f"{BASE}/ava/index.jsf"

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

# Marker proving an authenticated page; absence means the session is dead.
AUTH_MARKER = "Sair do SIGAA"
# Substring of the URL we get bounced to when a session expires.
LOGIN_REDIRECT_MARKER = "logon.jsf"

KEYRING_SERVICE = "sigaa-ufpb"
KEYRING_ACTIVE_USERNAME = "__active_username__"

# UFPB class-time slots. Day digits: 2=Mon .. 7=Sat. Shift: M/T/N.
# NOTE: clock times below are an UNCONFIRMED default; confirm against a turma's
# "Plano de Curso" before trusting them for calendar/ICS export.
SLOT_TIMES_UNCONFIRMED = {
    "M": {1: "07:00", 2: "07:50", 3: "08:50", 4: "09:40", 5: "10:40", 6: "11:30"},
    "T": {1: "13:00", 2: "13:50", 3: "14:50", 4: "15:40", 5: "16:40", 6: "17:30"},
    "N": {1: "18:30", 2: "19:20", 3: "20:20", 4: "21:10"},
}


def default_db_path() -> Path:
    """Local SQLite path under the user config dir (override via SIGAA_DB)."""
    override = os.environ.get("SIGAA_DB")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "sigaa-tools" / "sigaa.db"


def default_download_dir() -> Path:
    """Private directory used by MCP download tools (override via SIGAA_DOWNLOAD_DIR)."""
    override = os.environ.get("SIGAA_DOWNLOAD_DIR")
    if override:
        return Path(override).expanduser()
    return default_db_path().parent / "downloads"


def default_username() -> str | None:
    """Return the environment override or the last account saved by login."""
    username = os.environ.get("SIGAA_USER")
    if username:
        return username
    try:
        import keyring

        saved = keyring.get_password(KEYRING_SERVICE, KEYRING_ACTIVE_USERNAME)
        return saved or None
    except Exception:
        return None


@dataclass
class Settings:
    db_path: Path = field(default_factory=default_db_path)
    username: str | None = field(default_factory=default_username)

    def resolve_password(self) -> str | None:
        """keyring first (Keychain), then SIGAA_PASS env var."""
        if self.username:
            try:
                import keyring

                secret = keyring.get_password(KEYRING_SERVICE, self.username)
                if secret:
                    return secret
            except Exception:
                pass
        return os.environ.get("SIGAA_PASS")

# Matrícula on-line (enrollment request) flow.
MATRICULA_INSTRUCOES_URL = f"{BASE}/graduacao/matricula/instrucoes.jsf"
MATRICULA_TURMAS_CURRICULO_URL = f"{BASE}/graduacao/matricula/turmas_curriculo.jsf"
