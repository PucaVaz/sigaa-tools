from pathlib import Path

import httpx
import pytest

from sigaa.sipac import SipacClient, SipacProcessNotFound, public_process_to_dict


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_client_replays_public_get_post_get_flow_without_credentials():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and "consulta_processo" in request.url.path:
            return httpx.Response(200, text=_fixture("sipac_search_form.html"))
        if request.method == "POST":
            assert b"NUM_PROTOCOLO=000001" in request.content
            return httpx.Response(200, text=_fixture("sipac_search_results.html"))
        return httpx.Response(200, text=_fixture("sipac_process.html"))

    raw = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    with SipacClient(raw) as client:
        process = client.get_public_process("23074.000001/2099-10")

    assert [request.method for request in requests] == ["GET", "POST", "GET"]
    data = public_process_to_dict(process)
    assert data["schema_version"] == 1
    assert data["source"] == "sipac_ufpb_public_portal"
    assert data["documents"][0]["kind"] == "OFÍCIO"


def test_client_reports_a_missing_process():
    def handler(request: httpx.Request) -> httpx.Response:
        name = "sipac_search_form.html" if request.method == "GET" else "sipac_search_results.html"
        text = _fixture(name).replace("23074.000001/2099-10", "23074.999999/2099-99")
        return httpx.Response(200, text=text)

    raw = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    with SipacClient(raw) as client:
        with pytest.raises(SipacProcessNotFound, match="was not found"):
            client.get_public_process("23074.000001/2099-10")
