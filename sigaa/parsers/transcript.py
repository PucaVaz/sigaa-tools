"""Extract the official CRA value from an academic transcript.

The PDF entry point keeps the private document in memory and returns only a
``Decimal``. Public errors are deliberately static so malformed documents
cannot leak transcript text or bytes through exception messages.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from io import BytesIO

from pypdf import PdfReader


class TranscriptParseError(ValueError):
    """The transcript is invalid or does not expose an unambiguous CRA."""


class CraUnavailableError(TranscriptParseError):
    """The transcript is valid but does not report a CRA yet."""


_CRA_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9])C[\s._-]*R[\s._-]*A(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(
    r"(?<![\d.,])[-+]?\d{1,3}(?:[.,]\d+)?(?![\d.,])"
)
_VALUE_DELIMITER_RE = re.compile(r"[:=]")
_NON_WHITESPACE_RE = re.compile(r"\S+")
_MAX_ADJACENT_LINES = 3
# SIGAA centers the boxed CRA value farther right than its label in the
# layout-extracted text. Neighboring table headers still provide tighter cell
# bounds when they exist.
_MAX_COLUMN_DISTANCE = 40
_MIN_CRA = Decimal("0.00")
_MAX_CRA = Decimal("10.00")


def parse_cra_pdf(content: bytes | bytearray | memoryview) -> Decimal:
    """Return the transcript's official CRA from PDF bytes.

    The PDF is validated and parsed directly from memory. The returned
    ``Decimal`` is always between ``0.00`` and ``10.00``, inclusive.
    """

    if not isinstance(content, (bytes, bytearray, memoryview)):
        raise TypeError("transcript PDF content must be bytes")

    pdf_bytes = bytes(content)
    if not pdf_bytes.startswith(b"%PDF-"):
        raise TranscriptParseError("transcript content is not a valid PDF")

    try:
        reader = PdfReader(BytesIO(pdf_bytes), strict=False)
        if reader.is_encrypted:
            raise TranscriptParseError("encrypted transcripts are not supported")
        if not reader.pages:
            raise TranscriptParseError("transcript PDF contains no pages")

        page_text = []
        for page in reader.pages:
            text = page.extract_text(extraction_mode="layout")
            if text:
                page_text.append(text)
    except TranscriptParseError:
        raise
    except Exception:
        raise TranscriptParseError("transcript PDF could not be read") from None

    if not page_text:
        raise TranscriptParseError("transcript PDF contains no readable text")
    return parse_cra_text("\n".join(page_text))


def parse_cra_text(text: str) -> Decimal:
    """Return the CRA associated with a ``CRA`` label in extracted PDF text.

    The value may share the label's line or appear up to three lines below it.
    Bare labels also support a preceding value, while explicit ``CRA:`` and
    ``CRA =`` fields never fall back upward. Comma and dot decimal separators
    are accepted. Conflicting repeated values fail instead of being guessed.
    """

    if not isinstance(text, str):
        raise TypeError("transcript text must be a string")

    normalized = unicodedata.normalize("NFKC", text).replace("\r\n", "\n")
    lines = normalized.replace("\r", "\n").split("\n")
    labels = [
        (line_index, match)
        for line_index, line in enumerate(lines)
        for match in _CRA_LABEL_RE.finditer(line)
    ]
    if not labels:
        raise CraUnavailableError("CRA is not available in transcript")

    values: list[Decimal] = []
    for line_index, label in labels:
        raw_value = _find_value_for_label(lines, line_index, label)
        if raw_value is not None:
            values.append(_parse_cra_value(raw_value))

    if not values:
        raise CraUnavailableError("CRA is not available in transcript")

    distinct_values = set(values)
    if len(distinct_values) != 1:
        raise TranscriptParseError("transcript contains conflicting CRA values")
    return distinct_values.pop()


def _find_value_for_label(
    lines: list[str],
    line_index: int,
    label: re.Match[str],
) -> str | None:
    line = lines[line_index]
    column_bounds = _label_column_bounds(line, label)
    after_label = line[label.end() :]

    explicit_delimiter = _VALUE_DELIMITER_RE.search(after_label)
    if explicit_delimiter is not None:
        candidate = _first_number(after_label[explicit_delimiter.end() :])
        if candidate is not None:
            return candidate
    else:
        candidate = _first_number(after_label)
        if candidate is not None:
            return candidate

        before_label = line[: label.start()]
        candidates_before = list(_NUMBER_RE.finditer(before_label))
        if candidates_before:
            return candidates_before[-1].group(0)

    for distance in range(1, _MAX_ADJACENT_LINES + 1):
        adjacent_index = line_index + distance
        if adjacent_index < len(lines):
            candidate = _number_nearest_column(
                lines[adjacent_index],
                label.start(),
                column_bounds=column_bounds,
            )
            if candidate is not None:
                return candidate

    # ``CRA:`` and ``CRA =`` introduce a value on the same line or below.
    # Looking above them can capture an unrelated field such as the current
    # academic period.
    if explicit_delimiter is not None:
        return None

    for distance in range(1, _MAX_ADJACENT_LINES + 1):
        adjacent_index = line_index - distance
        if adjacent_index >= 0:
            candidate = _number_nearest_column(
                lines[adjacent_index],
                label.start(),
                column_bounds=column_bounds,
            )
            if candidate is not None:
                return candidate

    return None


def _first_number(text: str) -> str | None:
    match = _NUMBER_RE.search(text)
    return match.group(0) if match is not None else None


def _label_column_bounds(
    line: str,
    label: re.Match[str],
) -> tuple[float | None, float | None]:
    """Bound an adjacent value to the CRA cell in a layout-extracted table."""
    tokens = list(_NON_WHITESPACE_RE.finditer(line))
    previous = next(
        (
            token
            for token in reversed(tokens)
            if token.end() <= label.start()
            and line[token.end() : label.start()].isspace()
            and len(line[token.end() : label.start()]) >= 2
        ),
        None,
    )
    following = next(
        (
            token
            for token in tokens
            if token.start() >= label.end()
            and line[label.end() : token.start()].isspace()
            and len(line[label.end() : token.start()]) >= 2
        ),
        None,
    )

    left = (
        (previous.start() + label.start()) / 2
        if previous is not None
        else None
    )
    right = (
        (label.start() + following.start()) / 2
        if following is not None
        else None
    )
    return left, right


def _number_nearest_column(
    line: str,
    label_column: int,
    *,
    column_bounds: tuple[float | None, float | None],
) -> str | None:
    matches = list(_NUMBER_RE.finditer(line))
    if not matches:
        return None

    left, right = column_bounds
    matches = [
        match
        for match in matches
        if (left is None or match.start() >= left)
        and (right is None or match.start() < right)
        and abs(match.start() - label_column) <= _MAX_COLUMN_DISTANCE
    ]
    if not matches:
        return None

    valid_matches = [
        match for match in matches if _value_in_range(match.group(0))
    ]
    candidates = valid_matches or matches
    nearest = min(
        candidates,
        key=lambda match: (abs(match.start() - label_column), match.start()),
    )
    return nearest.group(0)


def _value_in_range(raw_value: str) -> bool:
    try:
        value = Decimal(raw_value.replace(",", "."))
    except InvalidOperation:
        return False
    return value.is_finite() and _MIN_CRA <= value <= _MAX_CRA


def _parse_cra_value(raw_value: str) -> Decimal:
    try:
        value = Decimal(raw_value.replace(",", "."))
    except InvalidOperation:
        raise TranscriptParseError("CRA value is invalid") from None

    if not value.is_finite() or not _MIN_CRA <= value <= _MAX_CRA:
        raise TranscriptParseError("CRA value is outside the supported range")
    return value
