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
    """A request or redirect left the selected institution's HTTPS origin.

    Staged as ``network``: SIGAA answered with a hop the allowlist refuses, for
    example an ``http://`` redirect. The message names only the scheme, host and
    port, never a path, query or embedded credentials.
    """

    stage = STAGE_NETWORK

    def __init__(self, scheme: str, host: str | None, port: int | None, reason: str):
        self.scheme = scheme
        self.host = host
        self.port = port
        origin = f"{scheme}://{host or ''}" + (f":{port}" if port else "")
        super().__init__(f"request blocked: {origin} {reason}")


class UnrecognizedPageError(ParseError):
    """Unknown markup; diagnostics describe structure, never student values."""

    def __init__(self, feature, fingerprint):
        self.feature = feature
        self.fingerprint = fingerprint
        super().__init__(f"unrecognized {feature} page")


class NavigationError(ParseError, ValueError):
    """A required navigation target is absent from the current render."""


class SsoRedirectError(LoginRejectedError):
    """SIGAA bounced the request to its single sign-on host: the session is gone.

    The redirect is never followed, so no request reaches the SSO. Staged as
    ``auth`` (a ``LoginRejectedError``): the fix is a new login, not a retry.
    """

    def __init__(self, host: str | None):
        self.host = host
        super().__init__(f"session expired: SIGAA redirected to single sign-on at {host}")
