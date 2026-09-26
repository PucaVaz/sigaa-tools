"""Parse a turma's Plano de Curso page (Cronograma de Aulas + Avaliações)."""

from __future__ import annotations

from bs4 import BeautifulSoup

from ..models import CoursePlan, PlanEntry, PlanEvaluation
from ._common import fold
from ._variants import page_parser

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


# SIGAA's own declaration that the teacher registered no plan (observed on UFG's
# 4.2.651, 2026-09-26): the class page comes back with this warning instead of
# the plan tables. Only this exact message is trusted as "no plan".
_NO_PLAN = "esta turma ainda nao possui um plano cadastrado."


def _declares_no_plan(soup):
    warnings = [
        fold(item.get_text(" ", strip=True))
        for item in soup.select("#painel-erros ul.warning > li")
    ]
    return warnings == [_NO_PLAN] and not _recognized_plan(soup)


@page_parser(
    "plan", _declares_no_plan, empty=_declares_no_plan, name="course-plan-not-registered"
)
def _parse_no_plan(soup: BeautifulSoup, id_turma: str) -> None:
    return None


parse_course_plan.variants = (*parse_course_plan.variants, *_parse_no_plan.variants)
