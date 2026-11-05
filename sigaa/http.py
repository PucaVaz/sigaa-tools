"""HTTP session: cookie jar, ViewState handling, transparent re-login + retry.

SIGAA auth is JSF-stateless: a cookie jar (JSESSIONID + sigscookie) plus a
``javax.faces.ViewState`` replayed on every postback. When a session expires the
server bounces requests back to ``logon.jsf``; this layer detects that, logs in
again, and retries the call once.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import httpx

from . import config
from .errors import STAGE_AUTH, SigaaError
from .institutions import InstitutionProfile, Navigator, auth_session

_VIEWSTATE_RE = re.compile(
    r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"'
)


def extract_viewstate(html: str, default: str = "j_id1") -> str:
    match = _VIEWSTATE_RE.search(html)
    return match.group(1) if match else default


def _cookie_matches_host(cookie_domain: str, host: str) -> bool:
    domain = cookie_domain.lstrip(".")
    return host == domain or host.endswith("." + domain)


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
        cookie_only: bool = False,
    ):
        self.profile = profile
        self.navigator = navigator
        self._username = username
        self._password = password
        self._cookie_only = cookie_only
        self._client = client or httpx.Client(
            headers={"User-Agent": config.USER_AGENT},
            follow_redirects=True,
            timeout=timeout,
            event_hooks={"request": [self._validate_request]},
        )
        self._authenticated = False
        if client is not None:
            self._client.event_hooks.setdefault("request", []).append(self._validate_request)

    def _validate_request(self, request: httpx.Request) -> None:
        self.profile.validate_url(str(request.url))

    def login(self) -> str:
        """Authenticate and return the rendered portal HTML.

        A ``cookie_only`` session holds a SIGAA Cookie header in place of the
        password and only ever replays it, whatever the institution's own login
        is, so a dead session raises instead of falling back to a password.
        """
        if self._cookie_only:
            portal_html = auth_session.perform_login(self, self.profile)
        else:
            portal_html = self.navigator.login(self)
        self._authenticated = True
        return portal_html

    def cookie_header(self) -> str:
        """The SIGAA cookies this session holds, as a Cookie header value."""
        host = urlsplit(self.profile.host).hostname or ""
        return "; ".join(
            f"{cookie.name}={cookie.value}"
            for cookie in self._client.cookies.jar
            if _cookie_matches_host(cookie.domain, host)
        )

    def get(self, url: str) -> str:
        return self._request("GET", url)

    def post(self, url: str, data: dict[str, str | list[str]]) -> str:
        """POST form data. A list value repeats the key (httpx encodes it so;
        tuples inside the mapping break h11)."""
        return self._request("POST", url, data=data)

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

    def _request(self, method: str, url: str, data: dict | None = None) -> str:
        if not self._authenticated:
            self.login()
        resp = self._send(method, url, data)
        if self._looks_logged_out(resp):
            self.login()
            resp = self._send(method, url, data)
            if self._looks_logged_out(resp):
                raise AuthError("session lost and re-login did not restore it")
        return resp.text

    def _send(self, method: str, url: str, data: dict | None) -> httpx.Response:
        resp = self._client.request(method, url, data=data)
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
