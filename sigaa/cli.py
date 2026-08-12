"""Command-line interface. ``sync`` hits SIGAA; the rest read the local store."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

from . import setup_wizard
from .client import SigaaClient
from .config import Settings
from .curriculum import COMPONENT_VIEWS, curriculum_to_dict
from .documents import (
    ATESTADO_MATRICULA,
    DECLARACAO_VINCULO,
    HISTORICO,
    AcademicDocumentError,
    write_academic_document,
)
from .exporters.ics import build_calendar
from .http import AuthError
from .parsers.curriculum import CurriculumDataError
from .parsers.schedule import day_name, decode_schedule
from .parsers.sipac import SipacParseError
from .parsers.transcript import CraUnavailableError, TranscriptParseError
from .services import whatsnew
from .services.sync import sync
from .sipac import SipacClient, SipacProcessNotFound, public_process_to_dict
from .store.db import connect
from .store.repository import Repository


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    if getattr(args, "public_without_settings", False):
        settings = None
    else:
        settings = Settings()
        if getattr(args, "user", None):
            settings.username = args.user
        if getattr(args, "db", None):
            settings.db_path = args.db
    try:
        return args.func(args, settings)
    except KeyboardInterrupt:
        print("\nsetup cancelled", file=sys.stderr)
        return 130


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sigaa", description="SIGAA UFPB client")
    parser.add_argument("--user", help="override SIGAA username")
    parser.add_argument("--db", help="override SQLite path")
    sub = parser.add_subparsers(dest="command")

    p_login = sub.add_parser("login", help="store password in keychain and verify")
    p_login.set_defaults(func=_cmd_login)

    p_init = sub.add_parser("init", help="interactive first-run setup wizard")
    p_init.set_defaults(func=_cmd_init)

    p_sync = sub.add_parser("sync", help="fetch SIGAA and persist new news")
    p_sync.add_argument("--bodies", action="store_true", help="also fetch full news bodies")
    p_sync.add_argument("--json", action="store_true")
    p_sync.set_defaults(func=_cmd_sync)

    p_classes = sub.add_parser("classes", help="list classes from the store")
    p_classes.add_argument("--schedule", action="store_true", help="decode schedule codes")
    p_classes.add_argument("--json", action="store_true")
    p_classes.set_defaults(func=_cmd_classes)

    p_grades = sub.add_parser("grades", help="list grades from the store")
    p_grades.add_argument("--semester", help="filter by semester, e.g. 2025.1")
    p_grades.add_argument("--class", dest="klass", help="show one class's per-turma grade breakdown")
    p_grades.add_argument("--json", action="store_true")
    p_grades.set_defaults(func=_cmd_grades)

    p_curriculum = sub.add_parser(
        "curriculum",
        help="live CRA, curriculum progress, enrolled and pending components",
    )
    p_curriculum.add_argument(
        "--status",
        choices=COMPONENT_VIEWS,
        default="current",
        help="components to return (default: enrolled + required pending)",
    )
    p_curriculum.add_argument(
        "--required-only",
        action="store_true",
        help="hide optional components",
    )
    p_curriculum.add_argument("--period", type=int, help="filter by curriculum period")
    p_curriculum.add_argument(
        "--requirements",
        action="store_true",
        help="include prerequisite and corequisite expressions",
    )
    p_curriculum.add_argument(
        "--no-cra",
        action="store_true",
        help="skip the academic-transcript request",
    )
    p_curriculum.add_argument("--json", action="store_true")
    p_curriculum.set_defaults(func=_cmd_curriculum)

    p_cra = sub.add_parser("cra", help="show the official CRA from the transcript")
    p_cra.add_argument("--json", action="store_true")
    p_cra.set_defaults(func=_cmd_cra)

    p_sipac = sub.add_parser(
        "sipac",
        help="query SIPAC's public administrative-process portal",
    )
    sipac_sub = p_sipac.add_subparsers(dest="sipac_command")
    p_sipac_process = sipac_sub.add_parser(
        "process",
        help="look up one public process by its full number",
    )
    p_sipac_process.add_argument("number", help="e.g. 23074.056437/2026-26")
    p_sipac_process.add_argument("--json", action="store_true")
    p_sipac_process.set_defaults(
        func=_cmd_sipac_process,
        public_without_settings=True,
    )

    p_dl = sub.add_parser("deadlines", help="list assessment/task deadlines from the store")
    p_dl.add_argument("--class", dest="klass", help="filter by class code")
    p_dl.add_argument("--json", action="store_true")
    p_dl.set_defaults(func=_cmd_deadlines)

    p_ics = sub.add_parser("ics", help="export classes + deadlines as an .ics calendar")
    p_ics.add_argument("--out", help="output file (default: stdout)")
    p_ics.set_defaults(func=_cmd_ics)

    p_hist = sub.add_parser("historico", help="download the academic transcript PDF (networked)")
    p_hist.add_argument("--out", default="historico.pdf", help="output file (default: historico.pdf)")
    p_hist.add_argument("--force", action="store_true", help="overwrite an existing output file")
    p_hist.set_defaults(func=_cmd_academic_document, document_kind=HISTORICO)

    p_decl = sub.add_parser(
        "declaracao-vinculo",
        help="download the enrollment declaration PDF (networked)",
    )
    p_decl.add_argument(
        "--out",
        default="declaracao-vinculo.pdf",
        help="output file (default: declaracao-vinculo.pdf)",
    )
    p_decl.add_argument("--force", action="store_true", help="overwrite an existing output file")
    p_decl.set_defaults(func=_cmd_academic_document, document_kind=DECLARACAO_VINCULO)

    p_cert = sub.add_parser(
        "atestado-matricula",
        help="download the printable enrollment certificate HTML (networked)",
    )
    p_cert.add_argument(
        "--out",
        default="atestado-matricula.html",
        help="output file (default: atestado-matricula.html)",
    )
    p_cert.add_argument("--force", action="store_true", help="overwrite an existing output file")
    p_cert.set_defaults(func=_cmd_academic_document, document_kind=ATESTADO_MATRICULA)

    p_news = sub.add_parser("news", help="list news from the store")
    p_news.add_argument("--class", dest="klass", help="filter by class code")
    p_news.add_argument("--unread", action="store_true")
    p_news.add_argument("--mark-seen", action="store_true")
    p_news.add_argument("--json", action="store_true")
    p_news.set_defaults(func=_cmd_news)

    p_mat = sub.add_parser("materials", help="list class materials; download with --download/--download-all")
    p_mat.add_argument("--class", dest="klass", help="filter by class code")
    p_mat.add_argument("--kind", choices=["file", "link"], help="filter by kind")
    p_mat.add_argument("--download", metavar="ID", help="download one material by id (networked)")
    p_mat.add_argument("--download-all", action="store_true", help="download all file materials (networked)")
    p_mat.add_argument("--dir", default=".", help="output directory for downloads (default: .)")
    p_mat.add_argument("--json", action="store_true")
    p_mat.set_defaults(func=_cmd_materials)

    p_att = sub.add_parser("attendance", help="per-date attendance map for a class (networked)")
    p_att.add_argument("--class", dest="klass", required=True, help="class code")
    p_att.add_argument("--json", action="store_true")
    p_att.set_defaults(func=_cmd_attendance)

    p_plan = sub.add_parser("plan", help="Plano de Curso: cronograma + evaluation dates (networked)")
    p_plan.add_argument("--class", dest="klass", required=True, help="class code")
    p_plan.add_argument("--json", action="store_true")
    p_plan.set_defaults(func=_cmd_plan)

    p_whatsnew = sub.add_parser("whatsnew", help="everything unseen: news, materials, deadlines, grades")
    p_whatsnew.add_argument("--mark-seen", action="store_true", help="clear items after showing them")
    p_whatsnew.add_argument("--json", action="store_true")
    p_whatsnew.set_defaults(func=_cmd_whatsnew)

    p_watch = sub.add_parser("watch", help="sync repeatedly on an interval")
    p_watch.add_argument("--interval", type=int, default=900, help="seconds (default 900)")
    p_watch.add_argument("--bodies", action="store_true")
    p_watch.set_defaults(func=_cmd_watch)
    return parser


def _cmd_login(args, settings: Settings) -> int:
    setup_wizard.prompt_login(settings)
    return 0


def _cmd_init(args, settings: Settings) -> int:
    return setup_wizard.run_init(settings)


def _cmd_sync(args, settings: Settings) -> int:
    result = sync(settings, fetch_bodies=args.bodies)
    if args.json:
        print(json.dumps(_sync_json(result), ensure_ascii=False, indent=2))
        return 0 if result.ok else 1
    if not result.ok:
        print(f"sync failed: {result.error}", file=sys.stderr)
        return 1
    print(
        f"synced {result.turma_count} classes, {result.grade_count} grade rows — "
        f"{len(result.new_items)} new news, {len(result.new_deadlines)} new deadlines"
    )
    for item in result.new_items:
        print(f"  news + [{item.date}] {item.title}")
    for mat in result.new_materials:
        print(f"  material + ({mat.kind}) {mat.title}")
    for g in result.grade_updates:
        print(f"  grade + {g.id_turma}: {' '.join(g.units) or '—'} → {g.result or g.status or '—'}")
    for a in result.attendance_updates:
        print(f"  falta + {a.id_turma}: {a.total_absences}/{a.max_absences}")
    for dl in result.new_deadlines:
        print(f"  {dl.kind} + [{dl.date}] {dl.title}")
    return 0


def _cmd_classes(args, settings: Settings) -> int:
    repo = Repository(connect(settings.db_path))
    turmas = repo.get_turmas()
    if args.json:
        print(json.dumps([_turma_json(t, args.schedule) for t in turmas], ensure_ascii=False, indent=2))
        return 0
    if not turmas:
        print("no classes in store — run `sigaa sync` first")
        return 0
    for t in turmas:
        line = f"{t.code or '?':12} {t.name}"
        if args.schedule and t.schedule_raw:
            line += f"  [{_fmt_schedule(t.schedule_raw)}]"
        elif t.schedule_raw:
            line += f"  ({t.schedule_raw})"
        print(line)
    return 0


def _cmd_news(args, settings: Settings) -> int:
    repo = Repository(connect(settings.db_path))
    id_turma = None
    if args.klass:
        turma = repo.get_turma(args.klass)
        id_turma = turma.id_turma if turma else args.klass
    items = repo.get_news(id_turma=id_turma, unread_only=args.unread)
    if args.json:
        print(json.dumps([_news_json(n) for n in items], ensure_ascii=False, indent=2))
    else:
        if not items:
            print("no news in store — run `sigaa sync` first")
        for n in items:
            print(f"  [{n.date}] {n.title}")
    if args.mark_seen:
        repo.mark_news_seen([n.id for n in items])
    return 0


def _cmd_grades(args, settings: Settings) -> int:
    repo = Repository(connect(settings.db_path))
    if getattr(args, "klass", None):
        return _cmd_turma_grades(args, repo)
    grades = repo.get_grades(semester=args.semester)
    if args.json:
        print(json.dumps([_grade_json(g) for g in grades], ensure_ascii=False, indent=2))
        return 0
    if not grades:
        print("no grades in store — run `sigaa sync` first")
        return 0
    current = None
    for g in grades:
        if g.semester != current:
            current = g.semester
            print(f"\n{current}")
        units = " ".join(g.units) if g.units else "—"
        result = g.result or "—"
        print(f"  {g.code:12} {g.discipline[:40]:40} {units:20} = {result:5} {g.status or ''}")
    return 0


def _cmd_curriculum(args, settings: Settings) -> int:
    password = settings.resolve_password()
    if not settings.username or not password:
        print("missing credentials (set SIGAA_USER and keyring/SIGAA_PASS)", file=sys.stderr)
        return 1

    try:
        with SigaaClient(settings.username, password) as client:
            curriculum = client.get_curriculum_status(include_cra=not args.no_cra)
    except (
        AcademicDocumentError,
        AuthError,
        CurriculumDataError,
        TranscriptParseError,
        ValueError,
        httpx.HTTPError,
    ) as exc:
        print(f"curriculum lookup failed: {exc}", file=sys.stderr)
        return 1

    data = curriculum_to_dict(
        curriculum,
        status=args.status,
        required_only=args.required_only,
        period=args.period,
        include_requirements=args.requirements,
    )
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        _print_curriculum(data)
    return 0


def _cmd_cra(args, settings: Settings) -> int:
    password = settings.resolve_password()
    if not settings.username or not password:
        print("missing credentials (set SIGAA_USER and keyring/SIGAA_PASS)", file=sys.stderr)
        return 1

    try:
        with SigaaClient(settings.username, password) as client:
            cra = client.get_cra()
    except CraUnavailableError:
        data = {"value": None, "source": "unavailable"}
    except (
        AcademicDocumentError,
        AuthError,
        TranscriptParseError,
        ValueError,
        httpx.HTTPError,
    ) as exc:
        print(f"CRA lookup failed: {exc}", file=sys.stderr)
        return 1
    else:
        data = {"value": float(cra), "source": "academic_transcript"}

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif data["value"] is None:
        print("CRA: unavailable (the academic transcript does not report one yet)")
    else:
        print(f"CRA: {data['value']:.2f}")
        print("Source: official academic transcript")
    return 0


def _cmd_sipac_process(args, settings: Settings) -> int:
    del settings  # Public SIPAC lookup deliberately ignores stored credentials.
    try:
        with SipacClient() as client:
            process = client.get_public_process(args.number)
    except (SipacProcessNotFound, SipacParseError, ValueError, httpx.HTTPError) as exc:
        print(f"SIPAC process lookup failed: {exc}", file=sys.stderr)
        return 1

    data = public_process_to_dict(process)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        _print_sipac_process(data)
    return 0


def _cmd_turma_grades(args, repo: Repository) -> int:
    turma = repo.get_turma(args.klass)
    id_turma = turma.id_turma if turma else args.klass
    grades = repo.get_turma_grades(id_turma=id_turma)
    if args.json:
        print(json.dumps([_turma_grade_json(repo, g) for g in grades], ensure_ascii=False, indent=2))
        return 0
    if not grades:
        print("no per-class grades in store — run `sigaa sync` first")
        return 0
    for g in grades:
        t = repo.get_turma(g.id_turma)
        name = t.name if t else g.id_turma
        units = " ".join(g.units) if g.units else "—"
        print(f"{name}")
        print(f"  units: {units}   exame: {g.exam or '—'}   resultado: {g.result or '—'}")
        print(f"  faltas: {g.absences or '—'}   situação: {g.status or '—'}")
    return 0


def _cmd_deadlines(args, settings: Settings) -> int:
    repo = Repository(connect(settings.db_path))
    id_turma = None
    if args.klass:
        turma = repo.get_turma(args.klass)
        id_turma = turma.id_turma if turma else args.klass
    items = repo.get_deadlines(id_turma=id_turma)
    if args.json:
        print(json.dumps([_deadline_json(d) for d in items], ensure_ascii=False, indent=2))
        return 0
    if not items:
        print("no deadlines in store — run `sigaa sync` first")
    for d in items:
        print(f"  [{d.date}] ({d.kind}) {d.title}  {d.detail or ''}")
    return 0


def _cmd_ics(args, settings: Settings) -> int:
    repo = Repository(connect(settings.db_path))
    ics = build_calendar(repo.get_turmas(), repo.get_deadlines())
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(ics)
        print(f"wrote {args.out}")
    else:
        print(ics, end="")
    return 0


def _cmd_academic_document(args, settings: Settings) -> int:
    if Path(args.out).expanduser().exists() and not args.force:
        print(f"output already exists: {args.out} (pass --force to overwrite)", file=sys.stderr)
        return 1
    password = settings.resolve_password()
    if not settings.username or not password:
        print("missing credentials (set SIGAA_USER and keyring/SIGAA_PASS)", file=sys.stderr)
        return 1
    try:
        with SigaaClient(settings.username, password) as client:
            document = client.download_academic_document(args.document_kind)
    except (AcademicDocumentError, AuthError, ValueError) as exc:
        print(f"download failed: {exc}", file=sys.stderr)
        return 1
    try:
        write_academic_document(document, args.out, overwrite=args.force)
    except FileExistsError:
        print(f"output already exists: {args.out} (pass --force to overwrite)", file=sys.stderr)
        return 1
    print(f"wrote {args.out} ({len(document.content)} bytes, {document.media_type})")
    return 0


def _cmd_materials(args, settings: Settings) -> int:
    repo = Repository(connect(settings.db_path))
    id_turma = None
    if args.klass:
        turma = repo.get_turma(args.klass)
        id_turma = turma.id_turma if turma else args.klass

    if args.download or args.download_all:
        return _download_materials(args, settings, repo, id_turma)

    items = repo.get_materials(id_turma=id_turma, kind=args.kind)
    if args.json:
        print(json.dumps([_material_json(m) for m in items], ensure_ascii=False, indent=2))
        return 0
    if not items:
        print("no materials in store — run `sigaa sync` first")
        return 0
    for m in items:
        tag = "file" if m.kind == "file" else "link"
        print(f"  [{tag}] {m.id:>10}  {m.title}")
        if m.url:
            print(f"             {m.url}")
    return 0


def _download_materials(args, settings: Settings, repo: Repository, id_turma) -> int:
    password = settings.resolve_password()
    if not settings.username or not password:
        print("missing credentials (set SIGAA_USER and keyring/SIGAA_PASS)", file=sys.stderr)
        return 1

    stored = repo.get_materials(id_turma=id_turma, kind="file")
    if args.download:
        stored = [m for m in stored if m.id == args.download]
        if not stored:
            print(f"file material {args.download} not in store — run `sigaa sync` first", file=sys.stderr)
            return 1

    out_dir = Path(args.dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with SigaaClient(settings.username, password) as client:
        turmas = {t.id_turma: t for t in client.list_turmas()}
        for m in stored:
            turma = turmas.get(m.id_turma)
            if turma is None:
                print(f"  ! {m.title}: class not found", file=sys.stderr)
                continue
            content, filename = client.download_material(turma, m.id)
            path = out_dir / filename
            with open(path, "wb") as fh:
                fh.write(content)
            print(f"  wrote {path} ({len(content)} bytes)")
    return 0


def _live_turma(args, settings: Settings):
    """Resolve --class to (client, live Turma) or (None, None) after printing an error."""
    password = settings.resolve_password()
    if not settings.username or not password:
        print("missing credentials (set SIGAA_USER and keyring/SIGAA_PASS)", file=sys.stderr)
        return None, None
    repo = Repository(connect(settings.db_path))
    stored = repo.get_turma(args.klass)
    id_turma = stored.id_turma if stored else args.klass
    client = SigaaClient(settings.username, password)
    turma = next((t for t in client.list_turmas()
                  if t.id_turma == id_turma or t.code == args.klass), None)
    if turma is None:
        client.close()
        print(f"class {args.klass!r} not found", file=sys.stderr)
        return None, None
    return client, turma


def _cmd_attendance(args, settings: Settings) -> int:
    client, turma = _live_turma(args, settings)
    if client is None:
        return 1
    with client:
        attendance = client.get_attendance(turma)
    if attendance is None:
        print("attendance map not available for this class", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({
            "class_id": attendance.id_turma,
            "records": [{"date": r.date, "status": r.status, "justified": r.justified}
                        for r in attendance.records],
            "total_absences": attendance.total_absences,
            "justified_absences": attendance.justified_absences,
            "max_absences": attendance.max_absences,
        }, ensure_ascii=False, indent=2))
        return 0
    print(f"{turma.name}")
    for r in attendance.records:
        just = " (justificada)" if r.justified else ""
        print(f"  [{r.date}] {r.status}{just}")
    print(f"  faltas: {attendance.total_absences} / {attendance.max_absences} "
          f"(justificadas: {attendance.justified_absences})")
    return 0


def _cmd_plan(args, settings: Settings) -> int:
    client, turma = _live_turma(args, settings)
    if client is None:
        return 1
    with client:
        plan = client.get_course_plan(turma)
    if plan is None:
        print("course plan not available for this class", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({
            "class_id": plan.id_turma,
            "schedule": [{"start": e.start, "end": e.end, "description": e.description}
                         for e in plan.schedule],
            "evaluations": [{"date": e.date, "description": e.description}
                            for e in plan.evaluations],
        }, ensure_ascii=False, indent=2))
        return 0
    print(f"{turma.name}")
    if plan.evaluations:
        print("  avaliações:")
        for e in plan.evaluations:
            print(f"    [{e.date}] {e.description}")
    if plan.schedule:
        print("  cronograma:")
        for e in plan.schedule:
            span = e.start if e.start == e.end else f"{e.start} – {e.end}"
            print(f"    [{span}] {e.description}")
    return 0


def _cmd_whatsnew(args, settings: Settings) -> int:
    repo = Repository(connect(settings.db_path))
    feed = whatsnew.collect(repo)
    if args.json:
        print(json.dumps(_whatsnew_json(repo, feed), ensure_ascii=False, indent=2))
    elif feed.total() == 0:
        print("nothing new — run `sigaa sync` to check")
    else:
        for n in feed.news:
            print(f"  news      [{n.date}] {n.title}")
        for m in feed.materials:
            print(f"  material  ({m.kind}) {m.title}")
        for d in feed.deadlines:
            print(f"  deadline  [{d.date}] ({d.kind}) {d.title}")
        for g in feed.grades:
            t = repo.get_turma(g.id_turma)
            name = t.name if t else g.id_turma
            print(f"  grade     {name}: {' '.join(g.units) or '—'} → {g.result or g.status or '—'}")
        for a in feed.attendance:
            t = repo.get_turma(a.id_turma)
            name = t.name if t else a.id_turma
            last = f" (última: {a.records[-1].date} {a.records[-1].status})" if a.records else ""
            print(f"  falta     {name}: {a.total_absences}/{a.max_absences}{last}")
    if args.mark_seen:
        whatsnew.mark_seen(repo, feed)
    return 0


def _cmd_watch(args, settings: Settings) -> int:
    print(f"watching: sync every {args.interval}s (Ctrl-C to stop)")
    try:
        while True:
            result = sync(settings, fetch_bodies=args.bodies)
            status = "ok" if result.ok else f"error: {result.error}"
            print(f"[{time.strftime('%H:%M:%S')}] {len(result.new_items)} new — {status}")
            for item in result.new_items:
                print(f"  + [{item.date}] {item.title}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


def _print_curriculum(data: dict) -> None:
    print("Curriculum progress")
    if data["maximum_completion_term"]:
        print(f"  Maximum completion term: {data['maximum_completion_term']}")

    cra = data["cra"]
    if cra["value"] is not None:
        print(f"  CRA: {cra['value']:.2f} (official academic transcript)")
    elif cra["source"] == "not_requested":
        print("  CRA: not requested")
    else:
        print("  CRA: unavailable (not reported in the transcript yet)")

    semester = data["semester_workload_hours"]
    if semester["minimum"] is not None or semester["maximum"] is not None:
        minimum = semester["minimum"] if semester["minimum"] is not None else "?"
        maximum = semester["maximum"] if semester["maximum"] is not None else "?"
        print(f"  Semester workload: {minimum}-{maximum} h")

    print("\nWorkload")
    if not data["progress"]:
        print("  No workload progress reported.")
    for item in data["progress"]:
        percent = item["completed_percent"]
        print(
            f"  {item['description'][:28]:28} "
            f"{item['completed_hours']:>4}/{item['total_hours']:<4} h "
            f"{_progress_bar(percent)} {percent:>6.2f}%"
        )

    group_order = ("enrolled", "pending", "completed", "unknown")
    group_labels = {
        "enrolled": "Enrolled",
        "pending": "Pending",
        "completed": "Completed",
        "unknown": "Other status",
    }
    components = data["components"]
    for component_status in group_order:
        group = [
            component
            for component in components
            if component["status"] == component_status
        ]
        if not group:
            continue
        print(f"\n{group_labels[component_status]} ({len(group)})")
        for component in group:
            period = (
                f"P{component['period']}"
                if component["period"] is not None
                else "other"
            )
            nature = "required" if component["required"] else "option"
            print(
                f"  {component['code'][:12]:12} "
                f"{component['workload_hours']:>3} h "
                f"{period:>6} {nature:8} {component['name']}"
            )
            if "prerequisite" in component:
                print(f"      prerequisite: {component['prerequisite'] or '-'}")
                print(f"      corequisite:  {component['corequisite'] or '-'}")

    if not components:
        print("\nNo components match the selected filters.")

    counts = data["counts"]
    print(
        "\nSummary: "
        f"{counts['completed']} completed | "
        f"{counts['enrolled']} enrolled | "
        f"{counts['pending_required']} required pending | "
        f"{counts['pending_optional']} optional choices pending"
    )
    if data["query"]["status"] == "current" and counts["pending_optional"]:
        print(
            "Optional pending components are choices toward remaining workload, "
            "not all individually required. Use --status pending to inspect them."
        )


def _progress_bar(percent: float, width: int = 16) -> str:
    bounded = max(0.0, min(float(percent), 100.0))
    filled = round((bounded / 100.0) * width)
    return f"[{'#' * filled}{'-' * (width - filled)}]"


def _print_sipac_process(data: dict) -> None:
    print(f"{data['number']}  [{data['status'] or 'status unavailable'}]")
    print(f"  {data['detailed_subject'] or data['subject'] or 'No subject reported'}")
    if data["origin_unit"]:
        print(f"  Origin: {data['origin_unit']}")
    if data["opened_at"]:
        print(f"  Opened: {data['opened_at']}")
    print(
        f"  Interested parties: {len(data['interested_parties'])} | "
        f"Documents: {len(data['documents'])} | "
        f"Movements: {len(data['movements'])}"
    )
    for movement in data["movements"]:
        print(
            f"    {movement['sent_at']}: {movement['origin_unit']} "
            f"-> {movement['destination_unit']}"
        )
    print(f"  Public URL: {data['public_url']}")


def _fmt_schedule(raw: str) -> str:
    parts = []
    for s in decode_schedule(raw):
        days = "/".join(day_name(d) for d in s.days)
        parts.append(f"{days} {s.shift}{''.join(map(str, s.slots))}")
    return "; ".join(parts) if parts else raw


def _sync_json(result) -> dict:
    return {
        "ok": result.ok,
        "error": result.error,
        "classes": result.turma_count,
        "grade_rows": result.grade_count,
        "new_news": [_news_json(n) for n in result.new_items],
        "new_materials": [_material_json(m) for m in result.new_materials],
        "grade_updates": [
            {"class_id": g.id_turma, "units": g.units, "exam": g.exam,
             "result": g.result, "status": g.status}
            for g in result.grade_updates
        ],
        "new_deadlines": [_deadline_json(d) for d in result.new_deadlines],
        "attendance_updates": [_attendance_json(a) for a in result.attendance_updates],
    }


def _turma_json(t, with_schedule: bool) -> dict:
    data = {"code": t.code, "name": t.name, "room": t.room, "schedule_raw": t.schedule_raw}
    if with_schedule:
        data["schedule"] = [
            {"days": s.days, "shift": s.shift, "slots": s.slots}
            for s in decode_schedule(t.schedule_raw)
        ]
    return data


def _news_json(n) -> dict:
    return {"id": n.id, "id_turma": n.id_turma, "date": n.date, "title": n.title, "body": n.body}


def _material_json(m) -> dict:
    return {"id": m.id, "id_turma": m.id_turma, "topic": m.topic,
            "title": m.title, "kind": m.kind, "url": m.url}


def _grade_json(g) -> dict:
    return {
        "semester": g.semester, "code": g.code, "discipline": g.discipline,
        "units": g.units, "exam": g.exam, "result": g.result,
        "absences": g.absences, "status": g.status,
    }


def _whatsnew_json(repo, feed) -> dict:
    return {
        "total": feed.total(),
        "news": [_news_json(n) for n in feed.news],
        "materials": [_material_json(m) for m in feed.materials],
        "deadlines": [_deadline_json(d) for d in feed.deadlines],
        "grades": [_turma_grade_json(repo, g) for g in feed.grades],
        "attendance": [_attendance_json(a) for a in feed.attendance],
    }


def _attendance_json(a) -> dict:
    return {
        "class_id": a.id_turma,
        "records": [{"date": r.date, "status": r.status, "justified": r.justified}
                    for r in a.records],
        "total_absences": a.total_absences,
        "justified_absences": a.justified_absences,
        "max_absences": a.max_absences,
    }


def _turma_grade_json(repo, g) -> dict:
    t = repo.get_turma(g.id_turma)
    return {
        "class_id": g.id_turma, "code": t.code if t else None, "name": t.name if t else None,
        "units": g.units, "exam": g.exam, "result": g.result,
        "absences": g.absences, "status": g.status,
    }


def _deadline_json(d) -> dict:
    return {
        "id": d.id, "id_turma": d.id_turma, "kind": d.kind,
        "title": d.title, "date": d.date, "detail": d.detail,
    }


if __name__ == "__main__":
    raise SystemExit(main())
