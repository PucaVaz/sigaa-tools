"""Parse the rendered discente portal: the student header and the turma table."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, NavigableString

from ..errors import UnrecognizedPageError
from ..models import Deadline, Student, Turma
from ._common import clean, fold, page_fingerprint
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
_UFCG_MATRICULA_LABEL_RE = re.compile(r"Matr[ií]cula\s*:?", re.I)


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


def _ufcg_matricula(soup):
    for row in soup.select("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) == 2 and _UFCG_MATRICULA_LABEL_RE.fullmatch(
            cells[0].get_text(" ", strip=True)
        ):
            return cells[1].get_text(" ", strip=True)
    return ""


def _shows_ufcg_student(soup):
    return bool(soup.select_one(".usuario span") and _ufcg_matricula(soup))


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


@page_parser(
    "student",
    _shows_ufcg_student,
    validate=lambda result, soup: bool(result.name and result.matricula),
    name="ufcg-student",
)
def _parse_ufcg_student(soup: BeautifulSoup) -> Student:
    name = soup.select_one(".usuario span")
    matricula = _ufcg_matricula(soup)
    semester = soup.select_one(".periodo-atual strong")
    return Student(
        matricula=matricula,
        name=name.get_text(" ", strip=True) if name else "",
        semester=semester.get_text(" ", strip=True) if semester else None,
    )


parse_student.variants = (*parse_student.variants, *_parse_ufcg_student.variants)


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


def _shows_beta_turmas(soup):
    if soup.find("form", id=_PORTAL_FORM_RE) is None:
        return False
    if soup.select_one(".usuario, .periodo-atual"):
        return False
    if "nao ha turmas" in fold(_text(soup)):
        return True
    return any(
        (row := anchor.find_parent("tr")) is not None
        and len(row.find_all("td", recursive=False)) >= 5
        and _TURMA_PARAM_RE.search(anchor.get("onclick", ""))
        for anchor in soup.select("a[onclick*='idTurma']")
    )


@page_parser(
    "turmas",
    _shows_beta_turmas,
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


def _ufcg_header_roles(table):
    header = table.find("tr")
    if header is None:
        return {}
    roles = {}
    for index, cell in enumerate(header.find_all(["td", "th"], recursive=False)):
        label = fold(cell.get_text(" ", strip=True))
        if re.search(r"turma|disciplina|componente", label):
            roles.setdefault("class", index)
        elif re.search(r"sala|local|ambiente", label):
            roles.setdefault("room", index)
        elif re.search(r"hor[aá]rio|dia|turno", label):
            roles.setdefault("schedule", index)
        elif re.search(r"c[oó]digo|code", label):
            roles.setdefault("code", index)
    return roles


def _ufcg_class_control(row):
    return bool(row.select_one("td.descricao a[onclick]")) or any(
        key.casefold().endswith("openturma") and value == key
        for anchor in row.select("a[onclick]")
        for key, value in _jsf_params(anchor.get("onclick", "")).items()
    )


def _ufcg_turma_table(soup):
    for panel in soup.select(".simple-panel"):
        for table in panel.select("table"):
            roles = _ufcg_header_roles(table)
            header = table.find("tr")
            rows = [
                row for row in table.select("tr")
                if row is not header
                and not (
                    len(cells := row.find_all("td", recursive=False)) == 1
                    and cells[0].has_attr("colspan")
                    and not _ufcg_class_control(row)
                )
            ]
            if {"class", "room", "schedule"} <= roles.keys() and rows:
                return table, roles, rows
    return None


def _ufcg_turma_params(anchor):
    params = _jsf_params(anchor.get("onclick", ""))
    id_key = next(
        (key for key in params if re.sub(r"\W", "", key).casefold().endswith("idturma")),
        None,
    )
    field = next(
        (key for key, value in params.items() if key != id_key and value == key),
        None,
    )
    return params.get(id_key, "") if id_key else "", field


def _shows_ufcg_turmas(soup):
    layout = _ufcg_turma_table(soup)
    if not layout:
        return False
    table, _, rows = layout
    header_width = len(table.find("tr").find_all(["td", "th"], recursive=False))
    return all(
        len(row.find_all("td", recursive=False)) == header_width
        and row.select_one("td.descricao a[onclick]")
        for row in rows
    )


def _valid_ufcg_turmas(result, soup):
    layout = _ufcg_turma_table(soup)
    if not layout:
        return False
    _, _, rows = layout
    return len(result) == len(rows) and all(
        turma.id_turma and turma.name and turma.field and turma.form_id for turma in result
    )


@page_parser(
    "turmas",
    _shows_ufcg_turmas,
    validate=_valid_ufcg_turmas,
    name="ufcg-turmas",
)
def _parse_ufcg_turmas(soup: BeautifulSoup) -> list[Turma]:
    layout = _ufcg_turma_table(soup)
    if not layout:
        return []
    _, roles, rows = layout
    semester_node = soup.select_one(".periodo-atual strong")
    semester = semester_node.get_text(" ", strip=True) if semester_node else None
    turmas = []
    for row in rows:
        cells = row.find_all("td", recursive=False)
        description = row.find("td", class_="descricao", recursive=False)
        anchor = description.select_one("a[onclick]") if description else None
        form = anchor.find_parent("form") if anchor else None
        id_turma, field = _ufcg_turma_params(anchor) if anchor else ("", None)
        code = _cell(cells, roles["code"]) if "code" in roles else None
        turmas.append(
            Turma(
                id_turma=id_turma,
                name=anchor.get_text(" ", strip=True) if anchor else "",
                code=code,
                room=_cell(cells, roles["room"]),
                schedule_raw=_cell(cells, roles["schedule"]),
                semester=semester,
                field=field,
                form_id=(form.get("id") or form.get("name")) if form else None,
            )
        )
    return turmas


parse_turmas.variants = (*parse_turmas.variants, *_parse_ufcg_turmas.variants)


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


def _ufcg_deadlines_panel(soup):
    form = soup.select_one("form#formAtividades")
    return form.select_one("#avaliacao-portal") if form else None


def _ufcg_deadlines_empty(soup):
    panel = _ufcg_deadlines_panel(soup)
    marker = panel.select_one("p.vazio") if panel else None
    children = panel.find_all(recursive=False) if panel else []
    return bool(
        marker
        and fold(marker.get_text(" ", strip=True))
        == "nao ha atividades cadastradas para os proximos 15 dias ou decorridos 7 dias."
        and [child.name for child in children] == ["h4", "p"]
        and fold(children[0].get_text(" ", strip=True)) == "minhas atividades"
        and children[1] is marker
        and all(not child.find(True) for child in children)
        and not any(
            not getattr(child, "name", None) and str(child).strip()
            for child in panel.children
        )
    )


@page_parser(
    "deadlines",
    _ufcg_deadlines_empty,
    empty=_ufcg_deadlines_empty,
    name="ufcg-deadlines-empty",
)
def _parse_ufcg_deadlines(soup):
    return []


parse_deadlines.variants = (*parse_deadlines.variants, *_parse_ufcg_deadlines.variants)


@page_parser(
    "deadlines",
    lambda soup: bool((panel := _ufcg_deadlines_panel(soup)) and panel.select_one("table")),
    name="ufcg-deadlines-populated",
)
def _parse_ufcg_populated_deadlines(soup):
    panel = _ufcg_deadlines_panel(soup)
    tables = panel.find_all("table", recursive=False)
    heading = panel.find("h4", recursive=False)
    children = panel.find_all(recursive=False)
    more = children[2] if len(children) == 3 else None
    if (len(tables) != 1 or not heading or panel.select_one("p.vazio")
            or children[:2] != [heading, tables[0]]
            or more is None or more.name != "a" or more.get("class") != ["mais"]
            or more.has_attr("onclick")
            or "avaliacao" not in fold(urlsplit(more.get("href", "")).path)
            or fold(heading.get_text(" ", strip=True)) != "minhas atividades"):
        return []
    table = tables[0]
    header = table.select_one("thead > tr")
    rows = table.select("tbody > tr")
    if (not header or len(header.find_all("th", recursive=False)) != 3
            or not rows or len(table.select("tr")) != len(rows) + 1
            or table.select_one("a, button, input, select")):
        return []
    info_cells = rows[0].find_all("td", recursive=False)
    if len(info_cells) != 1 or info_cells[0].get("colspan") != "5":
        return []
    turmas = parse_turmas(soup)
    deadlines = []
    for row in rows[1:]:
        cells = row.find_all("td", recursive=False)
        if len(cells) != 3:
            return []
        date = clean(cells[1].get_text(" ", strip=True))
        date_match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", date)
        small = cells[2].find("small", recursive=False)
        br = small.find("br", recursive=False) if small else None
        strong = small.find("strong", recursive=False) if small else None
        if not date_match or not br or not strong:
            return []
        try:
            datetime.strptime(date_match.group(), "%d/%m/%Y")
        except ValueError:
            return []
        course = clean(" ".join(str(node) for node in br.previous_siblings
                                if isinstance(node, NavigableString)))
        title = clean(" ".join(str(node) if isinstance(node, NavigableString)
                               else node.get_text(" ", strip=True)
                               for node in strong.next_siblings))
        if not title or fold(strong.get_text(" ", strip=True)) != "avaliacao:":
            return []
        matches = [turma for turma in turmas if re.search(
            rf"(?<!\w){re.escape(fold(turma.name))}(?!\w)", fold(course)
        )]
        if len(matches) != 1:
            return []
        turma = matches[0]
        payload = json.dumps(
            ["ufcg", "portal", "v1", turma.id_turma, "avaliacao", fold(date), fold(title)],
            ensure_ascii=False, separators=(",", ":"),
        )
        event_id = "ufcg:portal:v1:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
        deadlines.append(Deadline(event_id, turma.id_turma, "avaliacao", title, date))
    if len({item.id for item in deadlines}) != len(deadlines):
        raise UnrecognizedPageError("deadlines", page_fingerprint(soup))
    return deadlines


parse_deadlines.variants = (*parse_deadlines.variants, *_parse_ufcg_populated_deadlines.variants)


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
