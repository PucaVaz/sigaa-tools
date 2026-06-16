"""Open and scrape a portal deadline event (tarefa/atividade).

Each deadline on a portal turma card is a dropdown anchor whose JSF postback
navigates into the Turma Virtual and renders the event page — for a tarefa, the
"Responder tarefa" form. We replay that postback (same form/field the browser
posts), then read the ``label`` / ``div.campo`` rows it lays the details out in.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

# jsfcljs(getElementById('<form>'),{'<field>':'<field>','id':'<event>','idTurma':'<turma>'},'')
_ONCLICK_RE = re.compile(
    r"getElementById\('([^']+)'\),\{'([^']+)':'[^']+','id':'(\d+)','idTurma':'(\d+)'"
)
# SIGAA renders this when a task is opened outside its submission window.
_NOTICE_RE = re.compile(r"Esta tarefa só estará dispon", re.I)


def build_event_postback(portal_html: str, event_id: str, viewstate: str) -> dict | None:
    """Build the JSF POST that opens one portal event page, or None if absent."""
    soup = BeautifulSoup(portal_html, "lxml")
    for anchor in soup.select("a[onclick]"):
        onclick = anchor.get("onclick", "")
        if f"'id':'{event_id}'" not in onclick:
            continue
        match = _ONCLICK_RE.search(onclick)
        if not match:
            return None
        form_id, field, _event, id_turma = match.groups()
        return {
            form_id: form_id,
            field: field,
            "id": event_id,
            "idTurma": id_turma,
            "javax.faces.ViewState": viewstate,
        }
    return None


def parse_tarefa_body(html: str) -> dict | None:
    """Scrape an event form's label/value rows (Descrição, Período, ...).

    Returns the rows as a dict keyed by their (colon-stripped) label, or None if
    the page carries no recognizable event detail form.
    """
    soup = BeautifulSoup(html, "lxml")
    form = _event_form(soup)
    if form is None:
        notice = soup.find(string=_NOTICE_RE)
        if notice:
            return {"Aviso": notice.strip()}
        return None
    fields: dict[str, str] = {}
    for li in form.select("ul.form > li"):
        label = li.find("label")
        campo = li.find("div", class_="campo")
        if label and campo:
            key = label.get_text(" ", strip=True).rstrip(":").strip()
            fields[key] = campo.get_text(" ", strip=True)
    return fields or None


def _event_form(soup: BeautifulSoup):
    """The form holding the detail rows, found via its legend or its layout."""
    for legend in soup.find_all("legend"):
        text = legend.get_text(strip=True).casefold()
        if "tarefa" in text or "atividade" in text or "respond" in text:
            return legend.find_parent("form") or legend.parent
    campo = soup.find("div", class_="campo")
    return campo.find_parent("form") if campo else None
