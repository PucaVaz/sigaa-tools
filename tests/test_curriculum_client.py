from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from sigaa import config
from sigaa.client import SigaaClient
from sigaa.parsers.curriculum import CurriculumDataError
from sigaa.parsers.transcript import CraUnavailableError


FIXTURE = Path(__file__).parent / "fixtures" / "curriculum.json"
CURRICULUM_JSON = FIXTURE.read_text(encoding="utf-8")


class _CurriculumSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.gets: list[str] = []
        self.login_count = 0

    def get(self, url: str) -> str:
        self.gets.append(url)
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result

    def login(self) -> str:
        self.login_count += 1
        return "<html>fresh portal</html>"


def _client_with(session: _CurriculumSession) -> SigaaClient:
    client = object.__new__(SigaaClient)
    client._session = session
    client._portal_html = "<html>stale portal</html>"
    return client


def test_client_fetches_curriculum_shell_then_json():
    session = _CurriculumSession(["<html>curriculum shell</html>", CURRICULUM_JSON])
    client = _client_with(session)

    status = client.get_curriculum_status(include_cra=False)

    assert status.curriculum == "999999 - 2099.1"
    assert status.cra_source == "not_requested"
    assert session.gets == [
        config.CURRICULUM_ENTRY_URL,
        config.CURRICULUM_DATA_URL,
    ]
    assert session.login_count == 0


def test_client_retries_the_complete_flow_after_invalid_payload():
    session = _CurriculumSession(
        [
            "<html>first shell</html>",
            "<html>expired login</html>",
            "<html>fresh shell</html>",
            CURRICULUM_JSON,
        ]
    )
    client = _client_with(session)

    status = client.get_curriculum_status(include_cra=False)

    assert status.components
    assert session.login_count == 1
    assert session.gets == [
        config.CURRICULUM_ENTRY_URL,
        config.CURRICULUM_DATA_URL,
        config.CURRICULUM_ENTRY_URL,
        config.CURRICULUM_DATA_URL,
    ]
    assert client._portal_html == "<html>fresh portal</html>"


def test_client_surfaces_sanitized_error_after_one_retry():
    private_html = "<html>student-private-data</html>"
    session = _CurriculumSession(
        ["<html>shell</html>", private_html, "<html>shell</html>", private_html]
    )
    client = _client_with(session)

    with pytest.raises(CurriculumDataError) as exc_info:
        client.get_curriculum_status(include_cra=False)

    assert "student-private-data" not in str(exc_info.value)
    assert session.login_count == 1


def test_client_composes_cra_from_transcript(monkeypatch):
    session = _CurriculumSession(["<html>shell</html>", CURRICULUM_JSON])
    client = _client_with(session)
    monkeypatch.setattr(client, "get_cra", lambda: Decimal("8.42"))

    status = client.get_curriculum_status()

    assert status.cra == Decimal("8.42")
    assert status.cra_source == "academic_transcript"


def test_client_keeps_curriculum_when_transcript_has_no_cra(monkeypatch):
    session = _CurriculumSession(["<html>shell</html>", CURRICULUM_JSON])
    client = _client_with(session)

    def unavailable():
        raise CraUnavailableError("CRA is not available in transcript")

    monkeypatch.setattr(client, "get_cra", unavailable)

    status = client.get_curriculum_status()

    assert status.cra is None
    assert status.cra_source == "unavailable"
