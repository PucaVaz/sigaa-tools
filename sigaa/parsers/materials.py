"""Parse course materials from the Turma Virtual Principal page (Tópicos de Aula).

Each ``div.topico-aula`` carries a ``.titulo`` heading and ``div.item`` rows. A
file row's anchor postbacks ``formAva`` to download the upload; a link row's
anchor is a plain external href. The view-scoped JSF field in the onclick changes
between renders, so downloads re-parse the live page and match on the stable
material id rather than caching the field.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import Material

# jsfcljs(formAva,{'<field>':'<field>','id':'<material_id>'},'_blank')
_DOWNLOAD_RE = re.compile(r"jsfcljs\([^,]+,\{'([^']+)':'[^']+','id':'(\d+)'\}")
_FILE_MARKER = "idInserirMaterialArquivo"

# Map the download response's content-type to a file extension.
_EXT_BY_TYPE = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/msword": ".doc",
    "application/zip": ".zip",
    "text/plain": ".txt",
}
_UNSAFE_RE = re.compile(r'[/\\:*?"<>|]+')


def parse_materials(turma_html: str, id_turma: str) -> list[Material]:
    soup = BeautifulSoup(turma_html, "lxml")
    materials: list[Material] = []
    for topic in soup.select("div.topico-aula"):
        titulo = topic.select_one(".titulo")
        topic_name = titulo.get_text(" ", strip=True) if titulo else ""
        for item in topic.select("div.item"):
            anchor = item.find("a")
            if not anchor:
                continue
            title = anchor.get_text(" ", strip=True)
            onclick = anchor.get("onclick") or ""
            href = anchor.get("href") or ""
            if _FILE_MARKER in onclick:
                match = _DOWNLOAD_RE.search(onclick)
                if match:
                    materials.append(
                        Material(
                            id=match.group(2),
                            id_turma=id_turma,
                            topic=topic_name,
                            title=title,
                            kind="file",
                        )
                    )
            elif href.startswith("http"):
                materials.append(
                    Material(
                        id=href,
                        id_turma=id_turma,
                        topic=topic_name,
                        title=title,
                        kind="link",
                        url=href,
                    )
                )
    return materials


def build_download_postback(turma_html: str, material_id: str, viewstate: str) -> dict | None:
    """Build the formAva POST fields that stream one uploaded material's bytes."""
    soup = BeautifulSoup(turma_html, "lxml")
    for anchor in soup.select(f"a[onclick*='{_FILE_MARKER}']"):
        match = _DOWNLOAD_RE.search(anchor.get("onclick", ""))
        if match and match.group(2) == material_id:
            field = match.group(1)
            return {
                "formAva": "formAva",
                field: field,
                "id": material_id,
                "javax.faces.ViewState": viewstate,
            }
    return None


def filename_for(title: str, content_type: str | None, content_disposition: str | None) -> str:
    """Pick a download filename: server-supplied if present, else title + ext."""
    if content_disposition:
        match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', content_disposition)
        if match:
            return _sanitize(match.group(1).strip())
    base = _sanitize(title) or "material"
    ext = _EXT_BY_TYPE.get((content_type or "").split(";")[0].strip().lower(), "")
    if ext and not base.lower().endswith(ext):
        base += ext
    return base


def _sanitize(name: str) -> str:
    return _UNSAFE_RE.sub("_", name).strip().strip(".")
