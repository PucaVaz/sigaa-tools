"""Parse the extension selection flow ('Vagas de Bolsas Disponíveis').

Three pages, reached in order from the portal menu:

1. The search form (``form#busca``, ``/sigaa/graduacao/agregador_bolsa/busca.jsf``).
   Choosing the EXTENSÃO scholarship type and pressing Buscar answers with
2. the results (``form#listagemResultado``): one ``table.listagem`` row per
   opportunity, each with a 'Participar da Seleção de Bolsas de Extensão' link
   carrying ``idOportunidade``. Following that link opens
3. the confirmation form (``/sigaa/extensao/DiscenteExtensao/inscricao_discente.jsf``):
   the action's details, a required Qualificações text, an optional Currículo
   Lattes and the 'Registrar-se como Interessado' button.

SIGAA reports the outcome of a search or a registration in Bootstrap alerts
(``div.alert-success|warning|danger``). A registration answers with the portal
page carrying an ``alert-success``; only that counts as registered. An empty
opportunity list is only trusted when SIGAA says "Nenhuma oportunidade foi
encontrada"; every other unexpected page raises so a markup change never passes
for "nothing open" or for a successful registration.

The success alert names the student's e-mail; every message is returned with
e-mail addresses masked.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..errors import NavigationError, ParseError, UnrecognizedPageError
from ..models import ExtensionOpportunity, ExtensionRegistration, ExtensionSelectionForm
from ._common import clean, fold, jsf_params, page_fingerprint
from ._variants import page_parser

FEATURE = "extension_opportunities"
SELECTION_FEATURE = "extension_selection"

STATUS_REGISTERED = "registered"
STATUS_REJECTED = "rejected"
STATUS_UNCONFIRMED = "unconfirmed"

_SEARCH_FORM_ID = "busca"
_RESULTS_FORM_ID = "listagemResultado"
_SELECTION_FORM_ACTION = "inscricao_discente"
_EXTENSION_TYPE_LABEL = "extensao"
_SEARCH_BUTTON_LABEL = "buscar"
_REGISTER_BUTTON_LABEL = "registrar-se"
_APPLY_LINK_MARKER = "cadastrarInteresseParticipacaoExtensao"
_DETAILS_LINK_MARKER = "vetProjDetalhes"
_QUALIFICATIONS_SUFFIX = "qualificacoes_dados_aluno"
_LATTES_SUFFIX = "lattes_dados_aluno"
_RESULTS_CAPTION = "oportunidades encontradas"
_NO_OPPORTUNITIES_NOTICE = "nenhuma oportunidade foi encontrada"
_VIEWSTATE = "javax.faces.ViewState"

# Folded column header -> model field.
_RESULT_COLUMNS = {
    "descricao da bolsa": "title",
    "vagas remuneradas": "paid_slots",
    "responsavel": "coordinator",
    "unidade": "unit",
}

# Folded label on the confirmation page -> model field. A whitelist: the same
# page shows the student's e-mail and phone, which must never be returned.
_ACTION_FIELDS = {
    "codigo": "action_code",
    "titulo da acao": "title",
    "coordenacao": "coordinator",
    "tipo da acao": "kind",
    "unidade proponente": "unit",
    "fonte de financiamento": "funding",
}

_SUCCESS_ALERTS = ("alert-success",)
_FAILURE_ALERTS = ("alert-danger", "alert-warning", "alert-error")
_OTHER_ALERTS = ("alert-info",)
# Message lists of the older SIGAA layout, kept so a refusal is never missed.
_LEGACY_FAILURE_SELECTOR = "ul.erros li, ul.warning li, #painel-erros li"
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_EMAIL_MASK = "[e-mail]"


class SelectionRejectedError(ParseError):
    """SIGAA refused to open the selection form and said why."""

    def __init__(self, messages: list[str]):
        self.messages = messages
        super().__init__("SIGAA refused the selection: " + " | ".join(messages))


def build_search_postback(html: str, year: int | None = None) -> tuple[str, dict[str, str]]:
    """Form action and payload that search the extension opportunities.

    Mirrors the browser: every default field of the search form is sent, the
    scholarship type is set to EXTENSÃO and, when given, the year replaces the
    one SIGAA pre-fills (the current year).
    """
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form", id=_SEARCH_FORM_ID)
    type_select = form.find("select", id=f"{_SEARCH_FORM_ID}:tipo") if form else None
    if type_select is None:
        raise UnrecognizedPageError(FEATURE, page_fingerprint(soup))
    extension_type = next(
        (
            option.get("value")
            for option in type_select.find_all("option")
            if fold(option.get_text()) == _EXTENSION_TYPE_LABEL
        ),
        None,
    )
    button = _submit_button(form, _SEARCH_BUTTON_LABEL)
    if not extension_type or button is None:
        raise UnrecognizedPageError(FEATURE, page_fingerprint(soup))

    fields = _default_fields(form)
    fields[str(type_select["name"])] = str(extension_type)
    if year is not None:
        fields[f"{_SEARCH_FORM_ID}:buscaAnoAtividade"] = str(year)
    fields[str(button["name"])] = str(button.get("value", ""))
    return str(form.get("action", "")), fields


def _results_table(soup):
    form = soup.find("form", id=_RESULTS_FORM_ID)
    if form is None:
        return None
    for table in form.find_all("table", class_="listagem"):
        caption = table.find("caption")
        if caption and _RESULTS_CAPTION in fold(caption.get_text(" ", strip=True)):
            return table
    return None


def _declares_no_opportunities(soup) -> bool:
    return any(
        _NO_OPPORTUNITIES_NOTICE in fold(message)
        for message in _alert_messages(soup, _FAILURE_ALERTS)
    )


def _data_rows(soup) -> list:
    table = _results_table(soup)
    return [row for row in table.find_all("tr") if row.find("td")] if table else []


@page_parser(
    FEATURE,
    lambda soup: _results_table(soup) is not None or _declares_no_opportunities(soup),
    empty=_declares_no_opportunities,
    validate=lambda result, soup: len(result) == len(_data_rows(soup)),
    name="opportunity-results",
)
def parse_opportunities(soup: BeautifulSoup) -> list[ExtensionOpportunity]:
    """Every opportunity listed on the search results page."""
    table = _results_table(soup)
    if table is None:
        return []
    columns = _result_columns(table)
    if columns is None:
        return []
    return [
        opportunity
        for row in _data_rows(soup)
        if (opportunity := _opportunity(row, columns)) is not None
    ]


def _result_columns(table) -> dict[str, int] | None:
    header = next((row for row in table.find_all("tr") if row.find("th")), None)
    if header is None:
        return None
    labels = [fold(cell.get_text(" ", strip=True)) for cell in header.find_all("th")]
    if any(label not in labels for label in _RESULT_COLUMNS):
        return None
    return {field: labels.index(label) for label, field in _RESULT_COLUMNS.items()}


def _opportunity(row, columns: dict[str, int]) -> ExtensionOpportunity | None:
    cells = row.find_all("td")
    if len(cells) <= max(columns.values()):
        return None
    apply_id = _link_param(row, _APPLY_LINK_MARKER, "idOportunidade")
    opportunity_id = apply_id or _link_param(row, _DETAILS_LINK_MARKER, "id")
    title = clean(cells[columns["title"]].get_text(" ", strip=True))
    if not opportunity_id or not title:
        return None
    unit_cell = cells[columns["unit"]]
    unit_code = clean(unit_cell.get_text(" ", strip=True)) or None
    unit_span = unit_cell.find("span", title=True)
    slots = clean(cells[columns["paid_slots"]].get_text(" ", strip=True))
    return ExtensionOpportunity(
        opportunity_id=opportunity_id,
        title=title,
        paid_slots=int(slots) if slots.isdigit() else None,
        coordinator=clean(cells[columns["coordinator"]].get_text(" ", strip=True)) or None,
        unit=clean(unit_span["title"]) if unit_span else unit_code,
        unit_code=unit_code,
        can_apply=apply_id is not None,
    )


def _link_param(row, marker: str, param: str) -> str | None:
    for anchor in row.find_all("a", id=True):
        if marker in anchor["id"]:
            return jsf_params(anchor.get("onclick") or "").get(param) or None
    return None


def build_apply_postback(html: str, opportunity_id: str) -> tuple[str, dict[str, str]]:
    """Form action and payload of one row's 'Participar da Seleção' link."""
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form", id=_RESULTS_FORM_ID)
    if form is None:
        raise UnrecognizedPageError(FEATURE, page_fingerprint(soup))
    for anchor in form.find_all("a", id=True):
        if _APPLY_LINK_MARKER not in anchor["id"]:
            continue
        params = jsf_params(anchor.get("onclick") or "")
        if params.get("idOportunidade") == str(opportunity_id):
            fields = _hidden_fields(form)
            fields[_RESULTS_FORM_ID] = _RESULTS_FORM_ID
            fields.update(params)
            return str(form.get("action", "")), fields
    raise NavigationError(
        f"extension opportunity {opportunity_id!r} is not open for selection in this search"
    )


def _selection_form(soup):
    for form in soup.find_all("form"):
        if _SELECTION_FORM_ACTION in (form.get("action") or "") and _named_field(
            form, "textarea", _QUALIFICATIONS_SUFFIX
        ):
            return form
    return None


def parse_selection_form(html: str) -> ExtensionSelectionForm:
    """The action shown on the confirmation page, before anything is submitted."""
    soup = BeautifulSoup(html, "lxml")
    form = _require_selection_form(soup)
    opportunity = form.find("input", attrs={"name": "id", "type": "hidden"})
    values: dict[str, str | None] = {}
    for row in form.find_all("tr"):
        label, value = row.find("th"), row.find("td")
        if label is None or value is None:
            continue
        field_name = _ACTION_FIELDS.get(fold(label.get_text(" ", strip=True)).rstrip(":").strip())
        if field_name:
            values[field_name] = clean(value.get_text(" ", strip=True)) or None
    if opportunity is None or not opportunity.get("value") or not values.get("title"):
        raise UnrecognizedPageError(SELECTION_FEATURE, page_fingerprint(soup))
    return ExtensionSelectionForm(opportunity_id=str(opportunity["value"]), **values)


def build_registration_postback(
    html: str, qualifications: str, lattes_url: str | None = None
) -> tuple[str, dict[str, str]]:
    """Form action and payload of 'Registrar-se como Interessado'."""
    soup = BeautifulSoup(html, "lxml")
    form = _require_selection_form(soup)
    button = _submit_button(form, _REGISTER_BUTTON_LABEL)
    lattes = _named_field(form, "input", _LATTES_SUFFIX)
    if button is None:
        raise UnrecognizedPageError(SELECTION_FEATURE, page_fingerprint(soup))
    fields = _hidden_fields(form)
    fields[str(_named_field(form, "textarea", _QUALIFICATIONS_SUFFIX)["name"])] = qualifications
    if lattes is not None:
        fields[str(lattes["name"])] = lattes_url or ""
    fields[str(button["name"])] = str(button.get("value", ""))
    return str(form.get("action", "")), fields


def parse_registration_result(html: str) -> ExtensionRegistration:
    """Classify SIGAA's answer to the registration postback."""
    soup = BeautifulSoup(html, "lxml")
    failures = _alert_messages(soup, _FAILURE_ALERTS) + _texts(soup, _LEGACY_FAILURE_SELECTOR)
    successes = _alert_messages(soup, _SUCCESS_ALERTS)
    if failures:
        return ExtensionRegistration(STATUS_REJECTED, failures + successes)
    if successes:
        return ExtensionRegistration(STATUS_REGISTERED, successes)
    return ExtensionRegistration(STATUS_UNCONFIRMED, _alert_messages(soup, _OTHER_ALERTS))


def _require_selection_form(soup):
    form = _selection_form(soup)
    if form is not None:
        return form
    refusals = _alert_messages(soup, _FAILURE_ALERTS) + _texts(soup, _LEGACY_FAILURE_SELECTOR)
    if refusals:
        raise SelectionRejectedError(refusals)
    raise UnrecognizedPageError(SELECTION_FEATURE, page_fingerprint(soup))


def _alert_messages(soup, alert_classes: tuple[str, ...]) -> list[str]:
    messages: list[str] = []
    for alert in soup.find_all("div", class_="alert"):
        if not set(alert.get("class") or []) & set(alert_classes):
            continue
        items = alert.find_all("li") or alert.select(".conteudo") or [alert]
        messages.extend(_message(item) for item in items)
    return [message for message in messages if message]


def _texts(soup, selector: str) -> list[str]:
    return [text for node in soup.select(selector) if (text := _message(node))]


def _message(node) -> str:
    return _EMAIL_RE.sub(_EMAIL_MASK, clean(node.get_text(" ", strip=True)))


def _named_field(form, tag: str, suffix: str):
    return next(
        (node for node in form.find_all(tag) if (node.get("name") or "").endswith(suffix)), None
    )


def _submit_button(form, label_fragment: str):
    for button in form.select('input[type="submit"][name]'):
        if label_fragment in fold(button.get("value") or ""):
            return button
    return None


def _hidden_fields(form) -> dict[str, str]:
    return {
        str(hidden["name"]): str(hidden.get("value", ""))
        for hidden in form.select('input[type="hidden"][name]')
    }


def _default_fields(form) -> dict[str, str]:
    """What a browser submits for an untouched form, minus its buttons.

    Unchecked checkboxes and option-less selects are not sent; a select without
    a ``selected`` option sends its first one.
    """
    fields = _hidden_fields(form)
    for text_input in form.select('input[type="text"][name]'):
        fields[str(text_input["name"])] = str(text_input.get("value", ""))
    for select in form.select("select[name]"):
        options = select.find_all("option")
        if not options:
            continue
        chosen = next((option for option in options if option.has_attr("selected")), options[0])
        fields[str(select["name"])] = str(chosen.get("value", ""))
    return fields
