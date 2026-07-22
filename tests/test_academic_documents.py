from __future__ import annotations

import os
import stat
import unicodedata
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urljoin

import httpx
import pytest
from bs4 import BeautifulSoup

from sigaa import cli as cli_module
from sigaa.client import SigaaClient
from sigaa.documents import (
    ATESTADO_MATRICULA,
    DECLARACAO_VINCULO,
    HISTORICO,
    AcademicDocumentError,
    validate_academic_document,
    write_academic_document,
)
from sigaa.http import AuthError, Session
from sigaa.parsers import portal as portal_parser

FIXTURES = Path(__file__).parent / "fixtures"
PORTAL = (FIXTURES / "portal_documents.html").read_text(encoding="utf-8")
ATESTADO = (FIXTURES / "atestado_matricula.html").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("Histórico acadêmico", "j_id_jsp_987654321_1:history"),
        ("Declaração de vínculo", "j_id_jsp_987654321_1:declaration"),
        ("Atestado de matrícula", "j_id_jsp_987654321_1:certificate"),
    ],
)
def test_build_document_postback_copies_current_form_fields(label, source):
    fields = portal_parser.build_menu_postback(PORTAL, label)

    assert fields is not None
    assert fields["j_id_jsp_987654321_1"] == "j_id_jsp_987654321_1"
    assert fields["subsistema"] == "12100"
    assert fields["portal-context"] == "student"
    assert fields["javax.faces.ViewState"] == "fresh-view-state"
    assert fields[source] == source


def test_build_document_postback_copies_all_jsf_params_and_normalizes_label():
    decomposed = unicodedata.normalize("NFD", "DECLARAÇÃO DE VÍNCULO")
    fields = portal_parser.build_menu_postback(PORTAL, decomposed)

    assert fields is not None
    assert fields["origin"] == "portal"


def test_build_document_postback_requires_viewstate():
    html = PORTAL.replace(
        '<input type="hidden" name="javax.faces.ViewState" value="fresh-view-state">',
        "",
    )
    with pytest.raises(ValueError, match="ViewState"):
        portal_parser.build_menu_postback(html, "Histórico acadêmico")


@pytest.mark.parametrize("kind", [HISTORICO, DECLARACAO_VINCULO])
def test_validate_pdf_document(kind):
    content = b"%PDF-1.7\nsynthetic fixture"
    document = validate_academic_document(
        kind,
        content,
        "application/pdf",
        "attachment; filename=../../documento.pdf",
    )

    assert document.content == content
    assert document.media_type == "application/pdf"
    assert document.filename == "documento.pdf"


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"<html>login</html>", "text/html;charset=ISO-8859-1"),
        (b"not a PDF", "application/pdf"),
        (b"%PDF-1.7", "text/html"),
    ],
)
def test_validate_pdf_rejects_http_200_error_pages(content, content_type):
    with pytest.raises(AcademicDocumentError, match="valid PDF"):
        validate_academic_document(HISTORICO, content, content_type)


def test_validate_atestado_preserves_encoding_and_adds_asset_base():
    content = ATESTADO.encode("iso-8859-1")
    document = validate_academic_document(
        ATESTADO_MATRICULA,
        content,
        "text/html;charset=ISO-8859-1",
    )

    assert document.content != content
    assert b'<base href="https://sigaa.ufpb.br/">' in document.content
    assert document.media_type == "text/html"
    assert document.charset == "iso-8859-1"
    assert document.filename == "atestado-matricula.html"

    saved = BeautifulSoup(document.content.decode("iso-8859-1"), "lxml")
    assert urljoin(saved.base["href"], saved.link["href"]) == (
        "https://sigaa.ufpb.br/sigaa/css/atestado_matricula.css"
    )


def test_validate_atestado_rejects_unexpected_html():
    with pytest.raises(AcademicDocumentError, match="unexpected"):
        validate_academic_document(
            ATESTADO_MATRICULA,
            b"<html><h3>Portal</h3></html>",
            "text/html;charset=ISO-8859-1",
        )


class _DocumentSession:
    def __init__(self, responses, fresh_portal=PORTAL):
        self.responses = iter(responses)
        self.fresh_portal = fresh_portal
        self.posts = []
        self.login_count = 0

    def post_download(self, url, data, *, retry_on_auth=True):
        self.posts.append((url, data.copy(), retry_on_auth))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result

    def login(self):
        self.login_count += 1
        return self.fresh_portal


def _client_with(session, portal=PORTAL):
    client = object.__new__(SigaaClient)
    client._session = session
    client._portal_html = portal
    return client


def test_client_downloads_each_document_with_its_dynamic_source_field():
    pdf = (b"%PDF-1.7\nfixture", "application/pdf", None)
    session = _DocumentSession([pdf, pdf])
    client = _client_with(session)

    assert client.get_historico_pdf().startswith(b"%PDF-")
    assert client.get_declaracao_vinculo_pdf().startswith(b"%PDF-")

    first_fields = session.posts[0][1]
    second_fields = session.posts[1][1]
    assert "j_id_jsp_987654321_1:history" in first_fields
    assert "j_id_jsp_987654321_1:declaration" in second_fields
    assert all(retry is False for _, _, retry in session.posts)


def test_client_rebuilds_postback_after_session_expiry():
    stale = PORTAL.replace("987654321", "111111111").replace(
        "fresh-view-state", "stale-view-state"
    )
    pdf = (b"%PDF-1.7\nfresh", "application/pdf", None)
    session = _DocumentSession([AuthError("expired"), pdf], fresh_portal=PORTAL)
    client = _client_with(session, portal=stale)

    document = client.download_academic_document(HISTORICO)

    assert document.content == pdf[0]
    assert session.login_count == 1
    assert session.posts[0][1]["javax.faces.ViewState"] == "stale-view-state"
    assert session.posts[1][1]["javax.faces.ViewState"] == "fresh-view-state"
    assert "j_id_jsp_111111111_1:history" in session.posts[0][1]
    assert "j_id_jsp_987654321_1:history" in session.posts[1][1]


def test_session_can_delegate_auth_retry_to_jsf_operation():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html;charset=UTF-8"},
            text='<html><a href="/sigaa/logon.jsf">Entrar</a></html>',
        )

    transport = httpx.MockTransport(handler)
    raw_client = httpx.Client(transport=transport)
    session = Session("example", "not-a-real-password", client=raw_client)
    session._authenticated = True
    try:
        with pytest.raises(AuthError, match="expired"):
            session.post_download("https://sigaa.invalid/report", {}, retry_on_auth=False)
    finally:
        session.close()


def test_write_document_refuses_overwrite_unless_explicit(tmp_path):
    first = validate_academic_document(
        HISTORICO, b"%PDF-1.7\nfirst", "application/pdf"
    )
    second = validate_academic_document(
        HISTORICO, b"%PDF-1.7\nsecond", "application/pdf"
    )
    target = tmp_path / "historico.pdf"

    assert write_academic_document(first, target) == target.resolve()
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        write_academic_document(second, target)
    assert target.read_bytes() == first.content

    write_academic_document(second, target, overwrite=True)
    assert target.read_bytes() == second.content
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("command", "default_output", "kind"),
    [
        ("historico", "historico.pdf", None),
        ("declaracao-vinculo", "declaracao-vinculo.pdf", DECLARACAO_VINCULO),
        ("atestado-matricula", "atestado-matricula.html", ATESTADO_MATRICULA),
    ],
)
def test_cli_exposes_all_academic_document_commands(command, default_output, kind):
    args = cli_module._build_parser().parse_args([command])

    assert args.out == default_output
    assert args.force is False
    if kind is not None:
        assert args.document_kind == kind


def test_cli_download_writes_only_validated_document(monkeypatch, tmp_path, capsys):
    document = validate_academic_document(
        DECLARACAO_VINCULO,
        b"%PDF-1.7\nprivate document bytes",
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
    target = tmp_path / "declaracao.pdf"
    args = SimpleNamespace(
        out=str(target), force=False, document_kind=DECLARACAO_VINCULO
    )
    monkeypatch.setattr(cli_module, "SigaaClient", FakeClient)

    assert cli_module._cmd_academic_document(args, settings) == 0
    assert target.read_bytes() == document.content
    stdout = capsys.readouterr().out
    assert "application/pdf" in stdout
    assert "private document bytes" not in stdout


def test_cli_existing_output_short_circuits_before_credentials(tmp_path, capsys):
    target = tmp_path / "historico.pdf"
    target.write_bytes(b"keep me")

    class SettingsThatMustNotResolve:
        username = "configured-user"

        def resolve_password(self):
            raise AssertionError("credentials should not be resolved")

    args = SimpleNamespace(out=str(target), force=False, document_kind=HISTORICO)
    result = cli_module._cmd_academic_document(args, SettingsThatMustNotResolve())

    assert result == 1
    assert target.read_bytes() == b"keep me"
    assert "--force" in capsys.readouterr().err


def test_cli_invalid_response_does_not_create_output(monkeypatch, tmp_path, capsys):
    class FakeClient:
        def __init__(self, username, password):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def download_academic_document(self, kind):
            raise AcademicDocumentError("SIGAA did not return a valid PDF")

    settings = SimpleNamespace(
        username="configured-user", resolve_password=lambda: "test-password"
    )
    target = tmp_path / "historico.pdf"
    args = SimpleNamespace(out=str(target), force=False, document_kind=HISTORICO)
    monkeypatch.setattr(cli_module, "SigaaClient", FakeClient)

    assert cli_module._cmd_academic_document(args, settings) == 1
    assert not target.exists()
    assert "download failed" in capsys.readouterr().err
