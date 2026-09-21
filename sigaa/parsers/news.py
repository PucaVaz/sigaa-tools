"""Parse the Notícias panel on a Turma Virtual Principal page, and news bodies.

Each news row carries a stable id (hidden ``name="id"``) plus a per-row JSF form
whose postback to /sigaa/ava/index.jsf opens the full body.

An empty result is only trusted when SIGAA says so ("Não há notícias
cadastradas"). A page without the panel, or a panel whose rows are not
recognized, raises ``NewsParseError`` so a markup change can never pass for a
quiet class.
"""

from __future__ import annotations

import re

from ._common import fold as _fold

from bs4 import BeautifulSoup, NavigableString

from ..errors import ParseError, UnrecognizedPageError
from ._common import page_fingerprint
from ..models import NewsItem

_PANEL_HEADER_RE = re.compile(r"Not(?:&iacute;|í)cias")
_JSFCLJS_PARAM_RE = re.compile(r"jsfcljs\([^,]+,\{'([^']+)':'([^']+)'\}")
_EMPTY_PANEL_RE = re.compile(r"nao ha noticias")
_DATE_RE = re.compile(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}")


class NewsParseError(ParseError):
    pass


def parse_news_list(turma_html: str, id_turma: str) -> list[NewsItem]:
    panel = news_panel(BeautifulSoup(turma_html, "lxml"))
    if panel is None:
        raise NewsParseError(f"news panel not found on the class page (class {id_turma})")

    items: list[NewsItem] = []
    for form in panel.find_all("form"):
        id_input = form.find("input", attrs={"name": "id"})
        if not id_input or not id_input.get("value"):
            continue
        date, title = _date_and_title(form)
        items.append(
            NewsItem(
                id=id_input["value"],
                id_turma=id_turma,
                date=date,
                title=title,
                form_id=form.get("id"),
            )
        )
    if not items and not _declares_no_news(panel):
        raise NewsParseError(
            f"news panel has no recognizable rows and no empty-panel notice (class {id_turma})"
        )
    return items


def build_body_postback(turma_html: str, news_id: str, viewstate: str) -> dict | None:
    """Build the JSF POST fields that open one news item's full body."""
    soup = BeautifulSoup(turma_html, "lxml")
    id_input = soup.find("input", attrs={"name": "id", "value": news_id})
    if not id_input:
        return None
    form = id_input.find_parent("form")
    if not form:
        return None

    fields = {form["id"]: form["id"], "id": news_id, "javax.faces.ViewState": viewstate}
    anchor = form.find("a", onclick=True)
    if anchor:
        match = _JSFCLJS_PARAM_RE.search(anchor["onclick"])
        if match:
            fields[match.group(1)] = match.group(2)
    return fields


def parse_news_body(body_html: str) -> str:
    """Extract the news article text from the Visualizar response page.

    Link targets are kept inline: teachers write remote-class links as
    ``<a href="https://meet...">clique aqui</a>``, and plain text extraction
    would drop the only part that matters.
    """
    soup = BeautifulSoup(body_html, "lxml")
    container = (
        soup.find("div", class_=re.compile("descricao"))
        or soup.find("td", class_=re.compile("descricao"))
        or soup.find("div", id=re.compile("conteudo", re.I))
    )
    if container is None:
        raise UnrecognizedPageError("news_body", page_fingerprint(soup))
    target = container
    for anchor in target.find_all("a", href=True):
        href = anchor["href"].strip()
        if href.startswith(("http://", "https://")) and href not in anchor.get_text():
            anchor.append(f" ({href})")
    return target.get_text("\n", strip=True)


def news_panel(soup: BeautifulSoup):
    """The Notícias panel body that every Turma Virtual Principal page carries."""
    for header in soup.find_all("div", class_=re.compile("headerBloco")):
        if _PANEL_HEADER_RE.search(header.get_text(strip=True)):
            # The body div is not an immediate sibling (a hidden input div and a
            # closing form sit between), so scan forward for the panel body.
            body = header.find_next("div", class_=re.compile("rich-stglpanel-body"))
            return body if body is not None else header.parent
    return None


def _declares_no_news(panel) -> bool:
    return bool(_EMPTY_PANEL_RE.search(_fold(panel.get_text(" ", strip=True))))




def _date_and_title(form) -> tuple[str, str]:
    """Date and title sit as ``<date text><br><i>title</i>`` before the form.

    The scan stops at the previous row's form, so a row without its own title
    never borrows the title of the announcement above it.
    """
    date, title = "", ""
    for node in form.previous_elements:
        if getattr(node, "name", None) == "form":
            break
        if not title and getattr(node, "name", None) == "i":
            title = node.get_text(strip=True)
        elif isinstance(node, NavigableString) and not date and node.parent.name != "i":
            match = _DATE_RE.search(str(node))
            if match:
                date = match.group(0)
        if date and title:
            break
    return date, title
