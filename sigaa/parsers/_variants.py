"""Recognize a page before parsing it; unmatched markup always fails loudly."""
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


def resolve_variant(feature, html, variants):
    soup = html if isinstance(html, BeautifulSoup) else BeautifulSoup(html, "lxml")
    # Never let a login form satisfy a permissive content selector.
    if soup.select_one('input[type="password"]'):
        raise UnrecognizedPageError(feature, page_fingerprint(soup))
    for variant in variants:
        if variant.matches(soup):
            return variant
    raise UnrecognizedPageError(feature, page_fingerprint(soup))


def parse_with_variants(feature, html, variants, *args, **kwargs):
    soup = BeautifulSoup(html, "lxml")
    variant = resolve_variant(feature, soup, variants)
    return variant.parse(soup, *args, **kwargs)


def page_parser(feature, matches, *, empty=lambda soup: False, validate=lambda result, soup: True,
                name="recognized-layout"):
    """Keep public signatures and expose variant metadata to offline probes."""
    def decorate(parser):
        def parse(soup, *args, **kwargs):
            result = parser(str(soup), *args, **kwargs)
            if (not result and not empty(soup)) or not validate(result, soup):
                raise UnrecognizedPageError(feature, page_fingerprint(soup))
            return result
        variants = (Variant(name, matches, parse),)
        @wraps(parser)
        def wrapped(html, *args, **kwargs):
            return parse_with_variants(feature, html, wrapped.variants, *args, **kwargs)
        wrapped.variants = variants
        wrapped.feature = feature
        return wrapped
    return decorate
