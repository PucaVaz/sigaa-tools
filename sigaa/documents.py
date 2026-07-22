"""Academic document contracts and response validation.

SIGAA exposes these reports as JSF postbacks from the student portal.  Two are
PDF downloads; the enrollment certificate is printable HTML. Keep response
validation here so callers never write a successful HTTP 200 login/error page
under a misleading extension.
"""

from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from email.message import Message
from pathlib import Path

from bs4 import BeautifulSoup

from .config import HOST

HISTORICO = "historico"
DECLARACAO_VINCULO = "declaracao-vinculo"
ATESTADO_MATRICULA = "atestado-matricula"


class AcademicDocumentError(RuntimeError):
    """SIGAA did not return the requested academic document."""


@dataclass(frozen=True)
class AcademicDocumentSpec:
    menu_label: str
    media_type: str


@dataclass(frozen=True)
class AcademicDocument:
    kind: str
    media_type: str
    content: bytes = field(repr=False)
    charset: str | None = None


DOCUMENT_SPECS = {
    HISTORICO: AcademicDocumentSpec(
        menu_label="Histórico acadêmico",
        media_type="application/pdf",
    ),
    DECLARACAO_VINCULO: AcademicDocumentSpec(
        menu_label="Declaração de vínculo",
        media_type="application/pdf",
    ),
    ATESTADO_MATRICULA: AcademicDocumentSpec(
        menu_label="Atestado de matrícula",
        media_type="text/html",
    ),
}

_UNSAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def document_spec(kind: str) -> AcademicDocumentSpec:
    try:
        return DOCUMENT_SPECS[kind]
    except KeyError as exc:
        choices = ", ".join(DOCUMENT_SPECS)
        raise ValueError(f"unknown academic document {kind!r}; choose one of: {choices}") from exc


def validate_academic_document(
    kind: str,
    content: bytes,
    content_type: str | None,
) -> AcademicDocument:
    """Validate a SIGAA response and return its media metadata."""
    spec = document_spec(kind)
    media_type, charset = _parse_content_type(content_type)

    if spec.media_type == "application/pdf":
        if media_type != "application/pdf" or not content.startswith(b"%PDF-"):
            raise AcademicDocumentError(f"SIGAA did not return a valid PDF for {kind}")
    else:
        if media_type != "text/html":
            raise AcademicDocumentError(f"SIGAA did not return HTML for {kind}")
        _validate_atestado_html(content, charset)

    if kind == ATESTADO_MATRICULA:
        content = _with_sigaa_base_url(content)

    return AcademicDocument(
        kind=kind,
        media_type=media_type,
        charset=charset,
        content=content,
    )


def sanitize_download_filename(name: str) -> str:
    """Reduce a server-supplied filename to one safe local path component."""
    normalized = unicodedata.normalize("NFC", name).strip()
    normalized = re.split(r"[/\\]", normalized)[-1]
    normalized = _UNSAFE_FILENAME_RE.sub("_", normalized).strip().strip(".")
    if not normalized:
        return "documento"
    stem = normalized.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED:
        normalized = f"_{normalized}"
    if len(normalized) > 240:
        base, dot, suffix = normalized.rpartition(".")
        normalized = f"{base[:220]}{dot}{suffix[:16]}" if dot else normalized[:240]
    return normalized


def write_academic_document(
    document: AcademicDocument,
    path: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Write private document bytes, atomically when replacing an existing file."""
    target = Path(path).expanduser()
    if overwrite:
        _atomic_replace(target, document.content)
    else:
        _exclusive_write(target, document.content)
    return target.resolve()


def _exclusive_write(target: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(target, flags, 0o600)
    try:
        _write_descriptor(descriptor, content)
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def _atomic_replace(target: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        _write_descriptor(descriptor, content)
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _write_descriptor(descriptor: int, content: bytes) -> None:
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _parse_content_type(value: str | None) -> tuple[str, str | None]:
    if not value:
        return "", None
    message = Message()
    message["Content-Type"] = value
    media_type = message.get_content_type().lower()
    charset = message.get_content_charset()
    return media_type, charset.lower() if charset else None


def _validate_atestado_html(content: bytes, charset: str | None) -> None:
    if not content:
        raise AcademicDocumentError("SIGAA returned an empty enrollment certificate")
    encoding = charset or "iso-8859-1"
    try:
        html = content.decode(encoding)
    except (LookupError, UnicodeDecodeError) as exc:
        raise AcademicDocumentError("SIGAA returned an unreadable enrollment certificate") from exc

    soup = BeautifulSoup(html, "lxml")
    heading = soup.find("h3")
    heading_text = heading.get_text(" ", strip=True).casefold() if heading else ""
    required_ids = ("identificacao", "matriculas", "autenticacao")
    if "atestado de matrícula" not in heading_text or any(
        soup.find(id=element_id) is None for element_id in required_ids
    ):
        raise AcademicDocumentError("SIGAA returned an unexpected enrollment certificate page")


_HEAD_RE = re.compile(br"(<head(?:\s[^>]*)?>)", re.IGNORECASE)


def _with_sigaa_base_url(content: bytes) -> bytes:
    """Make the saved report's root-relative official assets work under file://."""
    if re.search(br"<base\s", content, re.IGNORECASE):
        return content
    base = f'<base href="{HOST}/">'.encode("ascii")
    portable, replacements = _HEAD_RE.subn(rb"\1\n" + base, content, count=1)
    if replacements != 1:
        raise AcademicDocumentError("SIGAA returned an enrollment certificate without a head")
    return portable
