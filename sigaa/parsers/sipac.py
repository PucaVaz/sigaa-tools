"""Parsers for SIPAC/UFPB's public administrative-process portal."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from ..models import (
    SipacAttachedFile,
    SipacDocument,
    SipacInterestedParty,
    SipacMovement,
    SipacProcess,
    SipacStatusChange,
)

PUBLIC_HOST = "https://sipac.ufpb.br"
PROCESS_NUMBER_RE = re.compile(
    r"^\s*(\d{5})\s*[.]\s*(\d{6})\s*[/]\s*(\d{4})\s*[-]\s*(\d{2})\s*$"
)


class SipacParseError(ValueError):
    """Raised when SIPAC returns a page that does not match its public contract."""


def normalize_process_number(value: str) -> str:
    match = PROCESS_NUMBER_RE.fullmatch(value)
    if match is None:
        raise ValueError(
            "invalid SIPAC process number; expected 00000.000000/0000-00"
        )
    radical, sequence, year, check_digits = match.groups()
    return f"{radical}.{sequence}/{year}-{check_digits}"


def build_process_search_payload(html: str, process_number: str) -> dict[str, str]:
    number = normalize_process_number(process_number)
    radical, sequence, year, check_digits = re.split(r"[./-]", number)
    soup = BeautifulSoup(html, "lxml")
    form = soup.select_one("form#processoForm")
    if form is None:
        raise SipacParseError("SIPAC public process form was not found")

    payload = {
        field["name"]: field.get("value", "")
        for field in form.select("input[type=hidden][name]")
    }
    submit = form.select_one('input[type="submit"][name]')
    if submit is None:
        raise SipacParseError("SIPAC public process submit control was not found")
    payload.update(
        {
            "tipo_consulta": "100",
            "RADICAL_PROTOCOLO": radical,
            "NUM_PROTOCOLO": sequence,
            "ANO_PROTOCOLO": year,
            "DV_PROTOCOLO": check_digits,
            "INTERESSADO": "",
            "CPF_CNPJ": "",
            submit["name"]: submit.get("value", "Consultar Processo"),
        }
    )
    return payload


def parse_process_detail_url(
    html: str,
    process_number: str,
    *,
    base_url: str = PUBLIC_HOST,
) -> str | None:
    number = normalize_process_number(process_number)
    soup = BeautifulSoup(html, "lxml")
    for table in soup.select("table.listagem"):
        for row in _own_rows(table):
            cells = row.find_all(["th", "td"], recursive=False)
            if not cells or _text(cells[0]) != number:
                continue
            link = row.select_one('a[href*="processo_detalhado.jsf"]')
            if link is None:
                raise SipacParseError("SIPAC process result has no detail link")
            return _public_url(link.get("href"), base_url=base_url)
    return None


def parse_public_process(
    html: str,
    *,
    public_url: str,
) -> SipacProcess:
    soup = BeautifulSoup(html, "lxml")
    fields = _parse_general_fields(soup)
    number = fields.get("Processo")
    if not number:
        raise SipacParseError("SIPAC process detail page has no process number")

    return SipacProcess(
        number=normalize_process_number(number),
        public_url=public_url,
        origin=fields.get("Origem do Processo"),
        opened_at=fields.get("Data de Autuação"),
        opened_by=fields.get("Usuário de Autuação"),
        subject=fields.get("Assunto do Processo"),
        detailed_subject=fields.get("Assunto Detalhado"),
        nature=fields.get("Natureza do Processo"),
        origin_unit=fields.get("Unidade de Origem"),
        status=fields.get("Status"),
        registered_on=fields.get("Data de Cadastro"),
        note=fields.get("Observação") or None,
        interested_parties=_parse_interested_parties(soup),
        documents=_parse_documents(soup),
        movements=_parse_movements(soup),
        status_changes=_parse_status_changes(soup),
        attached_files=_parse_attached_files(soup),
    )


def _parse_general_fields(soup: BeautifulSoup) -> dict[str, str]:
    for table in soup.find_all("table"):
        rows = _own_rows(table)
        if not any(_row_label(row) == "Processo" for row in rows):
            continue
        fields: dict[str, str] = {}
        for row in rows:
            cells = row.find_all(["th", "td"], recursive=False)
            if len(cells) != 2 or cells[0].name != "th":
                continue
            fields[_text(cells[0]).rstrip(":")] = _text(cells[1])
        return fields
    raise SipacParseError("SIPAC process general-data table was not found")


def _parse_interested_parties(soup: BeautifulSoup) -> list[SipacInterestedParty]:
    table = _table_by_caption(soup, "Interessados Deste Processo")
    if table is None:
        return []
    rows = _data_rows(table, expected_headers=["Tipo", "Identificador", "Nome"])
    return [
        SipacInterestedParty(kind=values[0], identifier=values[1], name=values[2])
        for _, values in rows
        if len(values) >= 3
    ]


def _parse_documents(soup: BeautifulSoup) -> list[SipacDocument]:
    table = _table_by_caption(soup, "Documentos do Processo")
    if table is None:
        return []
    rows = _data_rows(
        table,
        expected_headers=[
            "Ordem",
            "Documento (Espécie)",
            "Data do Documento",
            "Origem",
            "Natureza",
        ],
    )
    documents = []
    for row, values in rows:
        if len(values) < 5 or not values[0].isdigit():
            continue
        download_url = None
        for link in row.find_all("a", href=True):
            image = link.find("img")
            if image and image.get("alt") == "Visualizar Documento":
                download_url = _public_url(link.get("href"))
                break
        documents.append(
            SipacDocument(
                order=int(values[0]),
                kind=values[1],
                date=values[2],
                origin=values[3],
                nature=values[4],
                download_url=download_url,
            )
        )
    return documents


def _parse_movements(soup: BeautifulSoup) -> list[SipacMovement]:
    table = _table_by_caption(soup, "Movimentações do Processo")
    if table is None:
        return []
    rows = _data_rows(
        table,
        expected_headers=[
            "Data Origem",
            "Unidade Origem",
            "Unidade Destino",
            "Enviado Por",
            "Recebido Em",
            "Recebido Por",
            "Urgente",
        ],
    )
    return [
        SipacMovement(
            sent_at=values[0],
            origin_unit=values[1],
            destination_unit=values[2],
            sent_by=values[3],
            received_at=values[4] or None,
            received_by=values[5] or None,
            urgent=_is_yes(values[6]),
        )
        for _, values in rows
        if len(values) >= 7
    ]


def _parse_status_changes(soup: BeautifulSoup) -> list[SipacStatusChange]:
    table = _table_by_caption(soup, "Alterações Ocorridas no Processo")
    if table is None:
        return []
    rows = _data_rows(table, expected_headers=["Data", "Usuário", "Status", "Obs."])
    return [
        SipacStatusChange(
            date=values[0],
            user=values[1],
            status=values[2],
            note=values[3] or None,
        )
        for _, values in rows
        if len(values) >= 4
    ]


def _parse_attached_files(soup: BeautifulSoup) -> list[SipacAttachedFile]:
    table = _table_by_caption(soup, "Arquivos anexados ao Processo")
    if table is None:
        return []
    rows = _data_rows(table, expected_headers=["Nome", "Descrição"])
    attached = []
    for row, values in rows:
        if not values:
            continue
        link = row.find("a", href=True)
        description = values[1] if len(values) > 1 and values[1] else None
        attached.append(
            SipacAttachedFile(
                name=values[0],
                description=description,
                download_url=_public_url(link.get("href")) if link else None,
            )
        )
    return attached


def _table_by_caption(soup: BeautifulSoup, caption_text: str) -> Tag | None:
    for table in soup.find_all("table"):
        caption = table.find("caption", recursive=False)
        if caption is not None and _text(caption) == caption_text:
            return table
    return None


def _own_rows(table: Tag) -> list[Tag]:
    return [row for row in table.find_all("tr") if row.find_parent("table") is table]


def _data_rows(
    table: Tag,
    *,
    expected_headers: list[str],
) -> list[tuple[Tag, list[str]]]:
    rows = _own_rows(table)
    if not rows:
        return []
    header = [_text(cell) for cell in rows[0].find_all(["th", "td"], recursive=False)]
    if header[: len(expected_headers)] != expected_headers:
        raise SipacParseError(
            f"unexpected columns in SIPAC table {_text(table.find('caption'))!r}"
        )
    return [
        (row, [_text(cell) for cell in row.find_all(["th", "td"], recursive=False)])
        for row in rows[1:]
    ]


def _row_label(row: Tag) -> str | None:
    first = row.find(["th", "td"], recursive=False)
    if first is None or first.name != "th":
        return None
    return _text(first).rstrip(":")


def _public_url(href: str | None, *, base_url: str = PUBLIC_HOST) -> str | None:
    if not href or href.startswith("#") or href.lower().startswith("javascript:"):
        return None
    url = urljoin(base_url, href)
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "sipac.ufpb.br":
        return None
    return url


def _is_yes(value: str) -> bool:
    return value.casefold() in {"sim", "yes", "true"}


def _text(element: Tag | None) -> str:
    return element.get_text(" ", strip=True) if element is not None else ""
