"""In-tree institution providers. Unknown keys never fall back silently.

Every module in this package that defines ``PROFILE`` and ``NAVIGATOR`` is a
provider, so adding an institution needs no edit here. ``base``, ``registry``
and the shared ``auth_*`` helpers are not providers.
"""
import importlib
import pkgutil
import sys

from .base import Institution

DEFAULT = "ufpb"
_NOT_PROVIDERS = {"base", "registry"}


def _discover() -> dict[str, Institution]:
    package = sys.modules[__package__]
    providers: dict[str, Institution] = {}
    for module_info in sorted(pkgutil.iter_modules(package.__path__), key=lambda m: m.name):
        name = module_info.name
        if name in _NOT_PROVIDERS or name.startswith("auth_") or module_info.ispkg:
            continue
        module = importlib.import_module(f"{__package__}.{name}")
        if not (hasattr(module, "PROFILE") and hasattr(module, "NAVIGATOR")):
            continue
        key = module.PROFILE.key
        if key in providers:
            raise ValueError(f"institution {key!r} is defined twice")
        providers[key] = Institution(module.PROFILE, module.NAVIGATOR)
    if DEFAULT not in providers:
        raise ValueError(f"default institution {DEFAULT!r} is not registered")
    # The default comes first wherever providers are listed.
    return {DEFAULT: providers.pop(DEFAULT), **providers}


_PROVIDERS = _discover()


def get(key: str | None = None) -> Institution:
    try:
        return _PROVIDERS[key or DEFAULT]
    except KeyError:
        raise ValueError(f"unknown institution: {key!r}") from None


def all() -> tuple[Institution, ...]:
    return tuple(_PROVIDERS.values())
