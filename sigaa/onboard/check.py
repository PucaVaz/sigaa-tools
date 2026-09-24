"""Deterministic privacy, test, lint, and compatibility gate."""
import json
import re
import subprocess
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from ..parsers._common import fold
from .probe import capture_file, probe

_PATTERNS = {
    "cpf": re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)"),
    "session": re.compile(r"(?:jsessionid|sigscookie)\s*[=:]\s*[\"']?[A-Za-z0-9_.-]{8,}", re.I),
    "cookie": re.compile(r"(?:set-cookie|cookie)\s*:\s*[^\r\n]+=[^\r\n;]+", re.I),
    "viewstate": re.compile(
        r"name=[\"']javax\.faces\.ViewState[\"'][^>]*value=[\"'](?!j_id\d+[\"'])[^\"']+[\"']",
        re.I,
    ),
}


_PRIVATE_SUFFIXES = {".db", ".sqlite3", ".pdf"}
_FORM_SECRET_FIELDS = 'input[name="javax.faces.ViewState"], input[type="password"]'


def _finding(source, index, category):
    return {"source": source, "file_index": index, "category": category}


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True).stdout


def _identity_values(value):
    if isinstance(value, dict):
        return [item for child in value.values() for item in _identity_values(child)]
    if isinstance(value, list):
        return [item for child in value for item in _identity_values(child)]
    return [value] if isinstance(value, str) and value else []


def _identity_pattern(identity: dict):
    """Match any identity value, each name token of 4+ letters, and the e-mail
    local part, accent- and case-insensitively. Tokens match as whole words only.

    This fails closed: a teacher or place sharing a surname with the student is
    also a finding (see docs/onboarding.md).
    """
    anywhere = [fold(value) for value in _identity_values(identity)]
    words = []
    name = identity.get("name")
    if isinstance(name, str):
        words += [token for token in fold(name).split() if len(token) >= 4]
    email = identity.get("email")
    if isinstance(email, str) and "@" in email:
        words.append(fold(email).split("@", 1)[0])
    alternatives = [re.escape(value) for value in anywhere if value]
    alternatives += [rf"(?<!\w){re.escape(word)}(?!\w)" for word in words if word]
    return re.compile("|".join(alternatives)) if alternatives else None


def privacy_findings(root: Path, identity: dict):
    """Scan staged blobs (not just working copies) and untracked source files.

    Findings expose categories and file indices, never matched private values.
    """
    staged = _git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    staged = staged.split(b"\0")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
    identity_pattern = _identity_pattern(identity)
    findings = []
    for source, paths in (("staged", staged), ("untracked", untracked)):
        for index, raw in enumerate(paths):
            if not raw:
                continue
            name = raw.decode("utf-8", "surrogateescape")
            path = root / name
            if ("captures" in Path(name).parts or path.suffix in _PRIVATE_SUFFIXES
                    or path.name.startswith(".env")):
                findings.append(_finding(source, index, "private_artifact"))
                continue
            if path.is_symlink():
                findings.append(_finding(source, index, "symlink"))
                continue
            content = _git(root, "show", f":{name}") if source == "staged" else path.read_bytes()
            encoding = "utf-16" if content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8"
            text = name + "\n" + content.decode(encoding, "replace")
            if identity_pattern and identity_pattern.search(fold(text)):
                findings.append(_finding(source, index, "identity"))
            for node in BeautifulSoup(text, "html.parser").select(_FORM_SECRET_FIELDS):
                value = str(node.get("value", ""))
                if value and not re.fullmatch(r"j_id\d+", value):
                    findings.append(_finding(source, index, "form_secret"))
            for candidate in re.findall(r"(?<!\d)\d{11}(?!\d)", text):
                if _valid_cpf(candidate):
                    findings.append(_finding(source, index, "cpf"))
                    break
            for category, pattern in _PATTERNS.items():
                if pattern.search(text):
                    findings.append(_finding(source, index, category))
    return findings


def check(root: Path, directory: Path, explanations=None):
    identity = json.loads(capture_file(directory, "identity.json").read_text())
    if not all(identity.get(key) for key in ("username", "name", "matricula", "email")):
        return {"ok": False, "error": "private identity.json lacks username, name, matricula, or email"}
    findings = privacy_findings(root, identity)
    if findings:
        return {"ok": False, "privacy_findings": findings}
    result = probe(directory)
    explanations = explanations or {}
    unresolved = [row["feature"] for row in result["features"]
                  if row["status"] in {"unrecognized", "nav_failed"}
                  and not str(explanations.get(row["feature"], "")).strip()]
    if not any(row["status"] in {"ok", "empty_confirmed"} for row in result["features"]):
        unresolved.append("no_verified_features")
    checks = {}
    for label, command in (("pytest", [sys.executable, "-m", "pytest", "-q"]),
                           ("ruff", [sys.executable, "-m", "ruff", "check", "."])):
        checks[label] = subprocess.run(command, cwd=root, capture_output=True).returncode
    return {"ok": not unresolved and all(code == 0 for code in checks.values()),
            "checks": checks, "unresolved_features": sorted(set(unresolved)),
            "not_captured": sorted({row["feature"] for row in result["features"]
                                    if row["status"] == "not_captured"})}


def _valid_cpf(value):
    digits = [int(c) for c in value]
    if len(set(digits)) == 1:
        return False
    for length in (9, 10):
        check_digit = (sum(digits[i] * (length + 1 - i) for i in range(length)) * 10) % 11
        if digits[length] != (0 if check_digit == 10 else check_digit):
            return False
    return True
