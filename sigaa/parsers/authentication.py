"""Pure parsing of classic authentication pages."""
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from ..errors import UnrecognizedPageError
from ._common import page_fingerprint


@dataclass(frozen=True)
class LoginForm:
    action: str
    fields: dict
    username_field: str
    password_field: str


def login_action(html, url):
    soup = BeautifulSoup(html, "lxml")
    forms = [
        form for form in soup.select("form") if form.select_one('input[type="password"][name]')
    ]
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
    return LoginForm(
        urljoin(url, str(form["action"])),
        fields,
        str(users[0]["name"]),
        str(passwords[0]["name"]),
    )


def authenticated_portal(html, url, profile):
    if urlsplit(str(url)).path.split(";")[0] != urlsplit(profile.portal_entry_url).path:
        return False
    soup = BeautifulSoup(html, "lxml")
    if soup.select_one('input[type="password"], form[name="loginForm"]'):
        return False
    return any(
        parse_qs(urlsplit(str(a["href"])).query).get("dispatch") == ["logOff"]
        and "sair" in a.get_text().casefold()
        for a in soup.select("a[href]")
    )


def has_login_form(html):
    return BeautifulSoup(html, "lxml").select_one(
        'input[type="password"], form[name="loginForm"]'
    ) is not None


def has_account_picker(html):
    return BeautifulSoup(html, "lxml").select_one(
        'select[name*="vinculo"], input[name*="vinculo"], select[name*="Vinculo"]'
    ) is not None
