from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from sigaa.errors import UnrecognizedPageError
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


def test_parse_materials_skips_tasks_forums_pages_and_plain_items():
    mixed = (FIXTURES / "materials_mixed_items.html").read_text(encoding="utf-8")

    items = materials_parser.parse_materials(mixed, ID_TURMA)

    assert [(m.kind, m.title) for m in items] == [
        ("file", "Slides sobre introdução - I"),
        ("link", "Intro - I (apresentação) (Link Externo)"),
    ]


def test_topics_with_only_other_items_are_an_empty_material_list():
    soup = BeautifulSoup((FIXTURES / "materials_mixed_items.html").read_text(), "lxml")
    for anchor in soup.select("a"):
        if "idInserirMaterialArquivo" in anchor.get("onclick", "") or anchor["href"].startswith("http"):
            anchor.find_parent("div", class_="item").decompose()

    assert materials_parser.parse_materials(str(soup), ID_TURMA) == []


def test_a_file_item_that_cannot_be_read_still_raises():
    broken = MATERIALS.replace("'id':'1012158'", "'id':'not-a-number'")

    with pytest.raises(UnrecognizedPageError):
        materials_parser.parse_materials(broken, ID_TURMA)


def test_class_page_without_topics_has_no_materials():
    principal = (FIXTURES / "news_remote_class.html").read_text(encoding="utf-8")

    assert materials_parser.parse_materials(principal, ID_TURMA) == []
