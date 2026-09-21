import pytest
from sigaa.errors import ParseError
from pathlib import Path

from sigaa.parsers import participantes as participantes_parser
from sigaa.store.db import connect
from sigaa.store.repository import Repository

FIXTURES = Path(__file__).parent / "fixtures"
PARTICIPANTES = (FIXTURES / "participantes.html").read_text(encoding="utf-8")
ID_TURMA = "379201"


def test_parse_professors_reads_name_department_and_email():
    professors = participantes_parser.parse_professors(PARTICIPANTES, ID_TURMA)

    assert [p.name for p in professors] == [
        "CLARA DANTAS DE EXEMPLO",
        "SEGUNDO DOCENTE DE EXEMPLO",
    ]
    assert all(p.id_turma == ID_TURMA for p in professors)

    first = professors[0]
    assert first.department == "CI - DEPARTAMENTO DE INFORMÁTICA"
    assert first.email == "clara@ci.ufpb.br"

    # A teacher without a listed e-mail keeps the field empty rather than
    # borrowing the next labelled value.
    assert professors[1].email is None


def test_parse_professors_ignores_the_student_roster():
    professors = participantes_parser.parse_professors(PARTICIPANTES, ID_TURMA)

    names = {p.name for p in professors}
    emails = {p.email for p in professors}
    assert "ALUNO UM DE EXEMPLO" not in names
    assert "aluno.um@example.com" not in emails


def test_parse_professors_without_the_fieldset_returns_empty():
    with pytest.raises(ParseError):
        participantes_parser.parse_professors("<html></html>", ID_TURMA)


def test_replace_professors_is_idempotent_and_drops_removed_staff(tmp_path):
    conn = connect(tmp_path / "sigaa.db")
    repo = Repository(conn)
    conn.execute("INSERT INTO turma (id_turma, code, name) VALUES (?, 'X', 'X')", (ID_TURMA,))

    professors = participantes_parser.parse_professors(PARTICIPANTES, ID_TURMA)
    repo.replace_professors(ID_TURMA, professors)
    repo.replace_professors(ID_TURMA, professors)
    assert len(repo.get_professors(ID_TURMA)) == 2

    repo.replace_professors(ID_TURMA, professors[:1])
    stored = repo.get_professors(ID_TURMA)
    assert [p.name for p in stored] == ["CLARA DANTAS DE EXEMPLO"]
    assert stored[0].email == "clara@ci.ufpb.br"
    conn.close()


def test_filter_by_professor_ignores_accents_and_case():
    from types import SimpleNamespace

    from sigaa.cli import _filter_by_professor

    turmas = [SimpleNamespace(id_turma="1"), SimpleNamespace(id_turma="2")]
    professors = {
        "1": [SimpleNamespace(name="JOSÉ ANTÔNIO DA SILVA")],
        "2": [SimpleNamespace(name="MARIA CLARA")],
    }

    assert [t.id_turma for t in _filter_by_professor(turmas, professors, "jose antonio")] == ["1"]
    assert [t.id_turma for t in _filter_by_professor(turmas, professors, "Antônio")] == ["1"]
    assert _filter_by_professor(turmas, professors, "nobody") == []
