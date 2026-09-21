"""Login flow. Operates on a raw httpx.Client to avoid Session recursion."""

from __future__ import annotations

import httpx

from .errors import LoginRejectedError, MissingCredentialsError
from .http import extract_viewstate
from .institutions import InstitutionProfile


def perform_login(
    client: httpx.Client, username: str, password: str, *, profile: InstitutionProfile
) -> str:
    """Authenticate and return the rendered portal HTML (with the turma list).

    Raises ``LoginRejectedError`` (a ``ValueError``) if the resulting portal is
    not authenticated.
    """
    if not username or not password:
        raise MissingCredentialsError("missing SIGAA username or password")
    login_page = client.get(profile.logon_url)
    login_page.raise_for_status()

    fields = {
        "form": "form",
        "form:width": "1280",
        "form:height": "800",
        "form:login": username,
        "form:senha": password,
        "form:entrar": "Entrar",
        "javax.faces.ViewState": extract_viewstate(login_page.text),
    }
    # The post-login redirect targets the deprecated classic portal, whose
    # http->https hop drops a trailing slash and 404s. The session cookie is set
    # regardless, so the status of this response is irrelevant.
    try:
        client.post(profile.logon_url, data=fields, follow_redirects=False)
    except httpx.HTTPError:
        pass

    # Enter via the slash-terminated classic URL, which 302s to the full beta
    # portal. A plain GET of the beta URL returns only a loading shell.
    portal = client.get(profile.portal_entry_url)
    portal.raise_for_status()
    if profile.auth_marker not in portal.text:
        raise LoginRejectedError("login failed: SIGAA rejected the credentials or showed a CAPTCHA")
    return portal.text
