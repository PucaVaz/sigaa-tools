"""Parse the extension documents page ('Certificados e Declarações').

The page (``/sigaa/extensao/DocumentosAutenticados/lista.jsf``) lists the
student's participations in extension actions in up to three ``listagem``
tables, one per kind: team member, audience and extension student. Inside a
table every action repeats the same block: a ``td.subFormulario`` heading
("<ano> - <título>" or "<código> - <título>"), a row of ``th`` column labels,
then the participation cells followed by up to three action-icon cells
(Visualizar, Emitir Declaração, Emitir Certificado). An empty icon cell means
that document cannot be issued yet.

SIGAA nests those rows inside an outer ``td``, which is invalid HTML: lxml
hoists the cells out of their row, html.parser keeps them nested. The parser
therefore walks the leaf cells of each table in document order instead of
trusting the row structure.

An empty result is only returned for a recognized page that lists no action
at all. A page that is not the documents page, an unknown table, or an action
block whose cells cannot be matched to its labels raises ``ExtensaoParseError``
so a markup change never passes for "no participations".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from ..errors import ParseError
from ..models import ExtensionParticipation

KIND_TEAM_MEMBER = "team_member"
KIND_AUDIENCE = "audience"
KIND_EXTENSION_STUDENT = "extension_student"

_PAGE_FORM_ACTION = "DocumentosAutenticados"

# Folded caption fragment -> participation kind.
_CAPTION_KINDS = (
    ("membro de equipe", KIND_TEAM_MEMBER),
    ("publico alvo", KIND_AUDIENCE),
    ("como discente", KIND_EXTENSION_STUDENT),
)

# Folded column label -> model field. The first column of every table is the
# student's own name; it is required (so a shifted layout is caught) but mapped
# to None and never returned.
_COLUMN_FIELDS = {
    KIND_TEAM_MEMBER: {
        "membro projeto": None,
        "categoria": "category",
        "funcao": "role",
        "inicio": "start_date",
        "fim": "end_date",
    },
    KIND_AUDIENCE: {
        "participante": None,
        "categoria": "category",
        "participacao": "role",
        "data do cadastro": "registered_on",
        "frequencia": "frequency",
    },
    KIND_EXTENSION_STUDENT: {
        "discente": None,
        "vinculo": "role",
        "inicio": "start_date",
        "fim": "end_date",
        "situacao": "status",
    },
}

_CODED_HEADING_RE = re.compile(r"^(?P<code>[A-Z]{2,}\d+-(?P<year>\d{4}))\s+-\s+(?P<title>.+)$")
_YEAR_HEADING_RE = re.compile(r"^(?P<year>\d{4})\s+-\s+(?P<title>.+)$")
_JSF_PARAMS_RE = re.compile(r"jsfcljs\([^,]+,\s*\{(.*?)\}\s*,", re.S)
_JSF_PARAM_RE = re.compile(r"'([^']+)'\s*:\s*'([^']*)'")
_RECORD_ID_PARAMS = ("idMembro", "idCadastroParticipante", "idDiscenteExtensao")
_EMPTY_NOTICE_RE = re.compile(r"\b(nenhum|nenhuma|nao ha|nao possui)\b")
_DECLARATION_MARKERS = ("declaracao", "comprovante.png")
_CERTIFICATE_MARKERS = ("certificado", "certificate.png")
# Windows-1252 en dash that SIGAA emits as the numeric reference &#150;.
_C1_EN_DASH = "\x96"


class ExtensaoParseError(ParseError):
    pass


@dataclass
class _ActionBlock:
    heading: str
    labels: list[str] = field(default_factory=list)
    cells: list = field(default_factory=list)


def parse_extension_participations(html: str) -> list[ExtensionParticipation]:
    """All extension participations listed on the documents page."""
    soup = BeautifulSoup(html, "lxml")
    form = _documents_form(soup)
    if form is None:
        raise ExtensaoParseError("extension documents page not recognized")

    participations: list[ExtensionParticipation] = []
    for table in form.find_all("table", class_="listagem"):
        kind = _table_kind(table)
        for block in _action_blocks(table):
            participations.append(_participation(kind, block))
    return participations


def _documents_form(soup: BeautifulSoup):
    for form in soup.find_all("form"):
        if _PAGE_FORM_ACTION in (form.get("action") or ""):
            return form
    return None


def _table_kind(table) -> str:
    caption = table.find("caption")
    caption_text = _fold(caption.get_text(" ", strip=True)) if caption else ""
    for fragment, kind in _CAPTION_KINDS:
        if fragment in caption_text:
            return kind
    raise ExtensaoParseError(f"unknown extension participation table: {caption_text!r}")


def _action_blocks(table) -> list[_ActionBlock]:
    blocks: list[_ActionBlock] = []
    current: _ActionBlock | None = None
    for cell in _leaf_cells(table):
        text = _clean(cell.get_text(" ", strip=True))
        if "subFormulario" in (cell.get("class") or []):
            current = _ActionBlock(heading=text)
            blocks.append(current)
        elif current is None:
            if text and not _EMPTY_NOTICE_RE.search(_fold(text)):
                raise ExtensaoParseError("extension table has cells outside any action block")
        elif cell.name == "th":
            if text:
                current.labels.append(text)
        else:
            current.cells.append(cell)
    return blocks


def _leaf_cells(table):
    """Table cells that contain no other cell, in document order."""
    for cell in table.find_all(["td", "th"]):
        if cell.find(["td", "th", "tr"]) is None:
            yield cell


def _participation(kind: str, block: _ActionBlock) -> ExtensionParticipation:
    columns = _COLUMN_FIELDS[kind]
    folded_labels = [_fold(label) for label in block.labels]
    missing = [label for label in columns if label not in folded_labels]
    if missing:
        raise ExtensaoParseError(
            f"extension {kind} block is missing columns: {', '.join(missing)}"
        )
    data_cells = block.cells[: len(folded_labels)]
    if len(data_cells) < len(folded_labels):
        raise ExtensaoParseError(f"extension {kind} block has no participation row")
    action_cells = block.cells[len(folded_labels):]
    for cell in action_cells:
        if _clean(cell.get_text(" ", strip=True)) and cell.find("a") is None:
            raise ExtensaoParseError(f"extension {kind} block has more than one row")

    values: dict[str, str | None] = {}
    for label, cell in zip(folded_labels, data_cells):
        field_name = columns.get(label)
        if field_name:
            values[field_name] = _clean(cell.get_text(" ", strip=True)) or None

    code, year, title = _split_heading(block.heading)
    anchors = [anchor for cell in action_cells for anchor in cell.find_all("a")]
    return ExtensionParticipation(
        kind=kind,
        title=title,
        action_code=code,
        year=year,
        declaration_available=any(_is_document_link(a, _DECLARATION_MARKERS) for a in anchors),
        certificate_available=any(_is_document_link(a, _CERTIFICATE_MARKERS) for a in anchors),
        sigaa_id=_record_id(anchors),
        **values,
    )


def _split_heading(heading: str) -> tuple[str | None, int | None, str]:
    """``PJ000-2099 - Título`` -> (code, 2099, title); ``2099 - Título`` -> (None, 2099, title)."""
    match = _CODED_HEADING_RE.match(heading)
    if match:
        return match["code"], int(match["year"]), match["title"]
    match = _YEAR_HEADING_RE.match(heading)
    if match:
        return None, int(match["year"]), match["title"]
    return None, None, heading


def _is_document_link(anchor, markers: tuple[str, ...]) -> bool:
    """Match by the icon's title/alt/src: SIGAA does not give every link an id."""
    parts = [anchor.get("title") or ""]
    for image in anchor.find_all("img"):
        parts.extend([image.get("alt") or "", image.get("src") or ""])
    label = _fold(" ".join(parts))
    return any(marker in label for marker in markers)


def _record_id(anchors) -> str | None:
    for anchor in anchors:
        match = _JSF_PARAMS_RE.search(anchor.get("onclick") or "")
        if not match:
            continue
        params = dict(_JSF_PARAM_RE.findall(match.group(1)))
        for name in _RECORD_ID_PARAMS:
            if params.get(name):
                return params[name]
    return None


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text.replace(_C1_EN_DASH, "–")).replace("\xa0", " ")
    return " ".join(text.split())


def _fold(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(ascii_text.casefold().split())
