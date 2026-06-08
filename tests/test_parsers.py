from pathlib import Path

from sigaa.parsers import news as news_parser
from sigaa.parsers import portal as portal_parser
from sigaa.parsers.schedule import decode_schedule

FIXTURES = Path(__file__).parent / "fixtures"
PORTAL = (FIXTURES / "portal.html").read_text(encoding="utf-8")
TURMA = (FIXTURES / "turma.html").read_text(encoding="utf-8")


def test_parse_student():
    student = portal_parser.parse_student(PORTAL)
    assert student.name == "FULANO DE TAL SILVA"
    assert student.matricula == "12345678901"
    assert student.semester == "2026.1"
    assert student.course == "CIÊNCIA DA COMPUTAÇÃO - GRADUAÇÃO"
    assert student.email == "fulano@academico.ufpb.br"


def test_parse_turmas():
    turmas = portal_parser.parse_turmas(PORTAL)
    assert len(turmas) == 2
    sd = next(t for t in turmas if t.id_turma == "369279")
    assert sd.code == "DSCO00022"
    assert sd.name == "SISTEMAS DISTRIBUÍDOS"
    assert sd.room == "SALA 1"
    assert sd.schedule_raw == "35M45"
    assert sd.field == "j_id_jsp_111111111_1:link0"
    assert sd.form_id == "j_id_jsp_111111111_1"


def test_find_menu_field_matches_decoded_text():
    field = portal_parser.find_menu_field(PORTAL, "SISTEMAS DISTRIBUÍDOS")
    assert field == "j_id_jsp_111111111_1:link0"
    assert portal_parser.find_menu_field(PORTAL, "Nonexistent Item") is None


def test_find_menu_field_handles_formatted_jsfcljs_params():
    html = """
    <a href="#" onclick="
      if (typeof jsfcljs == 'function') {
        jsfcljs(
          document.getElementById('portal'),
          { 'portal:link0' : 'portal:link0', 'idTurma' : '369279' },
          ''
        );
      }
      return false
    ">SISTEMAS DISTRIBUÍDOS</a>
    """

    assert portal_parser.find_menu_field(html, "SISTEMAS DISTRIBUÍDOS") == "portal:link0"


def test_parse_news_list():
    items = news_parser.parse_news_list(TURMA, id_turma="369279")
    assert [n.id for n in items] == ["46214565", "46003254"]
    assert items[0].date == "03/06/2026 10:57"
    assert items[0].title == "Feriado (04/06)"
    assert items[1].title.startswith("Alteração de data")


def test_build_body_postback():
    fields = news_parser.build_body_postback(TURMA, "46214565", viewstate="j_id2")
    assert fields["id"] == "46214565"
    assert fields["news_form_0"] == "news_form_0"
    assert fields["javax.faces.ViewState"] == "j_id2"
    assert fields["news_form_0:view"] == "news_form_0:view"


def test_build_body_postback_missing():
    assert news_parser.build_body_postback(TURMA, "does-not-exist", "j_id2") is None


def test_decode_schedule_single():
    [s] = decode_schedule("6M2345")
    assert s.days == [6]
    assert s.shift == "M"
    assert s.slots == [2, 3, 4, 5]


def test_decode_schedule_multi():
    schedules = decode_schedule("7M1 35N34")
    assert [s.shift for s in schedules] == ["M", "N"]
    assert schedules[1].days == [3, 5]
    assert schedules[1].slots == [3, 4]


def test_decode_schedule_strips_date_range():
    [s] = decode_schedule("7M2345 (27/04/2026 - 13/08/2026)")
    assert s.days == [7]
    assert s.slots == [2, 3, 4, 5]
