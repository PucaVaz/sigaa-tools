from __future__ import annotations

from decimal import Decimal

import pytest

from sigaa.parsers.transcript import (
    CraUnavailableError,
    TranscriptParseError,
    parse_cra_pdf,
    parse_cra_text,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Coeficiente de Rendimento Acadêmico (CRA): 8,76", "8.76"),
        ("CRA = 7.50", "7.50"),
        ("Índices acadêmicos\nCRA\n8,42\nFim", "8.42"),
        ("Índices acadêmicos\nCRA\nObservação\nValor: 9,10", "9.10"),
        ("8.25\nCRA", "8.25"),
        ("cra: 0,00", "0.00"),
        ("CRA: 10.00", "10.00"),
        ("CRA      MC\n8.61     7.20", "8.61"),
    ],
)
def test_parse_cra_text_handles_common_pdf_layouts(text, expected):
    assert parse_cra_text(text) == Decimal(expected)


def test_parse_cra_text_accepts_repeated_matching_value():
    text = "Resumo\nCRA: 8,40\nDetalhamento\nCRA\n8.40"

    assert parse_cra_text(text) == Decimal("8.40")


def test_boxed_cra_below_label_wins_over_period_number_above():
    text = f"{' ' * 7}9\nCRA:\n{' ' * 27}6.54"

    assert parse_cra_text(text) == Decimal("6.54")


def test_explicit_cra_label_without_value_does_not_fall_back_up():
    text = f"{' ' * 7}9\nCRA:\n"

    with pytest.raises(CraUnavailableError):
        parse_cra_text(text)


@pytest.mark.parametrize(
    "text",
    [
        "CRA      MC\n         7.20",
        "MC      CRA\n7.20",
    ],
)
def test_empty_cra_table_cell_does_not_use_neighboring_index(text):
    with pytest.raises(CraUnavailableError):
        parse_cra_text(text)


@pytest.mark.parametrize("text", ["Average result: 8.75", "CRA without value"])
def test_missing_cra_is_a_valid_unavailable_state(text):
    with pytest.raises(CraUnavailableError):
        parse_cra_text(text)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("CRA: 10,01", "supported range"),
        ("CRA: 8,50\nResumo\nCRA: 8,75", "conflicting"),
    ],
)
def test_parse_cra_text_rejects_missing_invalid_or_conflicting_values(text, message):
    with pytest.raises(TranscriptParseError, match=message):
        parse_cra_text(text)


def test_parse_errors_never_echo_private_transcript_text():
    private_text = "CRA sem valor - estudante PRIVATE-STUDENT-ID"

    with pytest.raises(TranscriptParseError) as exc_info:
        parse_cra_text(private_text)

    assert "PRIVATE-STUDENT-ID" not in str(exc_info.value)


def test_parse_cra_pdf_extracts_text_from_in_memory_pdf():
    content = _synthetic_text_pdf(["HISTORICO ACADEMICO", "CRA: 8.73"])

    assert parse_cra_pdf(content) == Decimal("8.73")


@pytest.mark.parametrize(
    "content",
    [
        b"PRIVATE-PDF-CONTENT",
        b"%PDF-1.7\nPRIVATE-MALFORMED-CONTENT",
    ],
)
def test_parse_cra_pdf_rejects_invalid_content_with_sanitized_error(content):
    with pytest.raises(TranscriptParseError) as exc_info:
        parse_cra_pdf(content)

    assert "PRIVATE" not in str(exc_info.value)
    assert content.decode("ascii") not in str(exc_info.value)


def _synthetic_text_pdf(lines: list[str]) -> bytes:
    """Build a tiny offline PDF with extractable ASCII text."""

    text_operations = ["BT", "/F1 12 Tf", "72 720 Td"]
    for index, line in enumerate(lines):
        if index:
            text_operations.append("0 -18 Td")
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        text_operations.append(f"({escaped}) Tj")
    text_operations.append("ET")
    stream = "\n".join(text_operations).encode("ascii")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        ),
    ]

    document = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_number, body in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{object_number} 0 obj\n".encode("ascii"))
        document.extend(body)
        document.extend(b"\nendobj\n")

    xref_offset = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    document.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(document)
