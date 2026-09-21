"""CLI entry points for institution onboarding."""
import json
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from ..config import default_institution
from ..institutions import get
from .capture import capture, safe_url


def register(sub):
    group = sub.add_parser("onboard", help="private institution onboarding harness")
    commands = group.add_subparsers(dest="onboard_command")
    login = commands.add_parser(
        "login-probe", help="fingerprint a public login form; does not log in"
    )
    login.add_argument("--institution")
    login.add_argument("--url", help="public HTTPS login page for an unregistered institution")
    login.add_argument("--json", action="store_true")
    login.set_defaults(func=login_probe, public_without_settings=True)
    cap = commands.add_parser(
        "capture", help="capture private raw pages from the selected account"
    )
    cap.add_argument("--institution")
    cap.add_argument("--out", type=Path, default=Path("captures"))
    cap.add_argument("--include-matricula", action="store_true")
    cap.add_argument("--json", action="store_true")
    cap.set_defaults(func=run_capture)

    probe_cmd = commands.add_parser("probe", help="report parser status without student values")
    probe_cmd.add_argument("--from", dest="source", type=Path)
    probe_cmd.add_argument("--institution")
    probe_cmd.add_argument("--json", action="store_true")
    probe_cmd.set_defaults(func=run_probe)
    init = commands.add_parser("init", help="scaffold an unsupported institution provider")
    init.add_argument("key")
    init.add_argument("--host", required=True)
    init.set_defaults(func=run_init, public_without_settings=True)
    gate = commands.add_parser("check", help="scan private data, run tests and lint, check probe")
    gate.add_argument("--from", dest="source", type=Path, required=True)
    gate.add_argument("--explanations", type=Path, help="JSON feature-to-explanation mapping")
    gate.add_argument("--json", action="store_true")
    gate.set_defaults(func=run_check, public_without_settings=True)
    report_cmd = commands.add_parser("report", help="write compatibility documentation and a PR body")
    report_cmd.add_argument("--from", dest="source", type=Path, required=True)
    report_cmd.set_defaults(func=run_report, public_without_settings=True)


def login_probe(args, settings=None):
    profile = get(args.institution or default_institution()).profile
    url = args.url or profile.logon_url
    if args.url:
        parsed = urlsplit(url)
        profile = replace(profile, host=f"https://{parsed.netloc}")
    profile.validate_url(url)

    def validate(request):
        profile.validate_url(str(request.url))

    hooks = {"request": [validate]}
    with httpx.Client(follow_redirects=True, timeout=30, event_hooks=hooks) as client:
        response = client.get(url)
        response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    forms = []
    for form in soup.select("form"):
        fields = [str(node.get("name")) for node in form.select("input[name]")]
        action = str(form.get("action", ""))
        strategy = None
        if {"form:login", "form:senha"}.issubset(fields):
            strategy = "jsf-logon"
        elif form.select_one('input[type="password"]') and "logar.do" in action:
            strategy = "classic-struts"
        forms.append({"action": safe_url(action), "fields": fields, "strategy": strategy})
    print(json.dumps({"url": safe_url(response.url), "forms": forms}, indent=2))
    return 0 if any(form["strategy"] for form in forms) else 1


def run_capture(args, settings):
    directory, manifest = capture(
        settings, output=args.out, include_matricula=args.include_matricula
    )
    statuses = [entry["status"] for entry in manifest["entries"]]
    result = {
        "directory": str(directory),
        "captured": statuses.count("captured"),
        "nav_failed": statuses.count("nav_failed"),
    }
    print(json.dumps(result, indent=2))
    return 1 if result["nav_failed"] else 0


def run_probe(args, settings):
    from .probe import probe
    directory = args.source
    if directory is None:
        directory, _ = capture(settings)
    result = probe(directory)
    print(json.dumps(result, indent=2))
    return int(any(row["status"] in {"unrecognized", "nav_failed"} for row in result["features"]))


def run_init(args, settings=None):
    from .scaffold import scaffold
    print(scaffold(Path.cwd(), args.key, args.host))
    return 0


def run_check(args, settings=None):
    from .check import check
    explanations = json.loads(args.explanations.read_text()) if args.explanations else None
    result = check(Path.cwd(), args.source, explanations)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


def run_report(args, settings=None):
    from .report import report
    path, body = report(args.source, Path.cwd())
    print(f"Wrote {path}\n\n{body}")
    return 0
