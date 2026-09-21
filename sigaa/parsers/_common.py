"""Shared normalization and diagnostics without table-cell or form values."""
import hashlib
import re
import unicodedata
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


def clean(value):
    # \x96 is the Windows-1252 en dash that SIGAA emits as the reference &#150;.
    return " ".join(unicodedata.normalize("NFKC", value.replace("\x96", "–")).split())


def fold(value):
    return unicodedata.normalize("NFKD", clean(value)).encode("ascii", "ignore").decode().casefold()


def normalized(value):
    return clean(value).casefold()


def jsf_params(onclick):
    match = re.search(r"jsfcljs\([^,]+,\s*\{(.*?)\}\s*,", onclick, re.S)
    return dict(re.findall(r"'([^']+)'\s*:\s*'([^']*)'", match.group(1))) if match else {}


def page_fingerprint(html):
    """Hash structural labels so even unexpected personal headings stay private.

    No cell text, input values, URL query strings, or cookies participate.
    Counts and digests support comparisons without disclosing their contents.
    """
    soup = html if isinstance(html, BeautifulSoup) else BeautifulSoup(html, "lxml")

    def digest(values):
        return hashlib.sha256("\n".join(sorted(values)).encode()).hexdigest()[:16]

    forms = (
        str(form.get("id", "")) + ":" + urlsplit(str(form.get("action", ""))).path.split(";")[0]
        for form in soup.select("form")
    )
    return {
        "forms": len(soup.select("form")),
        "tables": len(soup.select("table")),
        "form_structure": digest(forms),
        "table_classes": digest(" ".join(t.get("class", [])) for t in soup.select("table")),
        "headers": digest(fold(n.get_text(" ", strip=True)) for n in soup.select("th")),
        "legends": digest(fold(n.get_text(" ", strip=True)) for n in soup.select("legend")),
        "captions": digest(fold(n.get_text(" ", strip=True)) for n in soup.select("caption")),
    }
