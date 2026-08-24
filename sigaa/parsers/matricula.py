"""Parse the matrícula on-line pages: open sections and submission receipts."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import OpenTurma

# Component codes are alphanumeric (e.g. DINF00049, 1107202), not digits-only.
_COMPONENT_RE = re.compile(r"\*?\s*([A-Z0-9]{7,9}) - (.+?)\s*\(([^)]+)\)")
_LEVEL_RE = re.compile(r"(\d+º) Nível")
_SCHEDULE_RE = re.compile(r"\b[2-7]+[MTN][1-6]+\b")
_REQUEST_NUMBER_RE = re.compile(r"Solicita[^\s]*o de Matr[^\s]*cula N[^\s]*\s*(\d+)")


def parse_open_turmas(html: str) -> list[OpenTurma]:
    """Open sections from the 'Turmas Abertas do Currículo' page."""
    soup = BeautifulSoup(html, "lxml")
    turmas: list[OpenTurma] = []
    level: str | None = None
    component: tuple[str, str, str, bool] | None = None
    for row in soup.select("table tr"):
        text = re.sub(r"\s+", " ", row.get_text(" ", strip=True))
        level_match = _LEVEL_RE.match(text)
        if level_match:
            level = level_match.group(1)
            continue
        checkbox = row.find("input", {"name": "selecaoTurmas"})
        component_match = _COMPONENT_RE.match(text)
        if component_match and not checkbox:
            allowed = row.find("img", src=re.compile("matricula_permitida")) is not None
            component = (
                component_match.group(1),
                component_match.group(2),
                component_match.group(3),
                allowed,
            )
            continue
        if checkbox and component:
            cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in row.find_all("td")]
            cells = [c for c in cells if c and not c.startswith("Essa turma")]
            schedule = next((c for c in cells if _SCHEDULE_RE.search(c)), None)
            turma_label = next((c for c in cells if c.startswith("Turma")), None)
            capacity = next((c for c in cells if c.endswith("alunos")), None)
            label_idx = cells.index(turma_label) if turma_label in cells else -1
            teachers = cells[label_idx + 1] if 0 <= label_idx < len(cells) - 1 else None
            turmas.append(
                OpenTurma(
                    turma_id=checkbox["value"],
                    component_code=component[0],
                    component_name=component[1],
                    kind=component[2],
                    level=level,
                    allowed=component[3],
                    # The reservation flag lives in the checkbox id suffix.
                    has_reservation="temReservas" in (checkbox.get("id") or ""),
                    turma_label=turma_label,
                    teachers=teachers,
                    schedule_raw=schedule,
                    capacity=capacity,
                )
            )
    return turmas


def parse_messages(html: str) -> list[str]:
    """User-facing feedback messages (accepted/rejected selections, receipts)."""
    soup = BeautifulSoup(html, "lxml")
    messages = []
    for panel in soup.select("#painel-erros li, .info, .erros li, .aviso"):
        text = re.sub(r"\s+", " ", panel.get_text(" ", strip=True))
        if text:
            messages.append(text)
    if not messages:
        flat = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        for marker in ("selecionadas com sucesso", "submetidas com sucesso", "não possui reserva"):
            index = flat.find(marker)
            if index != -1:
                messages.append(flat[max(0, index - 120) : index + len(marker)])
    return messages


def parse_request_number(html: str) -> str | None:
    """The Solicitação de Matrícula number from the confirmation page."""
    flat = re.sub(r"\s+", " ", BeautifulSoup(html, "lxml").get_text(" ", strip=True))
    match = _REQUEST_NUMBER_RE.search(flat)
    return match.group(1) if match else None
