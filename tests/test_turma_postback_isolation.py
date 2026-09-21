"""A cached Principal page feeds exactly one Turma Virtual postback.

Chaining a second postback off the same page leaves the session on the page the
first postback opened, so SIGAA answers with whatever turma it currently sits on
-- the mechanism behind plan rows landing on the wrong turma.
"""

from sigaa.institutions import ufpb
from sigaa.client import SigaaClient
from sigaa.models import Turma

TURMA = Turma(id_turma="369279", name="SD", form_id="form", field="form:turma")

PORTAL = (
    '<html><body><form id="j_id_jsp_1_1">'
    '<input id="javax.faces.ViewState" name="javax.faces.ViewState" value="j_id1"/>'
    "</form></body></html>"
)


def _principal(marker: str) -> str:
    menu = "".join(
        f"""<a href="#" onclick="jsfcljs(document.getElementById('formMenu'),"""
        f"""{{'menu:{slug}':'menu:{slug}'}},'');">{label}</a>"""
        for label, slug in (("Ver Notas", "notas"), ("Plano de Curso", "plano"))
    )
    return (
        f'<html><body data-page="{marker}"><form id="formMenu">{menu}'
        '<input id="javax.faces.ViewState" name="javax.faces.ViewState" value="j_id2"/>'
        "</form></body></html>"
    )


class _FakeSession:
    def __init__(self):
        self.posts: list[tuple[str, dict]] = []
        self.enters = 0

    def post(self, url: str, fields: dict) -> str:
        self.posts.append((url, fields))
        if url == ufpb.PORTAL_ACTION_URL:
            self.enters += 1
            return _principal(f"re-entered-{self.enters}")
        return "<html><body>menu response</body></html>"


def _client() -> tuple[SigaaClient, _FakeSession]:
    client = SigaaClient.__new__(SigaaClient)
    session = _FakeSession()
    client._session = session
    client._portal_html = PORTAL
    client._spent_principals = set()
    return client, session


def test_first_postback_reuses_the_cached_principal_page():
    client, session = _client()
    client.get_turma_grades(TURMA, _principal("cached"))
    assert session.enters == 0
    assert session.posts[0][0] == ufpb.AVA_URL


def test_second_postback_re_enters_the_turma():
    client, session = _client()
    cached = _principal("cached")
    client.get_turma_grades(TURMA, cached)
    client.get_course_plan(TURMA, cached)

    assert session.enters == 1
    enter_url, enter_fields = session.posts[1]
    assert enter_url == ufpb.PORTAL_ACTION_URL
    assert enter_fields["idTurma"] == TURMA.id_turma


def test_news_body_after_a_menu_postback_re_enters_the_turma():
    client, session = _client()
    cached = _principal("cached")
    client.get_course_plan(TURMA, cached)
    client.get_news_body(TURMA, "1", cached)

    assert session.enters == 1


def test_a_freshly_entered_page_is_usable_for_one_postback():
    client, session = _client()
    fresh = client.enter_turma(TURMA)
    client.get_course_plan(TURMA, fresh)
    assert session.enters == 1  # only the explicit enter_turma
