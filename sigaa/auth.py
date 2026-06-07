"""Login flow. Operates on a raw httpx.Client to avoid Session recursion."""

from __future__ import annotations

import httpx

from . import config
from .http import extract_viewstate


def perform_login(client: httpx.Client, username: str, password: str) -> str:
    """Authenticate and return the rendered portal HTML (with the turma list).

    Raises ``ValueError`` if the resulting portal is not authenticated.
    """
    login_page = client.get(config.LOGON_URL)
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
        client.post(config.LOGON_URL, data=fields)
    except httpx.HTTPError:
        pass

    # Enter via the slash-terminated classic URL, which 302s to the full beta
    # portal. A plain GET of the beta URL returns only a loading shell.
    portal = client.get(config.PORTAL_ENTRY_URL)
    portal.raise_for_status()
    if config.AUTH_MARKER not in portal.text:
        raise ValueError("login failed (check credentials / CAPTCHA)")
    return portal.text
