"""Parse the rendered discente portal: the student header and the turma table."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import Deadline, Student, Turma
from ._common import fold
from ._common import jsf_params as _jsf_params
from ._common import normalized as _normalized_label
from ._variants import page_parser

_PORTAL_FORM_RE = re.compile(r"j_id_jsp_\d+_1$")
_TURMA_PARAM_RE = re.compile(r"\{'([^']+)':'[^']+','idTurma':'(\d+)'\}")
_EVENT_PARAM_RE = re.compile(r"'id':'(\d+)','idTurma':'(\d+)'")
_MENU_KIND_RE = re.compile(r"dropdown-menu-(\w+)")
# Event kinds that are real deadlines (news lives in its own channel).
_DEADLINE_KINDS = {"avaliacao", "atividade", "tarefa", "enquete"}
_MATRICULA_RE = re.compile(r"\b(\d{11})\b")
_SEMESTER_RE = re.compile(r"Semestre atual:\s*([\d.]+)")
_COURSE_RE = re.compile(r"\n\s*([A-ZÀ-Ú][^\n]*-\s*GRADUA[ÇC][ÃA]O)")
_NAME_RE = re.compile(r"Ol[áa],\s*\n?\s*([A-ZÀ-Ú][A-ZÀ-Ú .]+?)\s*\n")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")


def _text(soup: BeautifulSoup) -> str:
    return soup.get_text("\n", strip=True)


def portal_form_id(html: str) -> str:
    """The id of the main discente portal form (target of menu postbacks)."""
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form", id=_PORTAL_FORM_RE)
    if not form:
        raise ValueError("portal form not found")
    return form["id"]


def find_menu_field(html: str, link_text: str) -> str | None:
    """The JSF postback field for a sidebar menu item, matched by decoded text.

    Matches on the anchor's rendered text (handles HTML entities like ``í``).
    """
    soup = BeautifulSoup(html, "lxml")
    anchor = _find_menu_anchor(soup, link_text)
    if anchor:
        params = _jsf_params(anchor.get("onclick", ""))
        source = next((key for key, value in params.items() if key == value), None)
        return source or next(iter(params), None)
    return None


def build_menu_postback(
    html: str, link_text: str, viewstate: str | None = None
) -> dict[str, str] | None:
    """Build the current JSF form payload for a visible portal menu item.

    Component ids and ViewState change between renders.  Mirror the browser by
    copying the selected form's hidden inputs (including ``subsistema``) and all
    parameters from the anchor's ``jsfcljs`` call instead of hardcoding ids.
    """
    soup = BeautifulSoup(html, "lxml")
    anchor = _find_menu_anchor(soup, link_text)
    if anchor is None:
        return None
    form = anchor.find_parent("form")
    if form is None:
        raise ValueError(f"portal menu item has no form: {link_text!r}")

    form_name = form.get("name") or form.get("id")
    if not form_name:
        raise ValueError("portal form has no name or id")

    fields: dict[str, str] = {}
    for hidden in form.select('input[type="hidden"][name]'):
        fields[str(hidden["name"])] = str(hidden.get("value", ""))
    fields[str(form_name)] = str(form_name)
    fields.update(_jsf_params(anchor.get("onclick", "")))
    if viewstate is not None:
        fields["javax.faces.ViewState"] = viewstate
    if not fields.get("javax.faces.ViewState"):
        raise ValueError("portal form has no javax.faces.ViewState")
    return fields


def _find_menu_anchor(soup: BeautifulSoup, link_text: str):
    target = _normalized_label(link_text)
    for anchor in soup.select("a[onclick*='jsfcljs']"):
        if _normalized_label(anchor.get_text(" ", strip=True)) == target:
            return anchor
    return None


def _shows_student(soup):
    text = _text(soup)
    return bool(_NAME_RE.search(text) and _MATRICULA_RE.search(text))


@page_parser(
    "student",
    _shows_student,
    validate=lambda result, soup: bool(result.name and result.matricula),
    name="beta-student",
)
def parse_student(soup: BeautifulSoup) -> Student:
    text = _text(soup)

    matricula = _first(_MATRICULA_RE, text) or ""
    name = _first(_NAME_RE, text) or ""
    course = _first(_COURSE_RE, text)
    semester = _first(_SEMESTER_RE, text)
    email_match = _EMAIL_RE.search(text)
    email = email_match.group(0) if email_match else None

    return Student(
        matricula=matricula,
        name=name,
        course=course.strip() if course else None,
        email=email,
        semester=semester,
    )


def _turma_anchors(soup):
    return [
        anchor for anchor in soup.select("a[onclick*='idTurma']")
        if anchor.find_parent("tr") is not None and anchor.find_parent("ul") is None
    ]


def _valid_turmas(result, soup):
    return (
        all(t.name and t.field and t.form_id for t in result)
        and len(result) == len(_turma_anchors(soup))
    )


@page_parser(
    "turmas",
    lambda soup: soup.find("form", id=_PORTAL_FORM_RE) is not None,
    empty=lambda soup: "nao ha turmas" in fold(_text(soup)),
    validate=_valid_turmas,
    name="beta-turmas",
)
def parse_turmas(soup: BeautifulSoup) -> list[Turma]:
    form = soup.find("form", id=_PORTAL_FORM_RE)
    form_id = form["id"] if form else None
    semester = _first(_SEMESTER_RE, _text(soup))

    turmas: list[Turma] = []
    for anchor in soup.select("a[onclick*='idTurma']"):
        match = _TURMA_PARAM_RE.search(anchor.get("onclick", ""))
        if not match:
            continue
        field, id_turma = match.group(1), match.group(2)
        row = anchor.find_parent("tr")
        cells = row.find_all("td", recursive=False) if row else []

        turmas.append(
            Turma(
                id_turma=id_turma,
                name=anchor.get_text(strip=True),
                code=_cell(cells, 0),
                room=_cell(cells, 2),
                schedule_raw=_cell(cells, 3),
                semester=semester,
                field=field,
                form_id=form_id,
            )
        )
    return turmas


def _deadline_menus(soup):
    return [
        menu for menu in soup.select('ul[class*="dropdown-menu-"]')
        if _menu_kind(menu.get("class", [])) in _DEADLINE_KINDS
    ]


def _event_anchors(soup):
    """Event links in the deadline dropdowns. Other links there (for example
    "ver todas") have never been deadlines and are not counted."""
    return [
        anchor
        for menu in _deadline_menus(soup)
        for anchor in menu.select("li > a[onclick]")
        if _EVENT_PARAM_RE.search(anchor.get("onclick", ""))
    ]


def _shows_deadlines(soup):
    """Deadline dropdowns, or the portal form of a student with no class cards."""
    return bool(soup.select('ul[class*="dropdown-menu-"]')) or (
        soup.find("form", id=_PORTAL_FORM_RE) is not None
    )


@page_parser(
    "deadlines",
    _shows_deadlines,
    empty=lambda soup: not _event_anchors(soup),
    # Read at portal level: a false rejection fails the whole sync, so an event
    # without a date is kept, as it always was.
    validate=lambda result, soup: (
        len(result) == len(_event_anchors(soup)) and all(d.title for d in result)
    ),
    name="beta-deadlines",
)
def parse_deadlines(soup: BeautifulSoup) -> list[Deadline]:
    """Extract assessment/task deadlines from the portal turma event dropdowns."""
    deadlines: list[Deadline] = []
    for menu in soup.select('ul[class*="dropdown-menu-"]'):
        kind = _menu_kind(menu.get("class", []))
        if kind not in _DEADLINE_KINDS:
            continue
        for anchor in menu.select("li > a[onclick]"):
            match = _EVENT_PARAM_RE.search(anchor.get("onclick", ""))
            if not match:
                continue
            event_id, id_turma = match.group(1), match.group(2)
            title_el = anchor.select_one(".titulo")
            date, detail = _event_date(anchor.select_one(".info"))
            deadlines.append(
                Deadline(
                    id=event_id,
                    id_turma=id_turma,
                    kind=kind,
                    title=title_el.get_text(" ", strip=True) if title_el else "",
                    date=date,
                    detail=detail,
                )
            )
    return deadlines


def _menu_kind(classes: list[str]) -> str | None:
    for cls in classes:
        match = _MENU_KIND_RE.fullmatch(cls)
        if match and match.group(1) != "right":
            return match.group(1)
    return None


def _event_date(info_el) -> tuple[str, str | None]:
    if info_el is None:
        return "", None
    tempo = info_el.select_one(".tempo-decorrido")
    detail = tempo.get_text(" ", strip=True) if tempo else None
    if tempo:
        tempo.extract()
    return info_el.get_text(" ", strip=True), detail


def _cell(cells, index: int) -> str | None:
    if index < len(cells):
        value = cells[index].get_text(" ", strip=True)
        return value or None
    return None


def _first(pattern: re.Pattern, text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1) if match else None


# UFG classic discente portal (SIGAA 4.2.651, live capture 2026-09-26). Every
# selector below is anchored to that page; anything else fails as unrecognized.

_UFG_ID_RE = re.compile(r"\d+")


def _ufg_profile_table(soup):
    """The "Dados Institucionais" table. SIGAA renders two id="agenda-docente"
    elements; only the one directly under #perfil-docente holds it."""
    for panel in soup.select("div#perfil-docente > div#agenda-docente"):
        heading = panel.find("h4", recursive=False)
        tables = panel.find_all("table", recursive=False)
        if heading and fold(heading.get_text(" ", strip=True)) == "dados institucionais" \
                and len(tables) == 1:
            return tables[0]
    return None


def _ufg_label(soup, label):
    """Value cell of a two-cell ``<td>Label:</td><td>value</td>`` profile row."""
    table = _ufg_profile_table(soup)
    for row in table.select("tr") if table else []:
        cells = row.find_all("td", recursive=False)
        if len(cells) == 2 and fold(cells[0].get_text(" ", strip=True)) == label:
            return cells[1].get_text(" ", strip=True) or None
    return None


def _ufg_semester(soup):
    node = soup.select_one("#info-usuario .periodo-atual strong")
    return node.get_text(" ", strip=True) if node else None


@page_parser(
    "student",
    lambda soup: bool(
        soup.select_one("#info-usuario .usuario span") and _ufg_label(soup, "matricula:")
    ),
    validate=lambda result, soup: bool(result.name and result.matricula),
    name="ufg-student",
)
def _parse_ufg_student(soup: BeautifulSoup) -> Student:
    return Student(
        matricula=_ufg_label(soup, "matricula:") or "",
        name=soup.select_one("#info-usuario .usuario span").get_text(" ", strip=True),
        course=_ufg_label(soup, "curso:"),
        email=_ufg_label(soup, "e-mail:"),
        semester=_ufg_semester(soup),
    )


parse_student.variants = (*parse_student.variants, *_parse_ufg_student.variants)


def _ufg_turma_table(soup):
    """The one class table in #turmas-portal (not the updates rotator above it)."""
    panel = soup.select_one("div#turmas-portal.simple-panel")
    tables = [
        table for table in (panel.find_all("table", recursive=False) if panel else [])
        if [fold(th.get_text(" ", strip=True)) for th in table.select("thead > tr > th")][:3]
        == ["componente curricular", "local", "horario"]
    ]
    return tables[0] if len(tables) == 1 else None


def _ufg_turma(row, semester):
    """A class row, or None when the row has any other shape."""
    cells = row.find_all("td", recursive=False)
    if len(cells) != 6 or "descricao" not in cells[0].get("class", []):
        return None
    form = cells[0].find("form", recursive=False)
    id_input = form.select_one("input[name=idTurma]") if form else None
    anchors = form.select("a[onclick]") if form else []
    if not (form and form.get("id", "").startswith("form_acessarTurmaVirtual")
            and id_input and _UFG_ID_RE.fullmatch(id_input.get("value", ""))
            and len(anchors) == 1):
        return None
    params = _jsf_params(anchors[0].get("onclick", ""))
    field = next((key for key, value in params.items() if key == value), None)
    if len(params) != 1 or not field or not field.startswith(form["id"] + ":"):
        return None
    return Turma(
        id_turma=id_input["value"],
        name=anchors[0].get_text(" ", strip=True),
        room=_cell(cells, 1),
        schedule_raw=_cell(cells, 2),
        semester=semester,
        field=field,
        form_id=form["id"],
    )


def _ufg_hidden_row(row):
    cells = row.find_all("td", recursive=False)
    return (len(cells) == 1 and cells[0].has_attr("colspan")
            and cells[0].get("id", "").startswith("linha_")
            and not cells[0].get_text(strip=True) and not cells[0].find(True))


@page_parser(
    "turmas",
    lambda soup: _ufg_turma_table(soup) is not None,
    validate=lambda result, soup: bool(result) and all(t.name for t in result),
    name="ufg-turmas",
)
def _parse_ufg_turmas(soup: BeautifulSoup) -> list[Turma]:
    semester = _ufg_semester(soup)
    turmas = []
    for row in _ufg_turma_table(soup).select("tbody > tr"):
        if _ufg_hidden_row(row):
            continue
        turma = _ufg_turma(row, semester)
        if turma is None:
            return []  # one unreadable row makes the whole page unrecognized
        turmas.append(turma)
    return turmas


parse_turmas.variants = (*parse_turmas.variants, *_parse_ufg_turmas.variants)


def _ufg_activity_table(soup):
    form = soup.select_one("form#formAtividades")
    panel = form.select_one("div#avaliacao-portal.simple-panel") if form else None
    heading = panel.find("h4", recursive=False) if panel else None
    tables = panel.find_all("table", recursive=False) if panel else []
    if not (heading and fold(heading.get_text(" ", strip=True)) == "minhas atividades"
            and len(tables) == 1):
        return None
    labels = [fold(th.get_text(" ", strip=True)) for th in tables[0].select("thead > tr > th")]
    return tables[0] if labels == ["", "data", "atividade"] else None


def _ufg_deadline(row):
    cells = row.find_all("td", recursive=False)
    if len(cells) != 3:
        return None
    anchors = cells[2].select("a[onclick]")
    labels = cells[2].find_all("strong")
    if len(anchors) != 1 or len(labels) != 1:
        return None
    params = _jsf_params(anchors[0].get("onclick", ""))
    kind = fold(labels[0].get_text(" ", strip=True)).rstrip(":").strip()
    event_id, id_turma = params.get("id", ""), params.get("idTurma", "")
    title = anchors[0].get_text(" ", strip=True)
    date = cells[1].get_text(" ", strip=True)
    if not (kind in _DEADLINE_KINDS and _UFG_ID_RE.fullmatch(event_id)
            and _UFG_ID_RE.fullmatch(id_turma) and title and date):
        return None
    return Deadline(id=event_id, id_turma=id_turma, kind=kind, title=title, date=date)


@page_parser(
    "deadlines",
    lambda soup: _ufg_activity_table(soup) is not None,
    validate=lambda result, soup: bool(result),
    name="ufg-deadlines",
)
def _parse_ufg_deadlines(soup: BeautifulSoup) -> list[Deadline]:
    deadlines = []
    for row in _ufg_activity_table(soup).select("tbody > tr"):
        deadline = _ufg_deadline(row)
        if deadline is None:
            return []  # one unreadable row makes the whole page unrecognized
        deadlines.append(deadline)
    return deadlines


parse_deadlines.variants = (*parse_deadlines.variants, *_parse_ufg_deadlines.variants)
