"""Recognize a page before parsing it; unmatched markup always fails loudly."""
import re
from dataclasses import dataclass
from functools import wraps
from typing import Callable

from bs4 import BeautifulSoup

from ..errors import UnrecognizedPageError
from ._common import page_fingerprint


@dataclass(frozen=True)
class Variant:
    name: str
    matches: Callable
    parse: Callable


_LOGIN_FIELD_RE = re.compile(r"login|user|usuario", re.I)


def _is_login_form(soup) -> bool:
    """A password field in a form with a login/username field: a session bounce.

    A password field alone (for example a confirmation on an authenticated
    page) does not make the page a login page.
    """
    for password in soup.select('input[type="password"]'):
        form = password.find_parent("form")
        if form is None:
            continue
        for field in form.select('input[type="text"], input[type="email"], input:not([type])'):
            if _LOGIN_FIELD_RE.search(f"{field.get('name', '')} {field.get('id', '')}"):
                return True
    return False


def resolve_variant(feature, html, variants):
    soup = html if isinstance(html, BeautifulSoup) else BeautifulSoup(html, "lxml")
    # Never let a login form satisfy a permissive content selector.
    if _is_login_form(soup):
        raise UnrecognizedPageError(feature, page_fingerprint(soup))
    for variant in variants:
        if variant.matches(soup):
            return variant
    raise UnrecognizedPageError(feature, page_fingerprint(soup))


def parse_with_variants(feature, html, variants, *args, **kwargs):
    soup = html if isinstance(html, BeautifulSoup) else BeautifulSoup(html, "lxml")
    variant = resolve_variant(feature, soup, variants)
    return variant.parse(soup, *args, **kwargs)


def page_parser(feature, matches, *, empty=lambda soup: False, validate=lambda result, soup: True,
                name="recognized-layout"):
    """Turn a parser of an already-built soup into a public page parser.

    The public function keeps taking the page HTML, builds the soup once, and
    hands that same soup to the recognizer, the parser and the validators. It
    also exposes variant metadata to offline probes.
    """
    def decorate(parser):
        def parse(soup, *args, **kwargs):
            result = parser(soup, *args, **kwargs)
            if (not result and not empty(soup)) or not validate(result, soup):
                raise UnrecognizedPageError(feature, page_fingerprint(soup))
            return result

        @wraps(parser)
        def wrapped(html, *args, **kwargs):
            return parse_with_variants(feature, html, wrapped.variants, *args, **kwargs)

        wrapped.variants = (Variant(name, matches, parse),)
        wrapped.feature = feature
        return wrapped

    return decorate
