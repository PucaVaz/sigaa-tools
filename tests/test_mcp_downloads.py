from __future__ import annotations

import stat
from types import SimpleNamespace

import pytest

pytest.importorskip("mcp")

from mcp.server.fastmcp.exceptions import ToolError

from sigaa import mcp_server

MATERIAL_ID = "mat-1"
MATERIAL_BYTES = b"slides for week one"


def _configure(monkeypatch, tmp_path, *, server_name: str):
    """Point the material downloader at fake credentials, a fake client and tmp_path."""
    material = SimpleNamespace(id=MATERIAL_ID, kind="file", id_turma="369279", url=None)
    turma = SimpleNamespace(id_turma="369279")

    class FakeClient:
        def __init__(self, username, password):
            assert username == "configured-user"
            assert password == "test-password"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def list_turmas(self):
            return [turma]

        def download_material(self, requested_turma, material_id):
            assert requested_turma is turma
            assert material_id == MATERIAL_ID
            return MATERIAL_BYTES, server_name

    settings = SimpleNamespace(
        username="configured-user", resolve_password=lambda: "test-password"
    )
    repo = SimpleNamespace(get_materials=lambda: [material])
    monkeypatch.setattr(mcp_server, "_repo", lambda: repo)
    monkeypatch.setattr(mcp_server, "Settings", lambda: settings)
    monkeypatch.setattr(mcp_server, "SigaaClient", FakeClient)
    monkeypatch.setattr(mcp_server, "default_download_dir", lambda: tmp_path)


def test_material_download_rejects_a_caller_supplied_path(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, server_name="slides.pdf")

    with pytest.raises(ToolError, match="safe file name"):
        mcp_server.sigaa_download_material(MATERIAL_ID, "../escape.bin")

    assert not (tmp_path.parent / "escape.bin").exists()


def test_material_download_sanitizes_a_hostile_server_filename(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, server_name="../../evil.bin")

    message = mcp_server.sigaa_download_material(MATERIAL_ID)

    assert not (tmp_path.parent / "evil.bin").exists()
    written = [item for item in tmp_path.iterdir() if item.is_file()]
    assert len(written) == 1
    assert written[0].parent == tmp_path
    assert written[0].read_bytes() == MATERIAL_BYTES
    assert str(written[0]) in message


def test_material_download_refuses_to_clobber_an_existing_file(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, server_name="slides.pdf")

    mcp_server.sigaa_download_material(MATERIAL_ID)

    with pytest.raises(ToolError, match="already exists"):
        mcp_server.sigaa_download_material(MATERIAL_ID)

    assert (tmp_path / "slides.pdf").read_bytes() == MATERIAL_BYTES


def test_material_download_writes_a_private_contained_file(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, server_name="slides.pdf")

    message = mcp_server.sigaa_download_material(MATERIAL_ID, "aula-01.pdf")

    target = tmp_path / "aula-01.pdf"
    assert target.read_bytes() == MATERIAL_BYTES
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert str(target) in message
    assert str(len(MATERIAL_BYTES)) in message
