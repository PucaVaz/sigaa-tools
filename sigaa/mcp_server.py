"""MCP server exposing SIGAA to code agents.

Reads are served from the local store (instant, offline). ``sigaa_sync`` is the
only networked tool. Run: ``python -m sigaa.mcp_server`` (stdio).
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from .client import SigaaClient
from .config import Settings
from .exporters.ics import build_calendar
from .parsers.schedule import day_name, decode_schedule
from .services import whatsnew
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
def sigaa_list_materials(class_code: str | None = None, kind: str | None = None) -> list[dict]:
    """List class materials (slides, lists, links) from the store. Filter by class or kind (file/link)."""
    repo = _repo()
    id_turma = None
    if class_code:
        turma = repo.get_turma(class_code)
        id_turma = turma.id_turma if turma else class_code
    return [
        {"id": m.id, "class_id": m.id_turma, "topic": m.topic, "title": m.title,
         "kind": m.kind, "url": m.url}
        for m in repo.get_materials(id_turma=id_turma, kind=kind)
    ]


@mcp.tool()
def sigaa_download_material(material_id: str, path: str | None = None) -> str:
    """Download an uploaded class material (file) by its id. Networked. Returns the path written."""
    repo = _repo()
    material = next((m for m in repo.get_materials() if m.id == material_id), None)
    if material is None:
        return f"material id {material_id} not found in store; run sigaa_sync first"
    if material.kind != "file":
        return f"material {material_id} is an external link: {material.url}"

    settings = Settings()
    password = settings.resolve_password()
    if not settings.username or not password:
        return "no credentials available"
    with SigaaClient(settings.username, password) as client:
        turma = next((t for t in client.list_turmas() if t.id_turma == material.id_turma), None)
        if turma is None:
            return "could not locate the class for this material"
        content, filename = client.download_material(turma, material_id)
    out = path or filename
    with open(out, "wb") as fh:
        fh.write(content)
    return f"wrote {out} ({len(content)} bytes)"


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
def sigaa_list_grades(semester: str | None = None) -> list[dict]:
    """List grades from the store, optionally filtered by semester (e.g. 2025.1)."""
    return [
        {
            "semester": g.semester,
            "code": g.code,
            "discipline": g.discipline,
            "units": g.units,
            "result": g.result,
            "absences": g.absences,
            "status": g.status,
        }
        for g in _repo().get_grades(semester=semester)
    ]


@mcp.tool()
def sigaa_get_turma_grades(class_code: str | None = None) -> list[dict]:
    """Per-class grade breakdown (Ver Notas): Unid. 1..N, Exame, Resultado, Faltas, Situação."""
    repo = _repo()
    id_turma = None
    if class_code:
        turma = repo.get_turma(class_code)
        id_turma = turma.id_turma if turma else class_code
    out = []
    for g in repo.get_turma_grades(id_turma=id_turma):
        turma = repo.get_turma(g.id_turma)
        out.append(
            {
                "class_id": g.id_turma,
                "code": turma.code if turma else None,
                "name": turma.name if turma else None,
                "units": g.units,
                "exam": g.exam,
                "result": g.result,
                "absences": g.absences,
                "status": g.status,
            }
        )
    return out


@mcp.tool()
def sigaa_get_attendance(class_code: str) -> dict:
    """Per-date attendance map (Frequência) for a class. Networked (live fetch)."""
    client, turma, error = _live_turma(class_code)
    if error:
        return {"error": error}
    with client:
        attendance = client.get_attendance(turma)
    if attendance is None:
        return {"error": "attendance map not available for this class"}
    return {
        "class_id": attendance.id_turma,
        "records": [
            {"date": r.date, "status": r.status, "justified": r.justified}
            for r in attendance.records
        ],
        "total_absences": attendance.total_absences,
        "justified_absences": attendance.justified_absences,
        "max_absences": attendance.max_absences,
    }


@mcp.tool()
def sigaa_get_course_plan(class_code: str) -> dict:
    """Plano de Curso for a class: lecture schedule + scheduled evaluation dates.
    Networked (live fetch)."""
    client, turma, error = _live_turma(class_code)
    if error:
        return {"error": error}
    with client:
        plan = client.get_course_plan(turma)
    if plan is None:
        return {"error": "course plan not available for this class"}
    return {
        "class_id": plan.id_turma,
        "schedule": [
            {"start": e.start, "end": e.end, "description": e.description}
            for e in plan.schedule
        ],
        "evaluations": [{"date": e.date, "description": e.description}
                        for e in plan.evaluations],
    }


def _live_turma(class_code: str):
    """Resolve a class code to (authenticated client, live Turma, error)."""
    settings = Settings()
    password = settings.resolve_password()
    if not settings.username or not password:
        return None, None, "no credentials available"
    repo = _repo()
    stored = repo.get_turma(class_code)
    id_turma = stored.id_turma if stored else class_code
    client = SigaaClient(settings.username, password)
    turma = next((t for t in client.list_turmas()
                  if t.id_turma == id_turma or t.code == class_code), None)
    if turma is None:
        client.close()
        return None, None, f"class {class_code!r} not found"
    return client, turma, None


@mcp.tool()
def sigaa_list_deadlines(class_code: str | None = None) -> list[dict]:
    """List assessment/task deadlines from the store, optionally filtered by class."""
    repo = _repo()
    id_turma = None
    if class_code:
        turma = repo.get_turma(class_code)
        id_turma = turma.id_turma if turma else class_code
    return [
        {"id": d.id, "class_id": d.id_turma, "kind": d.kind, "title": d.title,
         "date": d.date, "detail": d.detail}
        for d in repo.get_deadlines(id_turma=id_turma)
    ]


@mcp.tool()
def sigaa_get_tarefa_body(deadline_id: str) -> dict:
    """Get a task/assignment's full details (Descrição, Período, ...) by its deadline id.
    Served from cache; fetched live if missing. Run sigaa_sync first to learn ids."""
    repo = _repo()
    item = next((d for d in repo.get_deadlines() if d.id == deadline_id), None)
    if item is None:
        return {"error": f"deadline id {deadline_id} not found in store; run sigaa_sync first"}
    if item.body:
        return {"id": item.id, "title": item.title, "fields": json.loads(item.body)}

    settings = Settings()
    password = settings.resolve_password()
    if not settings.username or not password:
        return {"error": "body not cached and no credentials available to fetch it"}
    with SigaaClient(settings.username, password) as client:
        fields = client.get_tarefa_body(deadline_id)
    if not fields:
        return {"error": "no detail form on this event (it may not be a tarefa)"}
    repo.update_deadline_body(deadline_id, json.dumps(fields, ensure_ascii=False))
    return {"id": item.id, "title": item.title, "fields": fields}


@mcp.tool()
def sigaa_download_tarefa_anexo(deadline_id: str, path: str | None = None) -> str:
    """Download a task's teacher attachment (Arquivo do Professor) by its deadline id.
    Networked. Returns the path written, or a message if the task has no attachment."""
    repo = _repo()
    item = next((d for d in repo.get_deadlines() if d.id == deadline_id), None)
    if item is None:
        return f"deadline id {deadline_id} not found in store; run sigaa_sync first"

    settings = Settings()
    password = settings.resolve_password()
    if not settings.username or not password:
        return "no credentials available"
    with SigaaClient(settings.username, password) as client:
        result = client.download_tarefa_attachment(deadline_id)
    if result is None:
        return "no teacher attachment on this task (or it is not a tarefa)"
    content, filename = result
    out = path or filename
    with open(out, "wb") as fh:
        fh.write(content)
    return f"wrote {out} ({len(content)} bytes)"


@mcp.tool()
def sigaa_export_ics() -> str:
    """Return an iCalendar (.ics) feed of classes + deadlines from the store."""
    repo = _repo()
    return build_calendar(repo.get_turmas(), repo.get_deadlines())


@mcp.tool()
def sigaa_whats_new(mark_seen: bool = False) -> dict:
    """Everything unseen since last check: news, materials, deadlines, and posted
    grade changes. Pass mark_seen=true to clear them after reading."""
    repo = _repo()
    feed = whatsnew.collect(repo)
    out = {
        "total": feed.total(),
        "news": [{"id": n.id, "class_id": n.id_turma, "date": n.date, "title": n.title}
                 for n in feed.news],
        "materials": [{"id": m.id, "class_id": m.id_turma, "topic": m.topic,
                       "title": m.title, "kind": m.kind, "url": m.url} for m in feed.materials],
        "deadlines": [{"id": d.id, "class_id": d.id_turma, "kind": d.kind,
                       "title": d.title, "date": d.date} for d in feed.deadlines],
        "grades": [_grade_update(repo, g) for g in feed.grades],
        "attendance": [_attendance_update(repo, a) for a in feed.attendance],
    }
    if mark_seen:
        whatsnew.mark_seen(repo, feed)
    return out


def _grade_update(repo: Repository, g) -> dict:
    turma = repo.get_turma(g.id_turma)
    return {
        "class_id": g.id_turma,
        "code": turma.code if turma else None,
        "name": turma.name if turma else None,
        "units": g.units, "exam": g.exam, "result": g.result, "status": g.status,
    }


def _attendance_update(repo: Repository, a) -> dict:
    turma = repo.get_turma(a.id_turma)
    return {
        "class_id": a.id_turma,
        "code": turma.code if turma else None,
        "name": turma.name if turma else None,
        "total_absences": a.total_absences,
        "max_absences": a.max_absences,
        "last_record": (
            {"date": a.records[-1].date, "status": a.records[-1].status}
            if a.records else None
        ),
    }


@mcp.tool()
def sigaa_download_historico(path: str = "historico.pdf") -> str:
    """Download the academic transcript PDF to a path. Networked. Returns the path."""
    settings = Settings()
    password = settings.resolve_password()
    if not settings.username or not password:
        return "no credentials available"
    with SigaaClient(settings.username, password) as client:
        pdf = client.get_historico_pdf()
    with open(path, "wb") as fh:
        fh.write(pdf)
    return f"wrote {path} ({len(pdf)} bytes)"


@mcp.tool()
def sigaa_sync(fetch_bodies: bool = False) -> dict:
    """Refresh from SIGAA and persist new news. The only networked tool."""
    result = run_sync(Settings(), fetch_bodies=fetch_bodies)
    return {
        "ok": result.ok,
        "error": result.error,
        "classes": result.turma_count,
        "grade_rows": result.grade_count,
        "new_news": [{"id": n.id, "date": n.date, "title": n.title} for n in result.new_items],
        "new_materials": [
            {"id": m.id, "topic": m.topic, "title": m.title, "kind": m.kind}
            for m in result.new_materials
        ],
        "grade_updates": [_grade_update(_repo(), g) for g in result.grade_updates],
        "attendance_updates": [_attendance_update(_repo(), a) for a in result.attendance_updates],
        "new_deadlines": [
            {"id": d.id, "date": d.date, "kind": d.kind, "title": d.title}
            for d in result.new_deadlines
        ],
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
