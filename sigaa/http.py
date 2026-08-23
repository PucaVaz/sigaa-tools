"""HTTP session: cookie jar, ViewState handling, transparent re-login + retry.

SIGAA auth is JSF-stateless: a cookie jar (JSESSIONID + sigscookie) plus a
``javax.faces.ViewState`` replayed on every postback. When a session expires the
server bounces requests back to ``logon.jsf``; this layer detects that, logs in
again, and retries the call once.
"""

from __future__ import annotations

import re

import httpx

from . import config

_VIEWSTATE_RE = re.compile(
    r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"'
)


def extract_viewstate(html: str, default: str = "j_id1") -> str:
    match = _VIEWSTATE_RE.search(html)
    return match.group(1) if match else default


class AuthError(RuntimeError):
    pass


class Session:
    """Stateful SIGAA session. Construct with credentials, then ``login()``."""

    def __init__(
        self,
        username: str,
        password: str,
        client: httpx.Client | None = None,
        *,
        timeout: float | httpx.Timeout = 30.0,
    ):
        self._username = username
        self._password = password
        self._client = client or httpx.Client(
            headers={"User-Agent": config.USER_AGENT},
            follow_redirects=True,
            timeout=timeout,
        )
        self._authenticated = False

    def login(self) -> str:
        """Authenticate and return the rendered portal HTML."""
        from .auth import perform_login  # lazy import avoids circular dependency

        portal_html = perform_login(self._client, self._username, self._password)
        self._authenticated = True
        return portal_html

    def get(self, url: str) -> str:
        return self._request("GET", url)

    def post(self, url: str, data: dict[str, str]) -> str:
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
        if content_type.lower().startswith("text/html") and self._looks_logged_out(resp.text):
            if not retry_on_auth:
                self._authenticated = False
                raise AuthError("session expired before download postback")
            self.login()
            resp = self._client.request("POST", url, data=data)
            resp.raise_for_status()
            retry_type = resp.headers.get("content-type", "")
            if retry_type.lower().startswith("text/html") and self._looks_logged_out(resp.text):
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
        if content_type.startswith("text/html") and self._looks_logged_out(resp.text):
            self.login()
            resp = self._client.request("GET", url)
            resp.raise_for_status()
        return resp.content, resp.headers.get("content-type"), resp.headers.get("content-disposition")

    def _request(self, method: str, url: str, data: dict | None = None) -> str:
        if not self._authenticated:
            self.login()
        text = self._send(method, url, data)
        if self._looks_logged_out(text):
            self.login()
            text = self._send(method, url, data)
            if self._looks_logged_out(text):
                raise AuthError("session lost and re-login did not restore it")
        return text

    def _send(self, method: str, url: str, data: dict | None) -> str:
        resp = self._client.request(method, url, data=data)
        resp.raise_for_status()
        return resp.text

    @staticmethod
    def _looks_logged_out(text: str) -> bool:
        return config.AUTH_MARKER not in text and config.LOGIN_REDIRECT_MARKER in text

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
