from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace

import pytest

pytest.importorskip("mcp")

from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import BlobResourceContents, ResourceLink

from sigaa import mcp_server
from sigaa.documents import (
    ATESTADO_MATRICULA,
    DECLARACAO_VINCULO,
    AcademicDocument,
)


@pytest.mark.parametrize(
    ("tool_name", "kind", "filename", "media_type", "content"),
    [
        (
            "sigaa_download_declaracao_vinculo",
            DECLARACAO_VINCULO,
            "declaracao.pdf",
            "application/pdf",
            b"%PDF-1.7\nsynthetic MCP resource bytes",
        ),
        (
            "sigaa_download_atestado_matricula",
            ATESTADO_MATRICULA,
            "atestado.html",
            "text/html",
            b"<!doctype html><html><body>synthetic certificate</body></html>",
        ),
    ],
)
def test_document_tool_returns_readable_resource_link(
    monkeypatch,
    tmp_path,
    tool_name,
    kind,
    filename,
    media_type,
    content,
):
    document = AcademicDocument(
        kind=kind,
        filename=filename,
        media_type=media_type,
        content=content,
    )

    class FakeClient:
        def __init__(self, username, password):
            assert username == "configured-user"
            assert password == "test-password"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def download_academic_document(self, requested_kind):
            assert requested_kind == kind
            return document

    settings = SimpleNamespace(
        username="configured-user", resolve_password=lambda: "test-password"
    )
    monkeypatch.setattr(mcp_server, "Settings", lambda: settings)
    monkeypatch.setattr(mcp_server, "SigaaClient", FakeClient)
    monkeypatch.setattr(mcp_server, "default_download_dir", lambda: tmp_path)

    async def exercise_resource():
        async with create_connected_server_and_client_session(mcp_server.mcp) as session:
            await session.initialize()
            result = await session.call_tool(
                tool_name,
                {"filename": filename},
            )
            links = [item for item in result.content if isinstance(item, ResourceLink)]
            resource = await session.read_resource(links[0].uri) if len(links) == 1 else None
            return result, links, resource

    result, links, resource = asyncio.run(exercise_resource())

    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent["kind"] == kind
    assert result.structuredContent["filename"] == filename
    assert result.structuredContent["mime_type"] == media_type
    assert result.structuredContent["size"] == len(content)
    expected_resource_media_type = (
        "application/octet-stream" if media_type == "text/html" else media_type
    )
    assert (
        result.structuredContent["resource_mime_type"]
        == expected_resource_media_type
    )

    assert len(links) == 1
    link = links[0]
    assert link.name == filename
    assert link.mimeType == expected_resource_media_type
    assert link.size == len(content)
    assert link.uri.scheme != "file"
    assert filename not in str(link.uri)
    assert str(tmp_path) not in str(link.uri)
    assert content not in repr(result).encode()

    assert resource is not None
    assert len(resource.contents) == 1
    [resource_content] = resource.contents
    assert isinstance(resource_content, BlobResourceContents)
    assert resource_content.uri == link.uri
    assert resource_content.mimeType == expected_resource_media_type
    assert base64.b64decode(resource_content.blob, validate=True) == content
