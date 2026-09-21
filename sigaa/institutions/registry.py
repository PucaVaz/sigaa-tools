"""In-tree institution providers. Unknown keys never fall back silently."""
from .base import Institution
from .ufpb import PROFILE, UfpbNavigator
from .ufcg import PROFILE as UFCG_PROFILE, NAVIGATOR as UFCG_NAVIGATOR

DEFAULT = PROFILE.key
_PROVIDERS = {DEFAULT: Institution(PROFILE, UfpbNavigator()),
              UFCG_PROFILE.key: Institution(UFCG_PROFILE, UFCG_NAVIGATOR)}


def get(key: str | None = None) -> Institution:
    try:
        return _PROVIDERS[key or DEFAULT]
    except KeyError:
        raise ValueError(f"unknown institution: {key!r}") from None


def all() -> tuple[Institution, ...]:
    return tuple(_PROVIDERS.values())
