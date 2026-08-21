from pathlib import Path

import pytest

from sigaa.parsers.sipac import (
    SipacParseError,
    build_process_search_payload,
    normalize_process_number,
    parse_process_detail_url,
    parse_public_process,
)


FIXTURES = Path(__file__).parent / "fixtures"


def test_normalize_process_number_accepts_whitespace_and_rejects_other_shapes():
    assert normalize_process_number(" 23074.000001 / 2099 - 10 ") == "23074.000001/2099-10"
    with pytest.raises(ValueError, match="00000.000000/0000-00"):
        normalize_process_number("23074-1")


def test_build_search_payload_replays_dynamic_jsf_fields():
    html = (FIXTURES / "sipac_search_form.html").read_text(encoding="utf-8")
    payload = build_process_search_payload(html, "23074.000001/2099-10")

    assert payload["javax.faces.ViewState"] == "j_id4"
    assert payload["processoForm:dynamic_submit"] == "Consultar Processo"
    assert payload["RADICAL_PROTOCOLO"] == "23074"
    assert payload["NUM_PROTOCOLO"] == "000001"
    assert payload["ANO_PROTOCOLO"] == "2099"
    assert payload["DV_PROTOCOLO"] == "10"


def test_parse_search_result_selects_the_matching_public_detail_url():
    html = (FIXTURES / "sipac_search_results.html").read_text(encoding="utf-8")

    assert parse_process_detail_url(html, "23074.000001/2099-10") == (
        "https://sipac.ufpb.br/public/jsp/processos/processo_detalhado.jsf?id=123"
    )
    with pytest.raises(SipacParseError, match="matching row or empty marker"):
        parse_process_detail_url(html, "23074.999999/2099-99")

    empty = (
        "<html><body>Nenhum processo encontrado de acordo com os parâmetros "
        "de busca passados.</body></html>"
    )
    assert parse_process_detail_url(empty, "23074.999999/2099-99") is None


def test_parse_public_process_returns_all_public_sections():
    html = (FIXTURES / "sipac_process.html").read_text(encoding="utf-8")
    process = parse_public_process(
        html,
        public_url="https://sipac.ufpb.br/public/jsp/processos/processo_detalhado.jsf?id=123",
    )

    assert process.number == "23074.000001/2099-10"
    assert process.detailed_subject == "PROCESSO SINTÉTICO PARA TESTES"
    assert process.status == "ATIVO"
    assert process.interested_parties[0].name == "UNIDADE DE TESTE"
    assert len(process.documents) == 2
    assert process.documents[0].download_url == (
        "https://sipac.ufpb.br/public/verArquivoDocumento?idArquivo=1"
    )
    assert process.documents[1].download_url == (
        "https://sipac.ufpb.br/public/jsp/processos/"
        "documento_visualizacao.jsf?idDoc=2"
    )
    assert process.movements[0].urgent is False
    assert process.status_changes[0].note == "Teste."
    assert process.attached_files[0].download_url == (
        "https://sipac.ufpb.br/public/arquivo/1"
    )


@pytest.mark.parametrize(
    "unsafe_onclick",
    [
        "window.open('/public/jsp/processos/documento_visualizacao.jsf?idDoc=invalid')",
        "window.open('https://example.com/public/jsp/processos/"
        "documento_visualizacao.jsf?idDoc=2')",
    ],
)
def test_parse_public_process_rejects_unsafe_document_view_onclick(unsafe_onclick):
    html = (FIXTURES / "sipac_process.html").read_text(encoding="utf-8")
    html = html.replace(
        "window.open('/public/jsp/processos/documento_visualizacao.jsf?idDoc=2',"
        "'','width=800,height=600, scrollbars');",
        unsafe_onclick,
    )

    process = parse_public_process(
        html,
        public_url="https://sipac.ufpb.br/public/jsp/processos/"
        "processo_detalhado.jsf?id=123",
    )

    assert process.documents[1].download_url is None
