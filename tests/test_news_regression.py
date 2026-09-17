"""News panel regressions: the remote-class notice, and failures that must not look quiet."""

from pathlib import Path

import pytest

from sigaa.errors import STAGE_PARSE
from sigaa.parsers import news as news_parser

FIXTURES = Path(__file__).parent / "fixtures"
REMOTE_ID_TURMA = "900001"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_remote_class_announcement_is_listed():
    items = news_parser.parse_news_list(_fixture("news_remote_class.html"), REMOTE_ID_TURMA)

    assert [(i.id, i.id_turma, i.date, i.title) for i in items] == [
        ("90000001", REMOTE_ID_TURMA, "13/09/2026 21:58", "Aula remota")
    ]


def test_remote_class_announcement_body_postback_targets_its_row():
    fields = news_parser.build_body_postback(
        _fixture("news_remote_class.html"), "90000001", viewstate="j_id3"
    )

    assert fields == {
        "j_id_jsp_900000001_119": "j_id_jsp_900000001_119",
        "j_id_jsp_900000001_119:j_id_jsp_900000001_120": "j_id_jsp_900000001_119:j_id_jsp_900000001_120",
        "id": "90000001",
        "javax.faces.ViewState": "j_id3",
    }


def test_remote_class_body_keeps_the_meet_link_hidden_behind_anchor_text():
    body = news_parser.parse_news_body(_fixture("news_remote_class_body.html"))

    assert "Aula remota" in body
    assert "será remota" in body
    assert "este link\n(https://meet.google.com/aaa-bbbb-ccc)" in body


def test_body_does_not_duplicate_a_link_already_written_out():
    html = '<div id="conteudo"><a href="https://meet.google.com/x">https://meet.google.com/x</a></div>'

    assert news_parser.parse_news_body(html) == "https://meet.google.com/x"


def test_declared_empty_panel_is_the_only_trusted_empty_result():
    assert news_parser.parse_news_list(_fixture("news_empty.html"), REMOTE_ID_TURMA) == []


@pytest.mark.parametrize(
    "fixture",
    ["news_panel_missing.html", "news_changed_markup.html", "auth_redirect.html"],
)
def test_unrecognized_pages_raise_a_parse_error(fixture):
    with pytest.raises(news_parser.NewsParseError) as excinfo:
        news_parser.parse_news_list(_fixture(fixture), REMOTE_ID_TURMA)

    assert excinfo.value.stage == STAGE_PARSE
    assert REMOTE_ID_TURMA in str(excinfo.value)


def test_row_without_its_own_title_does_not_borrow_the_previous_one():
    html = _fixture("news_remote_class.html").replace(
        "<br>\n\n    </div></div>",
        """<br>
				14/09/2026 07:00<br>
<form id="row2" name="row2" method="post" action="/sigaa/ava/index.jsf">
				<input type="hidden" name="id" value="90000003"/>
</form>
    </div></div>""",
    )

    items = news_parser.parse_news_list(html, REMOTE_ID_TURMA)

    assert [(i.id, i.date, i.title) for i in items] == [
        ("90000001", "13/09/2026 21:58", "Aula remota"),
        ("90000003", "14/09/2026 07:00", ""),
    ]


def test_timestamp_inside_a_title_is_not_taken_as_the_date():
    html = _fixture("news_remote_class.html").replace(
        "<i>Aula remota </i>", "<i>Prova remarcada para 20/09/2026 10:00</i>"
    )

    (item,) = news_parser.parse_news_list(html, REMOTE_ID_TURMA)

    assert item.date == "13/09/2026 21:58"
    assert item.title == "Prova remarcada para 20/09/2026 10:00"
