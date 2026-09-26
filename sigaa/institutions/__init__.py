"""Institution profiles and navigation providers."""
from .base import Capability, InstitutionProfile, MenuLabel, Navigator
from .registry import DEFAULT, all, get

__all__ = ["Capability", "InstitutionProfile", "MenuLabel", "Navigator", "DEFAULT", "all", "get"]
