from pathlib import Path

import pytest

from sigaa.parsers.sipac import (
    SipacParseError,
    build_interested_search_payload,
    build_results_page_request,
    normalize_interested_search,
    parse_process_search_page,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_interested_search_payload_supports_name_and_identifier():
    html = _fixture("sipac_search_form.html")
    kind, query, payload = build_interested_search_payload(html, name="  Jane   Example ")
    assert (kind, query) == ("name", "Jane Example")
    assert payload["tipo_consulta"] == "200"
    assert payload["INTERESSADO"] == "Jane Example"
    assert payload["CPF_CNPJ"] == ""

    kind, query, payload = build_interested_search_payload(html, identifier=" 1234567 ")
    assert (kind, query) == ("identifier", "1234567")
    assert payload["tipo_consulta"] == "300"
    assert payload["INTERESSADO"] == ""
    assert payload["CPF_CNPJ"] == "1234567"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "exactly one"),
        ({"name": "Jane", "identifier": "123"}, "exactly one"),
        ({"name": " x "}, "3 to 200"),
        ({"identifier": "123.456"}, "digits only"),
        ({"identifier": "1" * 15}, "digits only"),
    ],
)
def test_interested_search_rejects_ambiguous_or_unsafe_input(kwargs, message):
    with pytest.raises(ValueError, match=message):
        normalize_interested_search(**kwargs)


def test_parse_interested_results_and_pagination_metadata():
    page = parse_process_search_page(
        _fixture("sipac_interested_results.html"),
        query_type="name",
        query="JANE EXAMPLE",
        page=1,
    )
    assert page.total_results == 31
    assert page.total_pages == 3
    assert page.results[0].number == "23074.000001/2099-10"
    assert page.results[0].interested_parties == ["JANE EXAMPLE", "OTHER UNIT"]
    assert page.results[0].public_url.endswith("processo_detalhado.jsf?id=123")


def test_build_results_page_request_replays_dynamic_jsf_fields():
    url, payload = build_results_page_request(
        _fixture("sipac_interested_results.html"), 2
    )
    assert url == "https://sipac.ufpb.br/public/jsp/processos/processos.jsf"
    assert payload["javax.faces.ViewState"] == "j_id4"
    assert payload["documentoForm:dynamic_page"] == "1"


def test_pagination_rejects_out_of_range_and_external_action():
    html = _fixture("sipac_interested_results.html")
    with pytest.raises(ValueError, match="between 1 and 3"):
        build_results_page_request(html, 4)
    with pytest.raises(SipacParseError, match="not safe"):
        build_results_page_request(html.replace(
            "/public/jsp/processos/processos.jsf", "https://evil.example/processos.jsf"
        ), 2)


def test_empty_search_page_is_a_valid_zero_result_contract():
    page = parse_process_search_page(
        (
            "<html><body><center>Nenhum processo encontrado de acordo com os "
            "parâmetros de busca passados.</center></body></html>"
        ),
        query_type="name",
        query="NOBODY",
        page=1,
    )
    assert page.total_results == 0
    assert page.total_pages == 0
    assert page.results == []


@pytest.mark.parametrize(
    "html",
    [
        "<html><body>Manutenção temporária</body></html>",
        "<html><body><form id='loginForm'></form></body></html>",
        "<html><body>0 Registro(s) Encontrado(s)</body></html>",
        "<html><body>2 Registro(s) Encontrado(s)</body></html>",
    ],
)
def test_search_page_does_not_misreport_portal_failures_as_zero_results(html):
    with pytest.raises(SipacParseError):
        parse_process_search_page(
            html,
            query_type="name",
            query="JANE EXAMPLE",
            page=1,
        )
