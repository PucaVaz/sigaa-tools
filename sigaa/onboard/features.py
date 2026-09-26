"""The single inventory used by capture, probe, and compatibility reports."""
from dataclasses import dataclass
from typing import Callable

from ..institutions import Capability as C, MenuLabel as M
from ..parsers import portal, grades, attendance, plano, participantes, materials, news
from ..parsers import tarefa, matricula, extensao, curriculum


@dataclass(frozen=True)
class Feature:
    key: str
    capability: C
    fetcher: Callable
    parser: Callable
    needs_turma: bool = False
    opt_in: bool = False

    def parse(self, html, turma_id=None):
        return self.parser(html, turma_id) if self.needs_turma else self.parser(html)


def _portal(client, turma):
    return client._portal()


def _principal(client, turma):
    return client.enter_turma(turma)


def _menu(label, per_class=False):
    def fetch(client, turma):
        text = client.profile.menu_labels[label]
        if per_class:
            return client._turma_menu_post(turma, text)
        return client._portal_menu_post(text)
    return fetch


def _news_body(client, turma):
    html = client.enter_turma(turma)
    items = news.parse_news_list(html, turma.id_turma)
    if not items:
        raise CaptureUnavailable("no news body to capture")
    from ..http import extract_viewstate
    fields = news.build_body_postback(html, items[0].id, extract_viewstate(html))
    if fields is None:
        raise CaptureUnavailable("news body link unavailable")
    return client._session.post(client.profile.ava_url, fields)


def _task(client, turma):
    events = client.list_deadlines()
    event = next((e for e in events if e.kind in {"tarefa", "atividade"}), None)
    if event is None:
        raise CaptureUnavailable("no task to capture")
    html = client._open_event(event.id)
    if html is None:
        raise CaptureUnavailable("task link unavailable")
    return html


def _matricula(client, turma):
    return client.open_matricula_curriculo()


def _curriculum(client, turma):
    client._session.get(client.profile.curriculum_entry_url)
    return client._session.get(client.profile.curriculum_data_url)


def _parse_news_body(html, turma_id):
    return news.parse_news_body(html)


class CaptureUnavailable(ValueError):
    """The current account has no instance of this feature to capture."""


FEATURES = (
    Feature("student", C.PORTAL, _portal, portal.parse_student),
    Feature("turmas", C.PORTAL, _portal, portal.parse_turmas),
    Feature("deadlines", C.PORTAL, _portal, portal.parse_deadlines),
    Feature("grades", C.GRADES, _menu(M.GRADES), grades.parse_grades),
    Feature(
        "extension", C.EXTENSAO, _menu(M.EXTENSION_DOCS), extensao.parse_extension_participations
    ),
    Feature("curriculum", C.CURRICULUM_JSON, _curriculum, curriculum.parse_curriculum),
    Feature(
        "turma_grades", C.GRADES, _menu(M.TURMA_GRADES, True), grades.parse_turma_grades,
        needs_turma=True,
    ),
    Feature(
        "attendance", C.ATTENDANCE, _menu(M.ATTENDANCE, True), attendance.parse_attendance,
        needs_turma=True,
    ),
    Feature(
        "plan", C.PLAN, _menu(M.PLAN, True), plano.parse_course_plan, needs_turma=True
    ),
    Feature(
        "professors", C.PARTICIPANTS, _menu(M.PARTICIPANTS, True), participantes.parse_professors,
        needs_turma=True,
    ),
    Feature("materials", C.MATERIALS, _principal, materials.parse_materials, needs_turma=True),
    Feature("news", C.NEWS, _principal, news.parse_news_list, needs_turma=True),
    Feature("news_body", C.NEWS, _news_body, _parse_news_body, needs_turma=True),
    Feature("task", C.TASKS, _task, tarefa.parse_tarefa_body),
    Feature("matricula", C.MATRICULA, _matricula, matricula.parse_open_turmas, opt_in=True),
)
