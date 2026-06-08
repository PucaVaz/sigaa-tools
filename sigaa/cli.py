"""Command-line interface. ``sync`` hits SIGAA; the rest read the local store."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import time

from . import config
from .client import SigaaClient
from .config import Settings
from .exporters.ics import build_calendar
from .parsers.schedule import day_name, decode_schedule
from .services.sync import sync
from .store.db import connect
from .store.repository import Repository


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    settings = Settings()
    if getattr(args, "user", None):
        settings.username = args.user
    if getattr(args, "db", None):
        settings.db_path = args.db
    return args.func(args, settings)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sigaa", description="SIGAA UFPB client")
    parser.add_argument("--user", help="override SIGAA username")
    parser.add_argument("--db", help="override SQLite path")
    sub = parser.add_subparsers(dest="command")

    p_login = sub.add_parser("login", help="store password in keychain and verify")
    p_login.set_defaults(func=_cmd_login)

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
    p_grades.add_argument("--json", action="store_true")
    p_grades.set_defaults(func=_cmd_grades)

    p_dl = sub.add_parser("deadlines", help="list assessment/task deadlines from the store")
    p_dl.add_argument("--class", dest="klass", help="filter by class code")
    p_dl.add_argument("--json", action="store_true")
    p_dl.set_defaults(func=_cmd_deadlines)

    p_ics = sub.add_parser("ics", help="export classes + deadlines as an .ics calendar")
    p_ics.add_argument("--out", help="output file (default: stdout)")
    p_ics.set_defaults(func=_cmd_ics)

    p_hist = sub.add_parser("historico", help="download the academic transcript PDF (networked)")
    p_hist.add_argument("--out", default="historico.pdf", help="output file (default: historico.pdf)")
    p_hist.set_defaults(func=_cmd_historico)

    p_news = sub.add_parser("news", help="list news from the store")
    p_news.add_argument("--class", dest="klass", help="filter by class code")
    p_news.add_argument("--unread", action="store_true")
    p_news.add_argument("--mark-seen", action="store_true")
    p_news.add_argument("--json", action="store_true")
    p_news.set_defaults(func=_cmd_news)

    p_watch = sub.add_parser("watch", help="sync repeatedly on an interval")
    p_watch.add_argument("--interval", type=int, default=900, help="seconds (default 900)")
    p_watch.add_argument("--bodies", action="store_true")
    p_watch.set_defaults(func=_cmd_watch)
    return parser


def _cmd_login(args, settings: Settings) -> int:
    if not settings.username:
        settings.username = input("SIGAA username: ").strip()
    password = getpass.getpass("SIGAA password: ")
    try:
        import keyring

        keyring.set_password(config.KEYRING_SERVICE, settings.username, password)
        stored = "keychain"
    except Exception:
        stored = "not stored (keyring unavailable; use SIGAA_PASS env)"

    with SigaaClient(settings.username, password) as client:
        student = client.get_student()
    print(f"login ok: {student.name} ({student.matricula}) — password {stored}")
    return 0


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


def _cmd_historico(args, settings: Settings) -> int:
    password = settings.resolve_password()
    if not settings.username or not password:
        print("missing credentials (set SIGAA_USER and keyring/SIGAA_PASS)", file=sys.stderr)
        return 1
    with SigaaClient(settings.username, password) as client:
        pdf = client.get_historico_pdf()
    with open(args.out, "wb") as fh:
        fh.write(pdf)
    print(f"wrote {args.out} ({len(pdf)} bytes)")
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
        "new_deadlines": [_deadline_json(d) for d in result.new_deadlines],
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


def _grade_json(g) -> dict:
    return {
        "semester": g.semester, "code": g.code, "discipline": g.discipline,
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
