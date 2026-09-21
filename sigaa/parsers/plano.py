"""Parse a turma's Plano de Curso page (Cronograma de Aulas + Avaliações)."""

from __future__ import annotations

from bs4 import BeautifulSoup

from ._variants import page_parser
from ._common import fold

from ..models import CoursePlan, PlanEntry, PlanEvaluation


def _recognized_plan(soup):
    return any(fold(c.get_text()).startswith(("cronograma de aulas", "avaliacoes"))
               for c in soup.select("table caption"))


def _valid_plan(result, soup):
    if result is None:
        return False
    for table in soup.select("table"):
        caption = table.find("caption")
        text = fold(caption.get_text()) if caption else ""
        width = 3 if text.startswith("cronograma de aulas") else 2 if text.startswith("avaliacoes") else 0
        if width and any(len(row.find_all("td", recursive=False)) != width
                         for row in table.select("tbody tr")):
            return False
    return True


@page_parser("plan", _recognized_plan, validate=_valid_plan, name="course-plan-tables")
def parse_course_plan(soup: BeautifulSoup, id_turma: str) -> CoursePlan | None:
    """Extract schedule and evaluation dates. Returns None if no plan tables."""
    cronograma = _table_by_caption(soup, "cronograma de aulas")
    avaliacoes = _table_by_caption(soup, "avalia")
    if cronograma is None and avaliacoes is None:
        return None

    schedule = [
        PlanEntry(start=cells[0], end=cells[1], description=cells[2])
        for cells in _rows(cronograma, width=3)
    ]
    evaluations = [
        PlanEvaluation(date=cells[0], description=cells[1])
        for cells in _rows(avaliacoes, width=2)
    ]
    return CoursePlan(id_turma=id_turma, schedule=schedule, evaluations=evaluations)


def _table_by_caption(soup: BeautifulSoup, caption_prefix: str):
    for table in soup.select("table"):
        caption = table.find("caption")
        if caption and caption.get_text(strip=True).casefold().startswith(caption_prefix):
            return table
    return None


def _rows(table, width: int) -> list[list[str]]:
    if table is None:
        return []
    out = []
    for row in table.select("tbody tr"):
        cells = [" ".join(td.get_text(" ", strip=True).split()) for td in row.find_all("td")]
        if len(cells) >= width and cells[0]:
            out.append(cells[:width])
    return out
