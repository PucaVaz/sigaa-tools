"""Parse the rendered discente portal: the student header and the turma table."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import Student, Turma

_PORTAL_FORM_RE = re.compile(r"j_id_jsp_\d+_1$")
_TURMA_PARAM_RE = re.compile(r"\{'([^']+)':'[^']+','idTurma':'(\d+)'\}")
_MATRICULA_RE = re.compile(r"\b(\d{11})\b")
_SEMESTER_RE = re.compile(r"Semestre atual:\s*([\d.]+)")
_COURSE_RE = re.compile(r"\n\s*([A-ZÀ-Ú][^\n]*-\s*GRADUA[ÇC][ÃA]O)")
_NAME_RE = re.compile(r"Ol[áa],\s*\n?\s*([A-ZÀ-Ú][A-ZÀ-Ú .]+?)\s*\n")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")


def _text(soup: BeautifulSoup) -> str:
    return soup.get_text("\n", strip=True)


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


def _cell(cells, index: int) -> str | None:
    if index < len(cells):
        value = cells[index].get_text(" ", strip=True)
        return value or None
    return None


def _first(pattern: re.Pattern, text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1) if match else None
