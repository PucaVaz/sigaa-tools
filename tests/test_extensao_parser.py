from pathlib import Path

import pytest

from sigaa.errors import STAGE_PARSE, ParseError
from sigaa.parsers.extensao import (
    KIND_AUDIENCE,
    KIND_EXTENSION_STUDENT,
    KIND_TEAM_MEMBER,
    ExtensaoParseError,
    parse_extension_participations,
)

FIXTURES = Path(__file__).parent / "fixtures"
PAGE = (FIXTURES / "extensao_documentos.html").read_text(encoding="utf-8")
EMPTY_PAGE = (FIXTURES / "extensao_documentos_vazio.html").read_text(encoding="utf-8")
STUDENT_NAME = "FULANO DE TAL DA SILVA"


def _by_id(sigaa_id):
    return next(p for p in parse_extension_participations(PAGE) if p.sigaa_id == sigaa_id)


def test_parses_every_participation_in_page_order():
    participations = parse_extension_participations(PAGE)

    assert [(p.kind, p.sigaa_id) for p in participations] == [
        (KIND_TEAM_MEMBER, "900001"),
        (KIND_TEAM_MEMBER, "900002"),
        (KIND_TEAM_MEMBER, "900003"),
        (KIND_AUDIENCE, "900004"),
        (KIND_EXTENSION_STUDENT, "900005"),
    ]


def test_ended_team_membership_without_released_certificate_offers_no_document():
    participation = _by_id("900001")

    assert participation.year == 2098
    assert participation.action_code is None
    assert participation.title == "LIGA FICTÍCIA DE COMPUTAÇÃO"
    assert participation.category == "DISCENTE"
    assert participation.role == "ALUNO(A) VOLUNTARIO(A)"
    assert (participation.start_date, participation.end_date) == ("10/03/2098", "10/03/2099")
    assert participation.declaration_available is False
    assert participation.certificate_available is False


def test_active_team_membership_offers_only_the_declaration():
    participation = _by_id("900002")

    assert participation.title == "PROJETO IMAGINÁRIO – ROBÓTICA EDUCACIONAL"
    assert participation.declaration_available is True
    assert participation.certificate_available is False


def test_released_certificate_is_detected():
    participation = _by_id("900003")

    assert participation.role == "MONITOR(A)"
    assert participation.declaration_available is False
    assert participation.certificate_available is True


def test_audience_participation_keeps_code_registration_date_and_frequency():
    participation = _by_id("900004")

    assert participation.action_code == "PJ000-2096"
    assert participation.year == 2096
    assert participation.title == "Curso Fictício de Programação para a Comunidade"
    assert participation.category == "DISCENTE (UFPB)"
    assert participation.role == "PARTICIPANTE"
    assert participation.registered_on == "20/06/2096"
    assert participation.frequency == "75%"
    assert participation.start_date is None


def test_extension_student_declaration_is_detected_without_a_link_id():
    participation = _by_id("900005")

    assert participation.action_code == "PJ001-2099"
    assert participation.role == "VOLUNTÁRIO"
    assert participation.status == "ATIVO"
    assert (participation.start_date, participation.end_date) == ("15/02/2099", "31/12/2099")
    assert participation.declaration_available is True
    assert participation.certificate_available is False


def test_student_name_is_never_returned():
    for participation in parse_extension_participations(PAGE):
        assert STUDENT_NAME.casefold() not in repr(participation).casefold()


def test_recognized_page_without_tables_means_no_participations():
    assert parse_extension_participations(EMPTY_PAGE) == []


def test_unrecognized_page_is_a_parse_error_not_an_empty_list():
    with pytest.raises(ExtensaoParseError) as exc_info:
        parse_extension_participations("<html><body><p>Sessão expirada</p></body></html>")

    assert isinstance(exc_info.value, ParseError)
    assert exc_info.value.stage == STAGE_PARSE


def test_missing_column_is_a_parse_error():
    changed = PAGE.replace("<th>Situa&#231;&#227;o</th>", "<th>Estado</th>")

    with pytest.raises(ExtensaoParseError, match="missing columns: situacao"):
        parse_extension_participations(changed)


def test_unknown_table_is_a_parse_error():
    changed = PAGE.replace("como p&#250;blico alvo", "como avaliador")

    with pytest.raises(ExtensaoParseError, match="unknown extension participation table"):
        parse_extension_participations(changed)


def test_action_block_without_a_participation_row_is_a_parse_error():
    start = PAGE.index("<td> Fulano de Tal da Silva </td>")
    end = PAGE.index("</tr>", start)
    changed = PAGE[:start] + PAGE[end:]

    with pytest.raises(ExtensaoParseError, match="no participation row"):
        parse_extension_participations(changed)
