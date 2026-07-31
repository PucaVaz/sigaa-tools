from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("mcp")

from mcp.server.fastmcp.exceptions import ToolError

from sigaa import mcp_server
from sigaa.parsers.curriculum import CurriculumDataError, parse_curriculum
from sigaa.parsers.transcript import CraUnavailableError


FIXTURE = Path(__file__).parent / "fixtures" / "curriculum.json"


def _curriculum():
    return replace(
        parse_curriculum(FIXTURE.read_text(encoding="utf-8")),
        cra=Decimal("8.42"),
        cra_source="academic_transcript",
    )


def _configured_settings():
    return SimpleNamespace(
        username="configured-user",
        resolve_password=lambda: "test-password",
    )


def test_mcp_registers_curriculum_and_cra_tools():
    names = set(mcp_server.mcp._tool_manager._tools)

    assert {"sigaa_get_curriculum", "sigaa_get_cra"} <= names


def test_mcp_curriculum_uses_shared_contract_and_filters(monkeypatch):
    class FakeClient:
        def __init__(self, username, password):
            assert (username, password) == ("configured-user", "test-password")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def get_curriculum_status(self, *, include_cra):
            assert include_cra is True
            return _curriculum()

    monkeypatch.setattr(mcp_server, "Settings", _configured_settings)
    monkeypatch.setattr(mcp_server, "SigaaClient", FakeClient)

    data = mcp_server.sigaa_get_curriculum(
        status="pending",
        required_only=True,
        period=2,
        include_requirements=True,
    )

    assert data["cra"] == {"value": 8.42, "source": "academic_transcript"}
    assert [component["code"] for component in data["components"]] == ["SYN0003"]
    assert data["components"][0]["prerequisite"] == "( SYN0001 )"
    assert "idDiscente" not in json.dumps(data)


def test_mcp_cra_treats_missing_value_as_valid_state(monkeypatch):
    class FakeClient:
        def __init__(self, username, password):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def get_cra(self):
            raise CraUnavailableError("CRA is not available in transcript")

    monkeypatch.setattr(mcp_server, "Settings", _configured_settings)
    monkeypatch.setattr(mcp_server, "SigaaClient", FakeClient)

    assert mcp_server.sigaa_get_cra() == {
        "value": None,
        "source": "unavailable",
    }


def test_mcp_curriculum_errors_are_sanitized(monkeypatch):
    class FakeClient:
        def __init__(self, username, password):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def get_curriculum_status(self, *, include_cra):
            raise CurriculumDataError("Invalid curriculum response")

    monkeypatch.setattr(mcp_server, "Settings", _configured_settings)
    monkeypatch.setattr(mcp_server, "SigaaClient", FakeClient)

    with pytest.raises(ToolError, match="Invalid curriculum response") as exc_info:
        mcp_server.sigaa_get_curriculum()

    assert "private" not in str(exc_info.value).lower()


def test_mcp_curriculum_requires_credentials(monkeypatch):
    settings = SimpleNamespace(username=None, resolve_password=lambda: None)
    monkeypatch.setattr(mcp_server, "Settings", lambda: settings)

    with pytest.raises(ToolError, match="no credentials"):
        mcp_server.sigaa_get_curriculum()
