from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("mcp")

from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ResourceLink

from sigaa import mcp_server
from sigaa.documents import DECLARACAO_VINCULO, validate_academic_document


def test_mcp_registers_all_academic_document_tools():
    names = set(mcp_server.mcp._tool_manager._tools)
    assert {
        "sigaa_download_historico",
        "sigaa_download_declaracao_vinculo",
        "sigaa_download_atestado_matricula",
    } <= names


def test_mcp_document_download_returns_metadata_not_content(monkeypatch, tmp_path):
    document = validate_academic_document(
        DECLARACAO_VINCULO,
        b"%PDF-1.7\nprivate MCP bytes",
        "application/pdf",
    )

    class FakeClient:
        def __init__(self, username, password):
            assert username == "configured-user"
            assert password == "test-password"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def download_academic_document(self, kind):
            assert kind == DECLARACAO_VINCULO
            return document

    settings = SimpleNamespace(
        username="configured-user", resolve_password=lambda: "test-password"
    )
    monkeypatch.setattr(mcp_server, "Settings", lambda: settings)
    monkeypatch.setattr(mcp_server, "SigaaClient", FakeClient)
    monkeypatch.setattr(mcp_server, "default_download_dir", lambda: tmp_path)
    target = tmp_path / "declaracao.pdf"

    result = mcp_server._download_academic_document(DECLARACAO_VINCULO, target.name)

    assert target.read_bytes() == document.content
    metadata = result.structuredContent
    assert metadata is not None
    assert metadata == {
        "kind": DECLARACAO_VINCULO,
        "filename": target.name,
        "mime_type": "application/pdf",
        "size": len(document.content),
        "resource_uri": metadata["resource_uri"],
        "resource_mime_type": "application/pdf",
    }
    [link] = [item for item in result.content if isinstance(item, ResourceLink)]
    assert str(link.uri) == metadata["resource_uri"]
    assert b"private MCP bytes" not in repr(result).encode()


def test_document_resource_rejects_unknown_and_changed_files(tmp_path):
    content = b"original private bytes"
    target = tmp_path / "documento.pdf"
    target.write_bytes(content)

    uri = mcp_server._register_document_resource(
        target.resolve(),
        download_dir=tmp_path.resolve(),
        filename=target.name,
        media_type="application/pdf",
        content=content,
    )
    token = uri.rsplit("/", 1)[-1]

    assert mcp_server._read_document_resource(token, "application/pdf") == content
    with pytest.raises(ValueError, match="invalid document resource identifier"):
        mcp_server._read_document_resource("not-a-real-token", "application/pdf")
    with pytest.raises(ValueError, match="not found or has expired"):
        mcp_server._read_document_resource("A" * 32, "application/pdf")

    target.write_bytes(b"changed private bytes!")
    with pytest.raises(ValueError, match="changed after it was downloaded"):
        mcp_server._read_document_resource(token, "application/pdf")


@pytest.mark.parametrize(
    "token",
    [
        "A" * 31,
        "A" * 33,
        "A" * 31 + "%",
        "A" * 31 + "\\",
        "A" * 31 + "?",
        "A" * 31 + "#",
        "A" * 30 + "%2F",
    ],
)
def test_mcp_rejects_malformed_document_resource_tokens(token):
    with pytest.raises(ValueError, match="invalid document resource identifier"):
        mcp_server._read_document_resource(token, "application/pdf")


def test_mcp_existing_output_short_circuits_before_credentials(monkeypatch, tmp_path):
    target = tmp_path / "documento.pdf"
    target.write_bytes(b"keep me")

    def settings_must_not_be_built():
        raise AssertionError("credentials should not be resolved")

    monkeypatch.setattr(mcp_server, "Settings", settings_must_not_be_built)
    monkeypatch.setattr(mcp_server, "default_download_dir", lambda: tmp_path)
    with pytest.raises(ToolError, match="already exists"):
        mcp_server._download_academic_document(DECLARACAO_VINCULO, target.name)

    assert target.read_bytes() == b"keep me"


@pytest.mark.parametrize(
    "filename", ["../outside.pdf", "subdir/document.pdf", "C:\\outside.pdf", "CON"]
)
def test_mcp_rejects_paths_and_unsafe_filenames(filename):
    with pytest.raises(ToolError, match="safe file name"):
        mcp_server._download_academic_document(DECLARACAO_VINCULO, filename)
