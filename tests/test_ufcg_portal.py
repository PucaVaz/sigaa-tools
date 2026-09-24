import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from sigaa.errors import UnrecognizedPageError
from sigaa.onboard.probe import probe
from sigaa.parsers import portal

FIXTURES = Path(__file__).parent / "fixtures"
UFCG_PORTAL = (FIXTURES / "ufcg/portal_student_turmas.html").read_text()
UFCG_EMPTY = (FIXTURES / "ufcg/portal_deadlines_empty.html").read_text()
UFCG_POPULATED = (FIXTURES / "ufcg/portal_deadlines_populated.html").read_text()
UFPB_PORTAL = (FIXTURES / "portal.html").read_text()


def test_ufcg_student_variant_reads_name_and_institutional_matricula():
    student = portal.parse_student(UFCG_PORTAL)

    assert student.name == "ALUNO TESTE"
    assert student.matricula == "UFCG-TESTE"
    assert portal.parse_student.variants[0].name == "beta-student"
    assert portal.parse_student.variants[1].name == "ufcg-student"


def test_ufcg_turmas_variant_reads_class_rows_and_ignores_rotator_updates():
    turmas = portal.parse_turmas(UFCG_PORTAL)

    assert portal.parse_turmas.variants[0].name == "beta-turmas"
    assert portal.parse_turmas.variants[1].name == "ufcg-turmas"
    assert len(turmas) == 2
    assert len({turma.id_turma for turma in turmas}) == 2
    assert all(turma.id_turma and not turma.id_turma.startswith("j_id_jsp_")
               for turma in turmas)
    assert all(turma.name and turma.field and turma.form_id for turma in turmas)
    assert all(turma.room and turma.schedule_raw for turma in turmas)
    assert all("Atualização" not in turma.name for turma in turmas)


def test_ufcg_changed_student_markup_is_unrecognized():
    changed = UFCG_PORTAL.replace('class="usuario"', 'class="usuario-changed"', 1)

    with pytest.raises(UnrecognizedPageError):
        portal.parse_student(changed)


def test_ufcg_blank_matricula_is_unrecognized():
    soup = BeautifulSoup(UFCG_PORTAL, "lxml")
    soup.select_one(".matricula td:nth-of-type(2)").clear()

    with pytest.raises(UnrecognizedPageError):
        portal.parse_student(str(soup))


def test_ufcg_partial_class_table_is_unrecognized():
    soup = BeautifulSoup(UFCG_PORTAL, "lxml")
    soup.select(".simple-panel table td.descricao")[0]["class"] = ["changed"]

    with pytest.raises(UnrecognizedPageError):
        portal.parse_turmas(str(soup))


def test_ufcg_collapsed_class_row_is_unrecognized():
    soup = BeautifulSoup(UFCG_PORTAL, "lxml")
    row = soup.select(".simple-panel table tr")[1]
    for cell in row.find_all("td", recursive=False)[1:]:
        cell.decompose()

    with pytest.raises(UnrecognizedPageError):
        portal.parse_turmas(str(soup))


def test_ufcg_collapsed_class_row_with_link_is_unrecognized():
    soup = BeautifulSoup(UFCG_PORTAL, "lxml")
    row = soup.select(".simple-panel table tr")[1]
    cells = row.find_all("td", recursive=False)
    for cell in cells[1:]:
        cell.decompose()
    cells[0]["colspan"] = "4"

    with pytest.raises(UnrecognizedPageError):
        portal.parse_turmas(str(soup))


def test_ufcg_collapsed_class_row_without_description_class_is_unrecognized():
    soup = BeautifulSoup(UFCG_PORTAL, "lxml")
    row = soup.select(".simple-panel table tr")[1]
    cells = row.find_all("td", recursive=False)
    for cell in cells[1:]:
        cell.decompose()
    cells[0]["class"] = ["changed"]
    cells[0]["colspan"] = "4"

    with pytest.raises(UnrecognizedPageError):
        portal.parse_turmas(str(soup))


def test_ufcg_non_class_collapsed_row_with_id_turma_link_is_ignored():
    soup = BeautifulSoup(UFCG_PORTAL, "lxml")
    row = soup.new_tag("tr")
    cell = soup.new_tag("td", colspan="4")
    cell.append(soup.select_one(".rotator a"))
    row.append(cell)
    soup.select_one(".simple-panel table").append(row)

    turmas = portal.parse_turmas(str(soup))

    assert [turma.id_turma for turma in turmas] == [
        "TURMA-TESTE-001",
        "TURMA-TESTE-002",
    ]


def test_ufcg_portal_without_class_rows_is_not_a_confirmed_empty_state():
    soup = BeautifulSoup(UFCG_PORTAL, "lxml")
    for row in soup.select(".simple-panel table tr")[1:]:
        row.decompose()

    with pytest.raises(UnrecognizedPageError):
        portal.parse_turmas(str(soup))


def test_ufpb_portal_variants_and_results_remain_unchanged():
    student = portal.parse_student(UFPB_PORTAL)
    turmas = portal.parse_turmas(UFPB_PORTAL)

    assert portal.parse_student.variants[0].name == "beta-student"
    assert portal.parse_turmas.variants[0].name == "beta-turmas"
    assert student.name and student.matricula
    assert [turma.id_turma for turma in turmas] == ["369279", "369164"]


def test_ufcg_deadlines_empty_variant_returns_empty_for_activity_window():
    assert portal.parse_deadlines(UFCG_EMPTY) == []


def test_ufcg_deadlines_empty_variant_requires_panel_marker():
    soup = BeautifulSoup(UFCG_EMPTY, "lxml")
    soup.select_one("#avaliacao-portal p.vazio").decompose()

    with pytest.raises(UnrecognizedPageError):
        portal.parse_deadlines(str(soup))


def test_ufcg_deadlines_empty_variant_requires_marker_inside_panel():
    soup = BeautifulSoup(UFCG_EMPTY, "lxml")
    marker = soup.select_one("#avaliacao-portal p.vazio").extract()
    soup.select_one(".rotator").insert_after(marker)

    with pytest.raises(UnrecognizedPageError):
        portal.parse_deadlines(str(soup))


def test_ufcg_deadlines_empty_variant_rejects_unknown_activity_control():
    soup = BeautifulSoup(UFCG_EMPTY, "lxml")
    soup.select_one("#avaliacao-portal").append(
        BeautifulSoup('<a onclick="abrirAtividade()">Atividade</a>', "lxml").a
    )

    with pytest.raises(UnrecognizedPageError):
        portal.parse_deadlines(str(soup))


@pytest.mark.parametrize(
    "extra_html",
    [
        '<a href="/atividade">Atividade</a>',
        '<button type="button">Atividade</button>',
        "<div>Atividade com prazo</div>",
    ],
    ids=["plain-link", "button", "other-populated-content"],
)
def test_ufcg_deadlines_empty_variant_rejects_extra_panel_content(extra_html):
    soup = BeautifulSoup(UFCG_EMPTY, "lxml")
    extra = BeautifulSoup(extra_html, "lxml").find()
    soup.select_one("#avaliacao-portal").append(extra)

    with pytest.raises(UnrecognizedPageError):
        portal.parse_deadlines(str(soup))


def test_ufcg_deadlines_empty_variant_rejects_changed_heading():
    soup = BeautifulSoup(UFCG_EMPTY, "lxml")
    soup.select_one("#avaliacao-portal h4").string = "Prova amanhã"

    with pytest.raises(UnrecognizedPageError):
        portal.parse_deadlines(str(soup))


def test_ufcg_populated_portal_returns_two_assessments():
    deadlines = portal.parse_deadlines(UFCG_POPULATED)

    assert [(item.id_turma, item.kind, item.title, item.date) for item in deadlines] == [
        ("TURMA-TESTE-001", "avaliacao", "Prova 1", "Seg, 05/10/2026"),
        ("TURMA-TESTE-002", "avaliacao", "Seminário", "Qua, 07/10/2026"),
    ]
    assert len({item.id for item in deadlines}) == 2
    assert all(item.id.startswith("ufcg:portal:v1:") for item in deadlines)


def test_probe_recognizes_ufcg_portal_assessments(tmp_path):
    body = UFCG_POPULATED.encode()
    (tmp_path / "page.body").write_bytes(body)
    (tmp_path / "manifest.json").write_text(json.dumps({
        "institution": "ufcg",
        "entries": [{"feature": "deadlines", "status": "captured", "file": "page.body",
                     "sha256": hashlib.sha256(body).hexdigest(), "encoding": "utf-8"}],
    }))

    row = next(row for row in probe(tmp_path)["features"] if row["feature"] == "deadlines")
    assert (row["status"], row["count"], row["variant"]) == (
        "ok", 2, "ufcg-deadlines-populated"
    )


def test_ufcg_assessment_ids_ignore_row_order_and_unrelated_updates():
    original = {item.title: item.id for item in portal.parse_deadlines(UFCG_POPULATED)}
    soup = BeautifulSoup(UFCG_POPULATED, "lxml")
    rows = soup.select("#avaliacao-portal tbody > tr")
    rows[1].insert_before(rows[2].extract())
    soup.select_one(".rotator a").string = "Outra atualização"

    assert {item.title: item.id for item in portal.parse_deadlines(str(soup))} == original
    soup.select("#avaliacao-portal tbody > tr td small")[-1].contents[-1].replace_with(
        " Prova alterada"
    )
    changed = {item.title: item.id for item in portal.parse_deadlines(str(soup))}
    assert changed["Prova alterada"] not in original.values()
    soup.select("#avaliacao-portal tbody > tr td:nth-of-type(2)")[-1].string = (
        "Ter, 06/10/2026"
    )
    rescheduled = {item.title: item.id for item in portal.parse_deadlines(str(soup))}
    assert rescheduled["Prova alterada"] != changed["Prova alterada"]


def test_ufcg_populated_portal_rejects_row_outside_body():
    soup = BeautifulSoup(UFCG_POPULATED, "lxml")
    row = soup.select("#avaliacao-portal tbody > tr")[-1].extract()
    foot = soup.new_tag("tfoot")
    foot.append(row)
    soup.select_one("#avaliacao-portal table").append(foot)

    with pytest.raises(UnrecognizedPageError):
        portal.parse_deadlines(str(soup))


def test_ufcg_populated_portal_keeps_nested_title_in_key():
    soup = BeautifulSoup(UFCG_POPULATED, "lxml")
    title = soup.select_one("#avaliacao-portal tbody tr td small strong").next_sibling
    title.replace_with(" Prova ")
    soup.select_one("#avaliacao-portal tbody tr td small strong").next_sibling.insert_after(
        BeautifulSoup("<span>1</span>", "lxml").span
    )
    first = portal.parse_deadlines(str(soup))[0]
    soup.select_one("#avaliacao-portal tbody tr td small span").string = "2"
    second = portal.parse_deadlines(str(soup))[0]

    assert first.title == "Prova 1"
    assert first.id != second.id


@pytest.mark.parametrize("change", ["duplicate", "missing_turma", "ambiguous_turma",
                                     "missing_date", "missing_title", "bad_header",
                                     "unexpected_button", "unexpected_panel_button",
                                     "conflicting_empty_marker"])
def test_ufcg_populated_portal_rejects_ambiguous_or_malformed_rows(change):
    soup = BeautifulSoup(UFCG_POPULATED, "lxml")
    rows = soup.select("#avaliacao-portal tbody > tr")
    if change == "duplicate":
        rows[1].insert_after(BeautifulSoup(str(rows[1]), "lxml").tr)
    elif change == "missing_turma":
        soup.select(".simple-panel table tr")[-1].decompose()
    elif change == "ambiguous_turma":
        rows[2].decompose()
        soup.select(".simple-panel td.descricao a")[-1].string = "Disciplina de Teste 1"
    elif change == "missing_date":
        rows[1].find_all("td", recursive=False)[1].clear()
    elif change == "missing_title":
        rows[1].select_one("small strong").next_sibling.replace_with(" ")
    elif change == "bad_header":
        soup.select_one("#avaliacao-portal thead th").decompose()
    elif change == "unexpected_button":
        rows[1].append(BeautifulSoup("<button>Enviar</button>", "lxml").button)
    elif change == "unexpected_panel_button":
        soup.select_one("#avaliacao-portal").append(
            BeautifulSoup("<button>Enviar</button>", "lxml").button
        )
    elif change == "conflicting_empty_marker":
        soup.select_one("#avaliacao-portal").append(
            BeautifulSoup('<p class="vazio">Não há atividades cadastradas.</p>', "lxml").p
        )

    with pytest.raises(UnrecognizedPageError):
        portal.parse_deadlines(str(soup))
