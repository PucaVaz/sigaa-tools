"""Typed failures, each tagged with the pipeline stage that produced it.

The stage is what automation keys on: a watcher must be able to tell "could not
log in" from "logged in, page changed shape" from "nothing new", without
parsing free-form messages.
"""

from __future__ import annotations

import httpx

STAGE_AUTH = "auth"
STAGE_NETWORK = "network"
STAGE_PARSE = "parse"
STAGE_SYNC = "sync"


class SigaaError(RuntimeError):
    stage = STAGE_SYNC


class MissingCredentialsError(SigaaError):
    """No account or no password could be resolved. Raised before any request."""

    stage = STAGE_AUTH


class LoginRejectedError(SigaaError, ValueError):
    """SIGAA answered the login form but the portal is not authenticated.

    Also a ``ValueError`` so callers written against the old bare
    ``ValueError("login failed ...")`` keep working.
    """

    stage = STAGE_AUTH


class ParseError(SigaaError):
    """A page SIGAA returned no longer matches the markup the parser expects."""

    stage = STAGE_PARSE


def error_stage(exc: BaseException) -> str:
    if isinstance(exc, SigaaError):
        return exc.stage
    if isinstance(exc, (httpx.HTTPError, OSError)):
        return STAGE_NETWORK
    return STAGE_SYNC


class UnsupportedFeatureError(SigaaError, ValueError):
    """The selected institution does not implement this feature."""


class UnsafeUrlError(SigaaError, ValueError):
    """A request or redirect left the selected institution's HTTPS origin."""


class UnrecognizedPageError(ParseError):
    """Unknown markup; diagnostics describe structure, never student values."""
    def __init__(self, feature, fingerprint):
        self.feature = feature
        self.fingerprint = fingerprint
        super().__init__(f"unrecognized {feature} page")


class NavigationError(ParseError, ValueError):
    """A required navigation target is absent from the current render."""
