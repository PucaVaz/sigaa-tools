"""Authentication by an imported browser session, for SSO the tool cannot pass.

Some institutions put SIGAA behind a single sign-on that enforces reCAPTCHA, so
no username/password form can be submitted unattended. The student logs in with
a browser and stores that session's Cookie header with ``sigaa login``; this
helper replays it against SIGAA only. It never contacts the SSO host: a bounce
there raises ``SsoRedirectError`` from the request guard before it is sent.
"""
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

from ..errors import LoginRejectedError, MissingCredentialsError
from ..parsers.authentication import authenticated_portal, has_login_form

_NOT_A_COOKIE = (
    "stored SIGAA session is not a Cookie header; paste the whole Cookie value "
    "from the browser (e.g. `JSESSIONID=...; other=...`), not a bare value"
)


def parse_cookie_header(header):
    """``name=value; other=value`` -> dict. Rejects anything but a Cookie header."""
    header = (header or "").strip()
    if header.casefold().startswith("cookie:"):
        header = header.split(":", 1)[1].strip()
    if not header or "\n" in header or "\r" in header:
        raise MissingCredentialsError(_NOT_A_COOKIE)
    jar = SimpleCookie()
    jar.load(header)
    cookies = {name: morsel.value for name, morsel in jar.items()}
    if not cookies:
        raise MissingCredentialsError(_NOT_A_COOKIE)
    return cookies


def perform_login(session, profile):
    cookies = parse_cookie_header(session._password)
    client = session._client
    domain = urlsplit(profile.host).hostname
    for name, value in cookies.items():
        client.cookies.set(name, value, domain=domain, path="/")
    response = client.get(profile.portal_entry_url, follow_redirects=True)
    response.raise_for_status()
    if authenticated_portal(response.text, response.url, profile):
        return response.text
    # The navigator knows its fork's own "session expired" pages, which need not
    # carry a login form (UFG's is an empty expirada.jsp).
    if has_login_form(response.text) or session.navigator.looks_logged_out(
        response.text, str(response.url)
    ):
        raise LoginRejectedError("imported SIGAA session expired; run `sigaa login` again")
    raise LoginRejectedError("imported session did not reach the authenticated student portal")
