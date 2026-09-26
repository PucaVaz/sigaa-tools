from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from sigaa.errors import UnrecognizedPageError
from sigaa.models import Deadline, Student, Turma
from sigaa.parsers import portal
from sigaa.parsers._variants import resolve_variant

PORTAL = (Path(__file__).parent / "fixtures/ufg/portal.html").read_text()


def _edit(css, mutate, html=PORTAL):
    soup = BeautifulSoup(html, "lxml")
    mutate(soup.select_one(css))
    return str(soup)


def test_ufg_student():
    assert portal.parse_student(PORTAL) == Student(
        matricula="000000000",
        name="ALUNO TESTE",
        course="CURSO TESTE",
        email="aluno.teste@example.org",
        semester="2026.2",
    )
    assert resolve_variant("student", PORTAL, portal.parse_student.variants).name == "ufg-student"


def test_ufg_turmas_skip_the_updates_rotator_and_hidden_rows():
    assert portal.parse_turmas(PORTAL) == [
        Turma(
            id_turma="1051979",
            name="FENÔMENOS DE TRANSPORTE",
            room="CAE-EMC-202",
            schedule_raw="35M34",
            semester="2026.2",
            field="form_acessarTurmaVirtual:turmaVirtual",
            form_id="form_acessarTurmaVirtual",
        ),
        Turma(
            id_turma="1050315",
            name="SISTEMAS DISTRIBUÍDOS 1",
            room="Sala 201 / 4ª: Lab. 200 - CAE, EMC",
            schedule_raw="24M12",
            semester="2026.2",
            field="form_acessarTurmaVirtualj_id_3:turmaVirtualj_id_3",
            form_id="form_acessarTurmaVirtualj_id_3",
        ),
    ]
    assert resolve_variant("turmas", PORTAL, portal.parse_turmas.variants).name == "ufg-turmas"


def test_ufg_deadlines():
    assert portal.parse_deadlines(PORTAL) == [
        Deadline(
            id="127274006",
            id_turma="1050315",
            kind="tarefa",
            title="Entregue Aqui sua Atividade Supervisionada 1",
            date="21/09/2026 23:59",
        )
    ]
    assert resolve_variant(
        "deadlines", PORTAL, portal.parse_deadlines.variants
    ).name == "ufg-deadlines"


def test_turma_row_of_unknown_shape_fails_loudly():
    html = _edit("#turmas-portal tbody", lambda tbody: tbody.append(
        BeautifulSoup("<tr><td>?</td><td>?</td></tr>", "lxml").tr))
    with pytest.raises(UnrecognizedPageError):
        portal.parse_turmas(html)


def test_turma_without_hidden_id_fails_loudly():
    html = _edit("#turmas-portal input[name=idTurma]", lambda node: node.decompose())
    with pytest.raises(UnrecognizedPageError):
        portal.parse_turmas(html)


def test_empty_class_table_is_not_read_as_no_classes():
    # No live empty state has been captured yet, so none is trusted.
    html = _edit("#turmas-portal table[style] tbody", lambda tbody: tbody.clear())
    with pytest.raises(UnrecognizedPageError):
        portal.parse_turmas(html)


def test_activity_row_without_a_link_fails_loudly():
    html = _edit("#avaliacao-portal tbody a", lambda node: node.decompose())
    with pytest.raises(UnrecognizedPageError):
        portal.parse_deadlines(html)


def test_empty_activity_table_is_not_read_as_no_deadlines():
    html = _edit("#avaliacao-portal tbody", lambda tbody: tbody.clear())
    with pytest.raises(UnrecognizedPageError):
        portal.parse_deadlines(html)


def test_student_without_matricula_fails_loudly():
    html = _edit("#perfil-docente > #agenda-docente tr", lambda row: row.decompose())
    with pytest.raises(UnrecognizedPageError):
        portal.parse_student(html)


TOPICS = (Path(__file__).parent / "fixtures/ufg/turma_topics.html").read_text()


def test_ufg_materials_carry_the_per_file_key():
    from sigaa.models import Material
    from sigaa.parsers import materials

    assert materials.parse_materials(TOPICS, "1051061") == [
        Material(id="3588770", id_turma="1051061", kind="file",
                 topic="Apresentação geral (10/08/2026 - 10/08/2026)", title="Plano de Ensino"),
        Material(id="3588771", id_turma="1051061", kind="file",
                 topic="Apresentação geral (10/08/2026 - 10/08/2026)",
                 title="A verdadeira história da Inteligência Artificial"),
    ]


def test_ufg_material_download_replays_the_key():
    from sigaa.parsers import materials

    field = "formAva:j_id_jsp_2083335174_266:0:listaMateriais:1:idInserirMaterialArquivo"
    assert materials.build_download_postback(TOPICS, "3588771", "j_id2") == {
        "formAva": "formAva",
        field: field,
        "id": "3588771",
        "key": "00000000000000000000000000000002",
        "javax.faces.ViewState": "j_id2",
    }


MENU = (Path(__file__).parent / "fixtures/ufg/turma_menu.html").read_text()


@pytest.mark.parametrize("label, field", [
    ("Ver Notas", "formMenu:j_id_jsp_2083335174_70"),
    ("Frequência", "formMenu:j_id_jsp_2083335174_68"),
    ("Plano de Curso", "formMenu:j_id_jsp_2083335174_48"),
    ("Participantes", "formMenu:j_id_jsp_2083335174_52"),
])
def test_class_menu_postback_replays_the_whole_form(label, field):
    assert portal.class_menu_postback(MENU, label) == {
        "formMenu": "formMenu",
        "formMenu:j_id_jsp_2083335174_44": "formMenu:j_id_jsp_2083335174_45",
        field: field,
        "javax.faces.ViewState": "j_id8",
    }


def test_class_menu_postback_is_none_for_a_missing_or_ambiguous_item():
    assert portal.class_menu_postback(MENU, "Situação dos Discentes") is None
    doubled = MENU.replace("</form>", '<a href="#" onclick="jsfcljs(document.getElementById('
                           "'formMenu'),{'formMenu:x':'formMenu:x'},'');\">Ver Notas</a></form>")
    assert portal.class_menu_postback(doubled, "Ver Notas") is None
    assert portal.class_menu_postback("<html></html>", "Ver Notas") is None


NO_PLAN = (Path(__file__).parent / "fixtures/ufg/plan_not_registered.html").read_text()


def test_class_without_a_registered_plan_is_no_plan_not_a_parse_failure():
    from sigaa.parsers import plano

    assert plano.parse_course_plan(NO_PLAN, "1051061") is None
    assert resolve_variant("plan", NO_PLAN, plano.parse_course_plan.variants).name \
        == "course-plan-not-registered"


def test_other_warnings_on_the_plan_page_stay_unrecognized():
    from sigaa.parsers import plano

    other = NO_PLAN.replace("Esta turma ainda não possui um plano cadastrado.",
                            "Ocorreu um erro inesperado.")
    with pytest.raises(UnrecognizedPageError):
        plano.parse_course_plan(other, "1051061")
