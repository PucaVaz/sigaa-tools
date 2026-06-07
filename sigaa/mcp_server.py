"""MCP server exposing SIGAA to code agents.

Reads are served from the local store (instant, offline). ``sigaa_sync`` is the
only networked tool. Run: ``python -m sigaa.mcp_server`` (stdio).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .client import SigaaClient
from .config import Settings
from .parsers.schedule import day_name, decode_schedule
from .services.sync import sync as run_sync
from .store.db import connect
from .store.repository import Repository

mcp = FastMCP("sigaa-ufpb")


def _repo() -> Repository:
    return Repository(connect(Settings().db_path))


@mcp.tool()
def sigaa_list_classes() -> list[dict]:
    """List enrolled classes from the local store."""
    return [
        {
            "code": t.code,
            "name": t.name,
            "room": t.room,
            "schedule_raw": t.schedule_raw,
            "id_turma": t.id_turma,
        }
        for t in _repo().get_turmas()
    ]


@mcp.tool()
def sigaa_list_news(
    class_code: str | None = None, unread_only: bool = False, since: str | None = None
) -> list[dict]:
    """List class news from the store. Optionally filter by class, unread, or date (DD/MM/YYYY ...)."""
    repo = _repo()
    id_turma = None
    if class_code:
        turma = repo.get_turma(class_code)
        id_turma = turma.id_turma if turma else class_code
    items = repo.get_news(id_turma=id_turma, unread_only=unread_only, since=since)
    return [{"id": n.id, "class_id": n.id_turma, "date": n.date, "title": n.title} for n in items]


@mcp.tool()
def sigaa_get_news_body(news_id: str) -> str:
    """Get a news item's full text. Served from cache; fetched live if missing."""
    repo = _repo()
    matches = [n for n in repo.get_news() if n.id == news_id]
    if not matches:
        return f"news id {news_id} not found in store; run sigaa_sync first"
    item = matches[0]
    if item.body:
        return item.body

    settings = Settings()
    password = settings.resolve_password()
    if not settings.username or not password:
        return "body not cached and no credentials available to fetch it"
    with SigaaClient(settings.username, password) as client:
        turma = next((t for t in client.list_turmas() if t.id_turma == item.id_turma), None)
        if turma is None:
            return "could not locate the class to fetch this news body"
        body = client.get_news_body(turma, news_id) or ""
    if body:
        repo.update_news_body(news_id, body)
    return body


@mcp.tool()
def sigaa_get_schedule(class_code: str | None = None) -> list[dict]:
    """Decoded weekly schedule (days/shift/slots) for one or all classes."""
    repo = _repo()
    turmas = [repo.get_turma(class_code)] if class_code else repo.get_turmas()
    out = []
    for t in turmas:
        if not t:
            continue
        out.append(
            {
                "code": t.code,
                "name": t.name,
                "sessions": [
                    {
                        "days": [day_name(d) for d in s.days],
                        "shift": s.shift,
                        "slots": s.slots,
                    }
                    for s in decode_schedule(t.schedule_raw)
                ],
            }
        )
    return out


@mcp.tool()
def sigaa_sync(fetch_bodies: bool = False) -> dict:
    """Refresh from SIGAA and persist new news. The only networked tool."""
    result = run_sync(Settings(), fetch_bodies=fetch_bodies)
    return {
        "ok": result.ok,
        "error": result.error,
        "classes": result.turma_count,
        "new": [{"id": n.id, "date": n.date, "title": n.title} for n in result.new_items],
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
