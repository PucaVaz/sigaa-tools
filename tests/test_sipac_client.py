from collections import OrderedDict
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
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(429)

    raw = httpx.Client(transport=httpx.MockTransport(handler))
    with SipacClient(
        raw, min_request_interval=0, retry_backoff=0.25, sleep=sleeps.append
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            client.get_public_process("23074.000001/2099-10")

    assert attempts == 2
    assert sleeps == [2.0]


def test_client_rate_limits_requests_and_reuses_short_lived_cache():
    now = 0.0
    sleeps: list[float] = []
    requests: list[httpx.Request] = []

    def clock() -> float:
        return now

    def sleep(delay: float) -> None:
        nonlocal now
        sleeps.append(delay)
        now += delay

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and "consulta_processo" in request.url.path:
            return httpx.Response(200, text=_fixture("sipac_search_form.html"))
        if request.method == "POST":
            return httpx.Response(200, text=_fixture("sipac_search_results.html"))
        return httpx.Response(200, text=_fixture("sipac_process.html"))

    raw = httpx.Client(transport=httpx.MockTransport(handler))
    cache = OrderedDict()
    with SipacClient(
        raw,
        clock=clock,
        sleep=sleep,
        min_request_interval=1.0,
        cache_ttl=10.0,
        cache_max_entries=1,
        cache=cache,
    ) as client:
        first = client.get_public_process("23074.000001/2099-10")
        first.status = "MUTATED"
        cached = client.get_public_process("23074.000001/2099-10")
        now += 11.0
        refreshed = client.get_public_process("23074.000001/2099-10")

    assert len(requests) == 6
    assert sleeps == [1.0, 1.0, 1.0, 1.0]
    assert cached.status == "ATIVO"
    assert refreshed.status == "ATIVO"
    assert len(cache) == 1
