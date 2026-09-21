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
