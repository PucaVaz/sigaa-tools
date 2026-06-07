"""Parse the Notícias panel on a Turma Virtual Principal page, and news bodies.

Each news row carries a stable id (hidden ``name="id"``) plus a per-row JSF form
whose postback to /sigaa/ava/index.jsf opens the full body.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import NewsItem

_PANEL_HEADER_RE = re.compile(r"Not(?:&iacute;|í)cias")
_JSFCLJS_PARAM_RE = re.compile(r"jsfcljs\([^,]+,\{'([^']+)':'([^']+)'\}")


def parse_news_list(turma_html: str, id_turma: str) -> list[NewsItem]:
    panel = _news_panel(turma_html)
    if panel is None:
        return []

    items: list[NewsItem] = []
    for form in panel.find_all("form"):
        id_input = form.find("input", attrs={"name": "id"})
        if not id_input or not id_input.get("value"):
            continue
        news_id = id_input["value"]
        date, title = _date_and_title(form)
        items.append(
            NewsItem(
                id=news_id,
                id_turma=id_turma,
                date=date,
                title=title,
                form_id=form.get("id"),
            )
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
    """Extract the news article text from the Visualizar response page."""
    soup = BeautifulSoup(body_html, "lxml")
    container = (
        soup.find("div", class_=re.compile("descricao"))
        or soup.find("td", class_=re.compile("descricao"))
        or soup.find("div", id=re.compile("conteudo", re.I))
    )
    target = container or soup
    return target.get_text("\n", strip=True)


def _news_panel(turma_html: str):
    soup = BeautifulSoup(turma_html, "lxml")
    for header in soup.find_all("div", class_=re.compile("headerBloco")):
        if _PANEL_HEADER_RE.search(header.get_text(strip=True)):
            body = header.find_next_sibling("div")
            return body if body is not None else header.parent
    return None


def _date_and_title(form) -> tuple[str, str]:
    """Date and title sit as text + <i> just before the form in the panel."""
    date, title = "", ""
    italic = form.find_previous("i")
    if italic:
        title = italic.get_text(strip=True)
        prev = italic.previous_sibling
        while prev is not None and not str(prev).strip():
            prev = prev.previous_sibling
        if prev is not None:
            match = re.search(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}", str(prev))
            if match:
                date = match.group(0)
    return date, title
