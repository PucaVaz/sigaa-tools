"""Classic SIGAA form authentication, with fields discovered from each render.

The flow is based on JucaGF/sigaa-tools-ufcg (MIT); see docs/institutions/ufcg.md.
No enrollment worker or submission logic is included.
"""
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, parse_qs

from bs4 import BeautifulSoup

from ..errors import LoginRejectedError, MissingCredentialsError, UnrecognizedPageError
from ..parsers._common import page_fingerprint


@dataclass(frozen=True)
class LoginForm:
    action: str
    fields: dict
    username_field: str
    password_field: str


def login_action(html, url):
    soup = BeautifulSoup(html, "lxml")
    forms = [form for form in soup.select("form") if form.select_one('input[type="password"][name]')]
    if len(forms) != 1:
        raise UnrecognizedPageError("login", page_fingerprint(soup))
    form = forms[0]
    users = form.select('input[type="text"][name], input[type="email"][name]')
    passwords = form.select('input[type="password"][name]')
    if len(users) != 1 or len(passwords) != 1 or not form.get("action"):
        raise UnrecognizedPageError("login", page_fingerprint(soup))
    fields = {}
    for node in form.select('input[type="hidden"][name]'):
        name, value = str(node["name"]), str(node.get("value", ""))
        if name in fields:
            previous = fields[name]
            fields[name] = [*previous, value] if isinstance(previous, list) else [previous, value]
        else:
            fields[name] = value
    for name, value in (("width", "1280"), ("height", "800")):
        if name in fields:
            fields[name] = value
    submits = form.select('input[type="submit"][name]')
    if len(submits) > 1:
        raise UnrecognizedPageError("login", page_fingerprint(soup))
    if submits:
        fields[str(submits[0]["name"])] = str(submits[0].get("value", ""))
    return LoginForm(urljoin(url, str(form["action"])), fields,
                     str(users[0]["name"]), str(passwords[0]["name"]))


def authenticated_portal(html, url, profile):
    if urlsplit(str(url)).path.split(";")[0] != urlsplit(profile.portal_entry_url).path:
        return False
    soup = BeautifulSoup(html, "lxml")
    if soup.select_one('input[type="password"], form[name="loginForm"]'):
        return False
    return any(parse_qs(urlsplit(str(a["href"])).query).get("dispatch") == ["logOff"]
               and "sair" in a.get_text().casefold() for a in soup.select("a[href]"))


def perform_login(session, profile):
    if not session._username or not session._password:
        raise MissingCredentialsError("missing SIGAA username or password")
    client = session._client
    page = client.get(profile.logon_url, follow_redirects=True)
    page.raise_for_status()
    action = login_action(page.text, str(page.url))
    # Check the action before adding secrets. Request hooks also guard redirects.
    profile.validate_url(action.action)
    fields = dict(action.fields)
    fields[action.username_field] = session._username
    fields[action.password_field] = session._password
    response = client.post(action.action, data=fields, follow_redirects=True)
    response.raise_for_status()
    if authenticated_portal(response.text, response.url, profile):
        return response.text
    soup = BeautifulSoup(response.text, "lxml")
    if soup.select_one('input[type="password"], form[name="loginForm"]'):
        raise LoginRejectedError("login rejected; check credentials or required CAPTCHA/2FA")
    # An account/vínculo picker must be handled by the student, never bypassed.
    if soup.select_one('select[name*="vinculo"], input[name*="vinculo"], select[name*="Vinculo"]'):
        raise LoginRejectedError("login requires account selection")
    response = client.get(profile.portal_entry_url, follow_redirects=True)
    response.raise_for_status()
    if not authenticated_portal(response.text, response.url, profile):
        raise LoginRejectedError("login did not reach the authenticated student portal")
    return response.text
