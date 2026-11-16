from pathlib import Path

import pytest

from sigaa.errors import ParseError
from sigaa.parsers import tarefa as tarefa_parser


FIXTURES = Path(__file__).parent / "fixtures"
TAREFA = (FIXTURES / "tarefa.html").read_text(encoding="utf-8")


def _task_with_submit() -> str:
    return TAREFA.replace(
        '    </form>',
        '    <input name="formResponder:enviar" type="submit" value="Enviar tarefa"/>\n    </form>',
    )


def test_build_submission_form_keeps_hidden_fields_file_field_and_submit_control():
    submission = tarefa_parser.build_submission_form(_task_with_submit())

    assert submission.action == "/sigaa/ava/TarefaTurma/enviarTarefa.jsf"
    assert submission.fields == {
        "formResponder:id": "11112222",
        "javax.faces.ViewState": "abc123",
        "formResponder:enviar": "Enviar tarefa",
    }
    assert submission.file_field == "formResponder:idArquivo"


def test_build_submission_form_refuses_a_task_page_without_explicit_submit_control():
    with pytest.raises(ParseError, match="submit control"):
        tarefa_parser.build_submission_form(TAREFA)
