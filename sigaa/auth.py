"""Compatibility entry point for the default institution's login."""
from .institutions.ufpb import perform_login

__all__ = ["perform_login"]
