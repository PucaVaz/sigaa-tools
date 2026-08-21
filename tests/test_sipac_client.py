from pathlib import Path

import httpx
import pytest

from sigaa.parsers.sipac import SipacParseError
from sigaa.sipac import (
    PROCESS_SEARCH_URL,
    SipacClient,
    SipacProcessNotFound,
    public_process_to_dict,
)


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
        if request.method == "GET":
            text = _fixture(name)
        else:
            text = (
                "<html><body>Nenhum processo encontrado de acordo com os "
                "parâmetros de busca passados.</body></html>"
            )
        return httpx.Response(200, text=text)

    raw = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    with SipacClient(raw) as client:
        with pytest.raises(SipacProcessNotFound, match="was not found"):
            client.get_public_process("23074.000001/2099-10")


def test_client_does_not_report_unexpected_result_html_as_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=_fixture("sipac_search_form.html"))
        return httpx.Response(200, text="<html><body>Maintenance</body></html>")

    raw = httpx.Client(transport=httpx.MockTransport(handler))
    with SipacClient(raw, min_request_interval=0) as client:
        with pytest.raises(SipacParseError, match="matching row or empty marker"):
            client.get_public_process("23074.000001/2099-10")


def test_client_rejects_redirects_outside_the_public_https_host():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"})

    raw = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    with SipacClient(raw, min_request_interval=0) as client:
        with pytest.raises(ValueError, match="outside its public HTTPS host"):
            client.get_public_process("23074.000001/2099-10")


def test_client_follows_same_host_https_redirects_manually():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/redirected-form":
            return httpx.Response(200, text=_fixture("sipac_search_form.html"))
        if request.method == "GET" and "consulta_processo" in request.url.path:
            return httpx.Response(302, headers={"Location": "/redirected-form"})
        if request.method == "POST":
            return httpx.Response(200, text=_fixture("sipac_search_results.html"))
        return httpx.Response(200, text=_fixture("sipac_process.html"))

    raw = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    with SipacClient(raw, min_request_interval=0) as client:
        process = client.get_public_process("23074.000001/2099-10")

    assert process.number == "23074.000001/2099-10"
    assert requests[1].url == httpx.URL("https://sipac.ufpb.br/redirected-form")


def test_client_retries_transient_responses_with_bounded_backoff():
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.method == "GET" and "consulta_processo" in request.url.path:
            attempts += 1
            if attempts < 3:
                return httpx.Response(503)
            return httpx.Response(200, text=_fixture("sipac_search_form.html"))
        if request.method == "POST":
            return httpx.Response(200, text=_fixture("sipac_search_results.html"))
        return httpx.Response(200, text=_fixture("sipac_process.html"))

    raw = httpx.Client(transport=httpx.MockTransport(handler))
    with SipacClient(
        raw,
        min_request_interval=0,
        retry_backoff=0.5,
        sleep=sleeps.append,
    ) as client:
        client.get_public_process("23074.000001/2099-10")

    assert attempts == 3
    assert sleeps == [0.5, 1.0]


def test_client_respects_retry_after_and_does_not_retry_bare_429():
    attempts = 0
    now = 0.0
    sleeps: list[float] = []

    def clock() -> float:
        return now

    def sleep(delay: float) -> None:
        nonlocal now
        sleeps.append(delay)
        now += delay

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(429)

    raw = httpx.Client(transport=httpx.MockTransport(handler))
    with SipacClient(
        raw,
        clock=clock,
        min_request_interval=0,
        retry_backoff=0.25,
        sleep=sleep,
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            client.get_public_process("23074.000001/2099-10")

    assert attempts == 2
    assert sleeps == pytest.approx([2.0], abs=0.01)


def test_client_does_not_retry_before_a_long_retry_after_expires():
    now = 0.0
    sleeps: list[float] = []
    attempts = 0

    def clock() -> float:
        return now

    def sleep(delay: float) -> None:
        nonlocal now
        sleeps.append(delay)
        now += delay

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "120"})
        return httpx.Response(200, text="ok")

    raw = httpx.Client(transport=httpx.MockTransport(handler))
    with SipacClient(
        raw,
        clock=clock,
        sleep=sleep,
        min_request_interval=0,
        max_retries=2,
    ) as client:
        first = client._request("GET", PROCESS_SEARCH_URL)
        assert first.status_code == 429
        assert attempts == 1
        second = client._request("GET", PROCESS_SEARCH_URL)

    assert second.status_code == 200
    assert attempts == 2
    assert sleeps == [120.0]


@pytest.mark.parametrize("retry_after", ["1e309", "inf", "3601", "12.5"])
def test_invalid_or_excessive_retry_after_does_not_poison_the_limiter(retry_after):
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": retry_after})

    raw = httpx.Client(transport=httpx.MockTransport(handler))
    with SipacClient(raw, min_request_interval=0, sleep=sleeps.append) as client:
        response = client._request("GET", PROCESS_SEARCH_URL)

    assert response.status_code == 429
    assert attempts == 1
    assert sleeps == []


def test_client_rate_limits_each_request_without_retaining_results():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and "consulta_processo" in request.url.path:
            return httpx.Response(200, text=_fixture("sipac_search_form.html"))
        if request.method == "POST":
            return httpx.Response(200, text=_fixture("sipac_search_results.html"))
        return httpx.Response(200, text=_fixture("sipac_process.html"))

    raw = httpx.Client(transport=httpx.MockTransport(handler))
    with SipacClient(raw, min_request_interval=0) as client:
        client.get_public_process("23074.000001/2099-10")
        client.get_public_process("23074.000001/2099-10")

    assert len(requests) == 6
