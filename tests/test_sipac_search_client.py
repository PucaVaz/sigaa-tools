from collections import OrderedDict
from pathlib import Path

import httpx

from sigaa.sipac import SipacClient, public_process_search_to_dict


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _client(handler):
    return SipacClient(
        httpx.Client(transport=httpx.MockTransport(handler)),
        min_request_interval=0,
        cache=OrderedDict(),
    )


def test_client_searches_by_name_and_returns_shared_contract():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, text=_fixture("sipac_search_form.html"))
        body = request.content.decode()
        assert "tipo_consulta=200" in body
        assert "INTERESSADO=JANE+EXAMPLE" in body
        return httpx.Response(200, text=_fixture("sipac_interested_results.html"))

    with _client(handler) as client:
        page = client.search_public_processes(name="JANE EXAMPLE")

    assert [request.method for request in requests] == ["GET", "POST"]
    data = public_process_search_to_dict(page)
    assert data["query"] == {"type": "name", "value": "JANE EXAMPLE"}
    assert data["pagination"]["page_size"] == 15
    assert data["pagination"]["returned_results"] == 1


def test_client_fetches_only_the_requested_second_page():
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, text=_fixture("sipac_search_form.html"))
        if len(requests) == 2:
            assert "tipo_consulta=300" in request.content.decode()
            return httpx.Response(200, text=_fixture("sipac_interested_results.html"))
        assert request.url.path.endswith("/processos.jsf")
        assert "documentoForm%3Adynamic_page=1" in request.content.decode()
        return httpx.Response(200, text=_fixture("sipac_interested_results.html"))

    with _client(handler) as client:
        page = client.search_public_processes(identifier="1234567", page=2)

    assert len(requests) == 3
    assert page.query_type == "identifier"
    assert page.page == 2


def test_client_search_cache_avoids_a_second_portal_round_trip():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        name = "sipac_search_form.html" if request.method == "GET" else "sipac_interested_results.html"
        return httpx.Response(200, text=_fixture(name))

    with _client(handler) as client:
        first = client.search_public_processes(name="JANE EXAMPLE")
        second = client.search_public_processes(name="JANE EXAMPLE")

    assert calls == 2
    assert first == second
    assert first is not second


def test_identifier_search_is_never_cached_in_shared_or_injected_memory():
    calls = 0
    cache = OrderedDict()

    def handler(request):
        nonlocal calls
        calls += 1
        name = "sipac_search_form.html" if request.method == "GET" else "sipac_interested_results.html"
        return httpx.Response(200, text=_fixture(name))

    client = SipacClient(
        httpx.Client(transport=httpx.MockTransport(handler)),
        min_request_interval=0,
        cache=cache,
    )
    with client:
        client.search_public_processes(identifier="1234567")
        client.search_public_processes(identifier="1234567")

    assert calls == 4
    assert cache == {}
