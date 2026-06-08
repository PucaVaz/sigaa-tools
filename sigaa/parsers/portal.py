"""Parse the rendered discente portal: the student header and the turma table."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import Deadline, Student, Turma

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


_MENU_FIELD_RE = re.compile(r"jsfcljs\([^,]+,\{'([^']+)':'[^']+'\}")


def find_menu_field(html: str, link_text: str) -> str | None:
    """The JSF postback field for a sidebar menu item, matched by decoded text.

    Matches on the anchor's rendered text (handles HTML entities like ``í``).
    """
    soup = BeautifulSoup(html, "lxml")
    target = link_text.strip().casefold()
    for anchor in soup.select("a[onclick*='jsfcljs']"):
        if anchor.get_text(" ", strip=True).casefold() == target:
            match = _MENU_FIELD_RE.search(anchor["onclick"])
            if match:
                return match.group(1)
    return None


def parse_student(html: str) -> Student:
    soup = BeautifulSoup(html, "lxml")
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


def parse_turmas(html: str) -> list[Turma]:
    soup = BeautifulSoup(html, "lxml")
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


def parse_deadlines(html: str) -> list[Deadline]:
    """Extract assessment/task deadlines from the portal turma event dropdowns."""
    soup = BeautifulSoup(html, "lxml")
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
