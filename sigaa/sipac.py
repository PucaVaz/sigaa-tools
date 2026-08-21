"""Public SIPAC/UFPB client and shared process presentation contract."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import threading
import time
from typing import Callable
from urllib.parse import urljoin, urlparse

import httpx

from .config import USER_AGENT
from .models import SipacProcess, SipacProcessSearchPage
from .parsers.sipac import (
    PUBLIC_HOST,
    SipacParseError,
    build_interested_search_payload,
    build_process_search_payload,
    build_results_page_request,
    normalize_interested_search,
    normalize_process_number,
    parse_process_detail_url,
    parse_process_search_page,
    parse_public_process,
)

PROCESS_SEARCH_URL = f"{PUBLIC_HOST}/public/jsp/processos/consulta_processo.jsf"
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_TRANSIENT_STATUSES = {429, 500, 502, 503, 504}
_MAX_REDIRECTS = 5
_MAX_AUTOMATIC_RETRY_AFTER = 30.0
_MAX_SHARED_COOLDOWN = 3600.0


class _RateLimiter:
    def __init__(
        self,
        interval: float,
        *,
        clock: Callable[[], float],
        sleep: Callable[[float], None],
    ):
        self.interval = max(0.0, interval)
        self.clock = clock
        self.sleep = sleep
        self.last_request_at: float | None = None
        self.blocked_until = 0.0
        self.lock = threading.Lock()

    def wait(self) -> None:
        while True:
            with self.lock:
                now = self.clock()
                embargo_delay = self.blocked_until - now
                if self.last_request_at is not None:
                    interval_delay = self.interval - (now - self.last_request_at)
                else:
                    interval_delay = 0.0
                delay = max(embargo_delay, interval_delay)
                if delay <= 0:
                    self.last_request_at = now
                    return
            # Do not hold the lock while sleeping: a concurrent 429 must be able
            # to extend the embargo before this request is allowed through.
            self.sleep(delay)

    def defer(self, delay: float) -> None:
        """Apply one server-requested cooldown to every client sharing this limiter."""
        with self.lock:
            self.blocked_until = max(self.blocked_until, self.clock() + delay)


_SHARED_RATE_LIMITER = _RateLimiter(
    0.25,
    clock=time.monotonic,
    sleep=time.sleep,
)


class SipacProcessNotFound(LookupError):
    pass


class SipacClient:
    """Read-only client for SIPAC's unauthenticated public portal."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        min_request_interval: float = 0.25,
        max_retries: int = 2,
        retry_backoff: float = 0.25,
    ):
        owns_client = client is None
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=False,
            timeout=30.0,
        )
        self._clock = clock
        self._sleep = sleep
        self._max_retries = max(0, max_retries)
        self._retry_backoff = max(0.0, retry_backoff)
        self._rate_limiter = (
            _SHARED_RATE_LIMITER
            if owns_client
            and clock is time.monotonic
            and sleep is time.sleep
            and min_request_interval == 0.25
            else _RateLimiter(
                min_request_interval,
                clock=clock,
                sleep=sleep,
            )
        )

    def get_public_process(self, process_number: str) -> SipacProcess:
        number = normalize_process_number(process_number)
        form = self._request("GET", PROCESS_SEARCH_URL)
        form.raise_for_status()
        payload = build_process_search_payload(form.text, number)

        results = self._request("POST", PROCESS_SEARCH_URL, data=payload)
        results.raise_for_status()
        detail_url = parse_process_detail_url(results.text, number)
        if detail_url is None:
            raise SipacProcessNotFound(f"SIPAC process {number} was not found")

        detail = self._request("GET", detail_url)
        detail.raise_for_status()
        process = parse_public_process(detail.text, public_url=detail_url)
        if process.number != number:
            raise SipacParseError("SIPAC returned a different process than requested")
        return process

    def search_public_processes(
        self,
        *,
        name: str | None = None,
        identifier: str | None = None,
        page: int = 1,
    ) -> SipacProcessSearchPage:
        if page < 1:
            raise ValueError("SIPAC search page must be 1 or greater")
        query_type, query = normalize_interested_search(
            name=name, identifier=identifier
        )
        form = self._request("GET", PROCESS_SEARCH_URL)
        form.raise_for_status()
        payload_type, payload_query, payload = build_interested_search_payload(
            form.text, name=name, identifier=identifier
        )
        if (payload_type, payload_query) != (query_type, query):
            raise SipacParseError("SIPAC search criteria changed while building payload")

        results = self._request("POST", PROCESS_SEARCH_URL, data=payload)
        results.raise_for_status()
        results_html = results.text
        if page > 1:
            page_url, page_payload = build_results_page_request(results_html, page)
            results = self._request("POST", page_url, data=page_payload)
            results.raise_for_status()
            results_html = results.text
        parsed = parse_process_search_page(
            results_html, query_type=query_type, query=query, page=page
        )
        return parsed

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        current_method = method
        current_url = self._validated_url(url)
        current_kwargs = kwargs
        for redirect_count in range(_MAX_REDIRECTS + 1):
            response = self._request_with_retries(
                current_method,
                current_url,
                **current_kwargs,
            )
            if response.status_code not in _REDIRECT_STATUSES:
                return response
            if redirect_count == _MAX_REDIRECTS:
                response.close()
                raise httpx.TooManyRedirects(
                    "SIPAC exceeded the redirect limit",
                    request=response.request,
                )
            location = response.headers.get("location")
            if not location:
                return response
            next_url = self._validated_url(urljoin(str(response.url), location))
            if response.status_code == 303 or (
                response.status_code in {301, 302} and current_method != "GET"
            ):
                current_method = "GET"
                current_kwargs = {}
            response.close()
            current_url = next_url
        raise AssertionError("unreachable")  # pragma: no cover

    def _request_with_retries(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            self._rate_limiter.wait()
            retry_delay = self._retry_backoff * (2**attempt)
            try:
                response = self._client.request(
                    method,
                    url,
                    follow_redirects=False,
                    **kwargs,
                )
            except httpx.TransportError:
                if attempt == self._max_retries:
                    raise
            else:
                if response.status_code not in _TRANSIENT_STATUSES:
                    return response
                if response.status_code == 429:
                    retry_after = self._retry_after_seconds(response)
                    if retry_after is None:
                        return response
                    self._rate_limiter.defer(retry_after)
                    if (
                        attempt == self._max_retries
                        or retry_after > _MAX_AUTOMATIC_RETRY_AFTER
                    ):
                        return response
                    response.close()
                    continue
                if attempt == self._max_retries:
                    return response
                response.close()
            self._sleep(retry_delay)
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float | None:
        header = response.headers.get("retry-after")
        if header is None:
            return None
        if header.isascii() and header.isdecimal():
            if len(header) > 10:
                return None
            requested = float(int(header))
        else:
            try:
                retry_at = parsedate_to_datetime(header)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                requested = (retry_at - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return None
        requested = max(0.0, requested)
        return requested if requested <= _MAX_SHARED_COOLDOWN else None

    @staticmethod
    def _validated_url(url: str) -> str:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "sipac.ufpb.br"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
        ):
            raise ValueError("SIPAC refused a redirect outside its public HTTPS host")
        return url

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


def public_process_search_to_dict(page: SipacProcessSearchPage) -> dict:
    """Stable JSON contract shared by SIPAC search CLI and MCP tool."""
    return {
        "schema_version": 1,
        "source": "sipac_ufpb_public_portal",
        "query": {"type": page.query_type, "value": page.query},
        "pagination": {
            "page": page.page,
            "total_pages": page.total_pages,
            "total_results": page.total_results,
            "returned_results": len(page.results),
            "page_size": 15,
        },
        "results": [asdict(result) for result in page.results],
    }
