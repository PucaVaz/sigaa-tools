from __future__ import annotations

import pytest

from sigaa.config import HOSTED_MODE, LOCAL_MODE, default_mode


def test_mode_defaults_to_local_when_unset(monkeypatch):
    monkeypatch.delenv("SIGAA_MODE", raising=False)

    assert default_mode() == LOCAL_MODE


def test_mode_defaults_to_local_when_empty(monkeypatch):
    monkeypatch.setenv("SIGAA_MODE", "   ")

    assert default_mode() == LOCAL_MODE


def test_mode_reads_hosted_ignoring_case_and_padding(monkeypatch):
    monkeypatch.setenv("SIGAA_MODE", "  HOSTED ")

    assert default_mode() == HOSTED_MODE


def test_mode_rejects_an_unknown_value(monkeypatch):
    monkeypatch.setenv("SIGAA_MODE", "hosted-v2")

    with pytest.raises(ValueError, match="SIGAA_MODE must be one of"):
        default_mode()
