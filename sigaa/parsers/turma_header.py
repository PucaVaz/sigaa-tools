"""Which turma a Turma Virtual page says it shows.

Regexes rather than a DOM parse: this runs on every turma page, some of them
250 KB, only to read one short header.
"""

from __future__ import annotations

import re

# Principal and every menu page: <p id="linkCodigoTurma" ...>GDSCO0055 - </p>
_HEADER_CODE_RE = re.compile(r'id="linkCodigoTurma"[^>]*>\s*([^<\s]+)\s*-')
# Ver Notas with posted grades is a bare report with no Turma Virtual header:
# <h3>GDSCO0055 - INTRODUÇÃO AO ... - Turma: 01 (2026.2)</h3>. The trailing
# "- Turma:" keeps unrelated "<h3>Something - else</h3>" headings out.
_REPORT_CODE_RE = re.compile(r"<h3>\s*([^<\s]+)\s+-\s[^<]*?-\s*Turma:")


def displayed_turma_code(html: str) -> str | None:
    """Component code in the page's turma header, or None when it has none."""
    for pattern in (_HEADER_CODE_RE, _REPORT_CODE_RE):
        match = pattern.search(html)
        if match:
            return match.group(1)
    return None
