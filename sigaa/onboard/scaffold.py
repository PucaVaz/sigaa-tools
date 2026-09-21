"""Create an explicit, unsupported provider skeleton inside a source checkout."""
from pathlib import Path
import re
from urllib.parse import urlsplit


def scaffold(root: Path, key: str, host: str):
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,31}", key):
        raise ValueError("institution key must be a short Python module name")
    url = urlsplit(host)
    if (url.scheme != "https" or not url.hostname or url.path not in ("", "/")
            or url.query or url.fragment or url.username or url.password or url.port not in (None, 443)):
        raise ValueError("host must be a plain HTTPS origin")
    host = host.rstrip("/")
    target = root / "sigaa/institutions" / f"{key}.py"
    registry = root / "sigaa/institutions/registry.py"
    if target.exists():
        raise ValueError("institution already exists")
    registry_text = registry.read_text()
    source = f'''"""{key} provider skeleton. Navigation must be implemented before login."""
from dataclasses import replace
from .ufpb import PROFILE as TEMPLATE, UfpbNavigator

PROFILE = replace(
    TEMPLATE, key={key!r}, label={key.upper()!r}, host={host!r}, keyring_service={('sigaa-' + key)!r},
    **{{field: getattr(TEMPLATE, field).replace(TEMPLATE.host, {host!r})
       for field in TEMPLATE.__dataclass_fields__ if field.endswith("_url")}},
    capabilities=frozenset(),
)


class Navigator(UfpbNavigator):
    def login(self, session):
        raise NotImplementedError("Implement and test this institution's login and navigation")


NAVIGATOR = Navigator(PROFILE)
'''
    target.write_text(source)
    registry_text += (f"\nfrom .{key} import PROFILE as _{key}_profile, NAVIGATOR as _{key}_navigator  # noqa: E402\n"
                      f"_PROVIDERS[{key!r}] = Institution(_{key}_profile, _{key}_navigator)\n")
    registry.write_text(registry_text)
    fixtures = root / "tests/fixtures" / key
    fixtures.mkdir(parents=True, exist_ok=True)
    (fixtures / ".gitkeep").touch()
    return target
