"""Create an explicit, unsupported provider skeleton inside a source checkout."""
import re
from pathlib import Path
from urllib.parse import urlsplit

# The registry discovers every module that defines PROFILE and NAVIGATOR, so the
# generated file is the only edit. It inherits nothing from another institution:
# every navigation step raises until live captures establish how it works.
_TEMPLATE = '''"""{key} provider skeleton. Every step raises until live captures establish it."""
from ..errors import NavigationError
from .base import InstitutionProfile

HOST = {host!r}
# Confirm with `sigaa onboard login-probe` before implementing login.
LOGON_URL = HOST + "/sigaa/logon.jsf"

PROFILE = InstitutionProfile(
    key={key!r},
    label={label!r},
    host=HOST,
    logon_url=LOGON_URL,
    portal_entry_url="",
    portal_action_url="",
    ava_url="",
    curriculum_entry_url="",
    curriculum_data_url="",
    matricula_instrucoes_url="",
    matricula_turmas_curriculo_url="",
    auth_marker="",
    login_redirect_marker="",
    keyring_service={keyring_service!r},
    slot_times={{}},
    slot_minutes=50,
    menu_labels={{}},
    capabilities=frozenset(),
    provisional=True,
)


def _pending(step):
    return NavigationError(f"{key} {{step}} requires live onboarding captures")


class Navigator:
    def login(self, session):
        raise _pending("login")

    def looks_logged_out(self, text, url=""):
        raise _pending("session check")

    def portal_menu_post(self, session, portal, label):
        raise _pending("portal navigation")

    def enter_turma(self, session, portal, turma):
        raise _pending("class navigation")

    def turma_menu_post(self, session, principal, label):
        raise _pending("class menu")

    def open_event(self, session, portal, event_id):
        raise _pending("event navigation")


NAVIGATOR = Navigator()
'''
_RESERVED = {"base", "registry"}


def scaffold(root: Path, key: str, host: str):
    if (not re.fullmatch(r"[a-z][a-z0-9_]{1,31}", key)
            or key in _RESERVED or key.startswith("auth_")):
        raise ValueError("institution key must be a short Python module name")
    url = urlsplit(host)
    if (url.scheme != "https" or not url.hostname or url.path not in ("", "/")
            or url.query or url.fragment or url.username or url.password
            or url.port not in (None, 443)):
        raise ValueError("host must be a plain HTTPS origin")
    target = root / "sigaa/institutions" / f"{key}.py"
    if target.exists():
        raise ValueError("institution already exists")
    target.write_text(_TEMPLATE.format(
        key=key,
        label=key.upper(),
        host=host.rstrip("/"),
        keyring_service=f"sigaa-{key}",
    ))
    fixtures = root / "tests/fixtures" / key
    fixtures.mkdir(parents=True, exist_ok=True)
    (fixtures / ".gitkeep").touch()
    return target
