"""Public SIPAC/UFPB client and shared process presentation contract."""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import threading
import time
from typing import Any, Callable, MutableMapping
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
_DEFAULT_CACHE_TTL = 60.0
_DEFAULT_CACHE_MAX_ENTRIES = 128


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
        self.lock = threading.Lock()

    def wait(self) -> None:
        with self.lock:
            now = self.clock()
            if self.last_request_at is not None:
                delay = self.interval - (now - self.last_request_at)
                if delay > 0:
                    self.sleep(delay)
                    now = self.clock()
            self.last_request_at = now


_SHARED_CACHE: OrderedDict[str, tuple[float, Any]] = OrderedDict()
_SHARED_CACHE_LOCK = threading.Lock()
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
        cache_ttl: float = _DEFAULT_CACHE_TTL,
        cache_max_entries: int = _DEFAULT_CACHE_MAX_ENTRIES,
        max_retries: int = 2,
        retry_backoff: float = 0.25,
        cache: MutableMapping[str, tuple[float, Any]] | None = None,
    ):
        owns_client = client is None
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=False,
            timeout=30.0,
        )
        self._clock = clock
        self._sleep = sleep
        self._cache_ttl = max(0.0, cache_ttl)
        self._cache_max_entries = max(0, cache_max_entries)
        self._max_retries = max(0, max_retries)
        self._retry_backoff = max(0.0, retry_backoff)
        if cache is not None:
            self._cache = cache
            self._cache_lock = threading.Lock()
        elif owns_client:
            self._cache = _SHARED_CACHE
            self._cache_lock = _SHARED_CACHE_LOCK
        else:
            self._cache = OrderedDict()
            self._cache_lock = threading.Lock()
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
        cache_key = f"process:{number}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

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
        self._put_cached(cache_key, process)
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
        cache_key = (
            f"search:{query_type}:{query.casefold()}:{page}"
            if query_type == "name"
            else None
        )
        cached = self._get_cached(cache_key) if cache_key is not None else None
        if cached is not None:
            return cached

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
        if cache_key is not None:
            self._put_cached(cache_key, parsed)
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
                if (
                    response.status_code not in _TRANSIENT_STATUSES
                    or attempt == self._max_retries
                ):
                    return response
                retry_delay = self._retry_delay(response, attempt)
                if retry_delay is None:
                    return response
                response.close()
            self._sleep(retry_delay)
        raise AssertionError("unreachable")  # pragma: no cover

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float | None:
        backoff = self._retry_backoff * (2**attempt)
        if response.status_code != 429:
            return backoff
        header = response.headers.get("retry-after")
        if header is None:
            return None
        try:
            requested = float(header)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(header)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                requested = (retry_at - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return None
        return max(backoff, min(max(0.0, requested), 30.0))

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

    def _get_cached(self, key: str) -> Any | None:
        if self._cache_ttl <= 0 or self._cache_max_entries <= 0:
            return None
        now = self._clock()
        with self._cache_lock:
            self._prune_expired_locked(now)
            cached = self._cache.get(key)
            if cached is None:
                return None
            expires_at, process = cached
            if expires_at <= now:
                del self._cache[key]
                return None
            if isinstance(self._cache, OrderedDict):
                self._cache.move_to_end(key)
            return deepcopy(process)

    def _put_cached(self, key: str, value: Any) -> None:
        if self._cache_ttl <= 0 or self._cache_max_entries <= 0:
            return
        with self._cache_lock:
            now = self._clock()
            self._prune_expired_locked(now)
            self._cache[key] = (now + self._cache_ttl, deepcopy(value))
            if isinstance(self._cache, OrderedDict):
                self._cache.move_to_end(key)
                while len(self._cache) > self._cache_max_entries:
                    self._cache.popitem(last=False)

    def _prune_expired_locked(self, now: float) -> None:
        expired = [key for key, (expires_at, _) in self._cache.items() if expires_at <= now]
        for key in expired:
            del self._cache[key]

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
