"""Public SIPAC/UFPB client and shared process presentation contract."""

from __future__ import annotations

from dataclasses import asdict

import httpx

from .config import USER_AGENT
from .models import SipacProcess
from .parsers.sipac import (
    PUBLIC_HOST,
    SipacParseError,
    build_process_search_payload,
    normalize_process_number,
    parse_process_detail_url,
    parse_public_process,
)

PROCESS_SEARCH_URL = f"{PUBLIC_HOST}/public/jsp/processos/consulta_processo.jsf"


class SipacProcessNotFound(LookupError):
    pass


class SipacClient:
    """Read-only client for SIPAC's unauthenticated public portal."""

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=30.0,
        )

    def get_public_process(self, process_number: str) -> SipacProcess:
        number = normalize_process_number(process_number)
        form = self._client.get(PROCESS_SEARCH_URL)
        form.raise_for_status()
        payload = build_process_search_payload(form.text, number)

        results = self._client.post(PROCESS_SEARCH_URL, data=payload)
        results.raise_for_status()
        detail_url = parse_process_detail_url(results.text, number)
        if detail_url is None:
            raise SipacProcessNotFound(f"SIPAC process {number} was not found")

        detail = self._client.get(detail_url)
        detail.raise_for_status()
        process = parse_public_process(detail.text, public_url=detail_url)
        if process.number != number:
            raise SipacParseError("SIPAC returned a different process than requested")
        return process

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SipacClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def public_process_to_dict(process: SipacProcess) -> dict:
    """Stable JSON contract shared by the SIPAC CLI and MCP tool."""
    data = asdict(process)
    return {
        "schema_version": 1,
        "source": "sipac_ufpb_public_portal",
        **data,
    }
