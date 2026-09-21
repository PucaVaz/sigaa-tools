"""Parse a turma's Plano de Curso page (Cronograma de Aulas + Avaliações)."""

from __future__ import annotations

from bs4 import BeautifulSoup

from ._variants import page_parser
from ._common import fold

from ..models import CoursePlan, PlanEntry, PlanEvaluation


_SCHEDULE_CAPTION = "cronograma de aulas"
_EVALUATIONS_CAPTION = "avalia"
# Column labels the positional reader relies on, in order.
_SCHEDULE_COLUMNS = ["inicio", "fim", "descricao"]
_EVALUATION_COLUMNS = ["data", "descricao"]


def _recognized_plan(soup):
    return (
        _table_by_caption(soup, _SCHEDULE_CAPTION) is not None
        or _table_by_caption(soup, _EVALUATIONS_CAPTION) is not None
    )


def _valid_plan(result, soup):
    """Only the two tables the parser reads are checked. Rows it skips (short
    rows, rows without a first cell) stay skipped; a table that labels its
    columns must label the ones read by position."""
    for caption, columns in (
        (_SCHEDULE_CAPTION, _SCHEDULE_COLUMNS),
        (_EVALUATIONS_CAPTION, _EVALUATION_COLUMNS),
    ):
        table = _table_by_caption(soup, caption)
        headers = [fold(th.get_text(" ", strip=True)) for th in table.select("th")] if table else []
        if headers and headers[: len(columns)] != columns:
            return False
    return True


@page_parser("plan", _recognized_plan, validate=_valid_plan, name="course-plan-tables")
def parse_course_plan(soup: BeautifulSoup, id_turma: str) -> CoursePlan | None:
    """Extract schedule and evaluation dates. Returns None if no plan tables."""
    cronograma = _table_by_caption(soup, _SCHEDULE_CAPTION)
    avaliacoes = _table_by_caption(soup, _EVALUATIONS_CAPTION)
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
