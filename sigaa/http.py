"""HTTP session: cookie jar, ViewState handling, transparent re-login + retry.

SIGAA auth is JSF-stateless: a cookie jar (JSESSIONID + sigscookie) plus a
``javax.faces.ViewState`` replayed on every postback. When a session expires the
server bounces requests back to ``logon.jsf``; this layer detects that, logs in
again, and retries the call once.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from urllib.parse import urlencode

import httpx

from . import config
from .errors import STAGE_AUTH, SigaaError
from .institutions import InstitutionProfile, Navigator

FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"

# A connection that was never established sent nothing, so any request may retry it.
CONNECT_RETRIES = 2
# Resends of a read-only request whose response was lost (timeout, dropped
# connection). Bounded: with the 30 s timeout a dead server costs one request
# at most (MAX_RESENDS + 1) timeouts before the run fails as ``network``.
MAX_RESENDS = 2
RESEND_BACKOFF_SECONDS = 1.0

_VIEWSTATE_RE = re.compile(
    r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"'
)


def extract_viewstate(html: str, default: str = "j_id1") -> str:
    match = _VIEWSTATE_RE.search(html)
    return match.group(1) if match else default


def encode_form(data: dict[str, str | list[str]], charset: str) -> bytes:
    """URL-encode a form in ``charset``, refusing text it cannot represent."""
    try:
        return urlencode(data, doseq=True, encoding=charset, errors="strict").encode("ascii")
    except UnicodeEncodeError as exc:
        unsupported = sorted(set(exc.object[exc.start : exc.end]))
        raise ValueError(
            f"text contains characters SIGAA cannot store ({charset}): "
            + " ".join(repr(char) for char in unsupported)
        ) from None


class AuthError(SigaaError):
    stage = STAGE_AUTH


class Session:
    """Stateful SIGAA session. Construct with credentials, then ``login()``."""

    def __init__(
        self,
        username: str,
        password: str,
        client: httpx.Client | None = None,
        *,
        timeout: float | httpx.Timeout = 30.0,
        profile: InstitutionProfile,
        navigator: Navigator,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.profile = profile
        self.navigator = navigator
        self._username = username
        self._password = password
        self._sleep = sleep
        self._client = client or httpx.Client(
            headers={"User-Agent": config.USER_AGENT},
            follow_redirects=True,
            timeout=timeout,
            transport=httpx.HTTPTransport(retries=CONNECT_RETRIES),
            event_hooks={"request": [self._validate_request]},
        )
        self._authenticated = False
        if client is not None:
            self._client.event_hooks.setdefault("request", []).append(self._validate_request)

    def _validate_request(self, request: httpx.Request) -> None:
        self.profile.validate_url(str(request.url))

    def login(self) -> str:
        """Authenticate and return the rendered portal HTML."""
        portal_html = self.navigator.login(self)
        self._authenticated = True
        return portal_html

    def get(self, url: str) -> str:
        return self._request("GET", url, resendable=True)

    def post_navigation(self, url: str, data: dict[str, str | list[str]]) -> str:
        """POST a JSF postback that only navigates (open a turma, click a menu).

        Unlike ``post``, it is resent when the response is lost: SIGAA answers a
        repeated navigation postback with the same page. Never use it for a form
        that changes account state.
        """
        return self._request("POST", url, data=data, resendable=True)

    def post(
        self, url: str, data: dict[str, str | list[str]], *, charset: str | None = None
    ) -> str:
        """POST form data. A list value repeats the key (httpx encodes it so;
        tuples inside the mapping break h11).

        httpx always encodes a form as UTF-8. Pass ``charset`` when the payload
        carries free text and the institution decodes forms in another charset,
        otherwise every accented character is stored as mojibake. Text the
        charset cannot represent raises ``ValueError`` before any request.
        """
        if charset is None:
            return self._request("POST", url, data=data)
        return self._request("POST", url, content=encode_form(data, charset))

    def post_bytes(self, url: str, data: dict[str, str]) -> bytes:
        """POST expecting a binary download (e.g. a PDF). Re-logins if bounced."""
        content, _, _ = self.post_download(url, data)
        return content

    def post_download(
        self,
        url: str,
        data: dict[str, str],
        *,
        retry_on_auth: bool = True,
    ) -> tuple[bytes, str | None, str | None]:
        """POST a binary download; return (content, content-type, content-disposition).

        Re-logins and retries once if the server bounces to an HTML login page.
        Set ``retry_on_auth=False`` when the payload contains render-scoped JSF
        ids: the caller must refresh the page and rebuild those fields instead.
        """
        if not self._authenticated:
            self.login()
        resp = self._client.request("POST", url, data=data)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if content_type.lower().startswith("text/html") and self._looks_logged_out(resp):
            if not retry_on_auth:
                self._authenticated = False
                raise AuthError("session expired before download postback")
            self.login()
            resp = self._client.request("POST", url, data=data)
            resp.raise_for_status()
            retry_type = resp.headers.get("content-type", "")
            if retry_type.lower().startswith("text/html") and self._looks_logged_out(resp):
                self._authenticated = False
                raise AuthError("session lost and re-login did not restore it")
        return resp.content, resp.headers.get("content-type"), resp.headers.get("content-disposition")

    def get_download(self, url: str) -> tuple[bytes, str | None, str | None]:
        """GET a binary download; return (content, content-type, content-disposition).

        Re-logins and retries once if the server bounces to an HTML login page.
        """
        if not self._authenticated:
            self.login()
        resp = self._client.request("GET", url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if content_type.startswith("text/html") and self._looks_logged_out(resp):
            self.login()
            resp = self._client.request("GET", url)
            resp.raise_for_status()
        return resp.content, resp.headers.get("content-type"), resp.headers.get("content-disposition")

    def _request(
        self,
        method: str,
        url: str,
        data: dict | None = None,
        content: bytes | None = None,
        *,
        resendable: bool = False,
    ) -> str:
        if not self._authenticated:
            self.login()
        send = self._send_with_resends if resendable else self._send
        resp = send(method, url, data, content)
        if self._looks_logged_out(resp):
            self.login()
            resp = send(method, url, data, content)
            if self._looks_logged_out(resp):
                raise AuthError("session lost and re-login did not restore it")
        return resp.text

    def _send_with_resends(
        self, method: str, url: str, data: dict | None, content: bytes | None = None
    ) -> httpx.Response:
        for resend in range(MAX_RESENDS):
            try:
                return self._send(method, url, data, content)
            except httpx.TransportError:
                self._sleep(RESEND_BACKOFF_SECONDS * 2**resend)
        return self._send(method, url, data, content)

    def _send(
        self, method: str, url: str, data: dict | None, content: bytes | None = None
    ) -> httpx.Response:
        if content is None:
            resp = self._client.request(method, url, data=data)
        else:
            resp = self._client.request(
                method, url, content=content, headers={"Content-Type": FORM_CONTENT_TYPE}
            )
        resp.raise_for_status()
        return resp

    def _looks_logged_out(self, resp: httpx.Response) -> bool:
        return self.navigator.looks_logged_out(resp.text, str(resp.url))

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
