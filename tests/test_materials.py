from pathlib import Path

from sigaa.parsers import materials as materials_parser

FIXTURES = Path(__file__).parent / "fixtures"
MATERIALS = (FIXTURES / "materials.html").read_text(encoding="utf-8")
ID_TURMA = "369279"


def test_parse_materials_files_and_links():
    items = materials_parser.parse_materials(MATERIALS, ID_TURMA)
    assert len(items) == 4

    files = [m for m in items if m.kind == "file"]
    assert [m.id for m in files] == ["1012156", "1012158", "1020982"]
    assert all(m.id_turma == ID_TURMA for m in items)

    first = files[0]
    assert first.title == "Slides sobre introdução - I"
    assert first.topic == "Visão geral e introdução (28/04/2026 - 05/05/2026)"
    assert first.url is None

    link = next(m for m in items if m.kind == "link")
    assert link.url == "https://example.sharepoint.com/intro-i"
    assert link.id == link.url


def test_build_download_postback_matches_material_id():
    fields = materials_parser.build_download_postback(MATERIALS, "1020982", "j_id3")
    assert fields["formAva"] == "formAva"
    assert fields["id"] == "1020982"
    assert fields["javax.faces.ViewState"] == "j_id3"
    field_key = "formAva:t:2:listaMateriais:0:idInserirMaterialArquivo"
    assert fields[field_key] == field_key


def test_build_download_postback_unknown_id_returns_none():
    assert materials_parser.build_download_postback(MATERIALS, "999999", "j_id3") is None


def test_filename_from_content_type():
    name = materials_parser.filename_for("Slides sobre introdução - I", "application/pdf", None)
    assert name == "Slides sobre introdução - I.pdf"


def test_filename_prefers_content_disposition():
    name = materials_parser.filename_for(
        "ignored", "application/pdf", 'attachment; filename="lista 1.pdf"'
    )
    assert name == "lista 1.pdf"


def test_filename_sanitizes_path_separators():
    name = materials_parser.filename_for("a/b:c", "application/pdf", None)
    assert "/" not in name and ":" not in name
    assert name.endswith(".pdf")
