from __future__ import annotations

import httpx

from sigaa.client import SigaaClient


def test_sigaa_client_accepts_a_custom_http_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeHttpClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(httpx, "Client", FakeHttpClient)
    timeout = httpx.Timeout(60.0, connect=10.0)

    SigaaClient("student", "secret", timeout=timeout)

    assert captured["timeout"] is timeout
    assert captured["follow_redirects"] is True
