"""Deterministic privacy, test, lint, and compatibility gate."""
import json
import re
import subprocess
import sys
from pathlib import Path

from .probe import probe, capture_file
from bs4 import BeautifulSoup

_PATTERNS = {
    "cpf": re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)"),
    "session": re.compile(r"(?:jsessionid|sigscookie)\s*[=:]\s*[\"']?[A-Za-z0-9_.-]{8,}", re.I),
    "cookie": re.compile(r"(?:set-cookie|cookie)\s*:\s*[^\r\n]+=[^\r\n;]+", re.I),
    "viewstate": re.compile(r"name=[\"']javax\.faces\.ViewState[\"'][^>]*value=[\"'](?!j_id\d+[\"'])[^\"']+[\"']", re.I),
}


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True).stdout


def _identity_values(value):
    if isinstance(value, dict):
        return [item for child in value.values() for item in _identity_values(child)]
    if isinstance(value, list):
        return [item for child in value for item in _identity_values(child)]
    return [value] if isinstance(value, str) and value else []


def privacy_findings(root: Path, identity: dict):
    """Scan staged blobs (not just working copies) and untracked source files.

    Findings expose categories and file indices, never matched private values.
    """
    staged = _git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split(b"\0")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
    values = _identity_values(identity)
    findings = []
    for source, paths in (("staged", staged), ("untracked", untracked)):
        for index, raw in enumerate(paths):
            if not raw:
                continue
            name = raw.decode("utf-8", "surrogateescape")
            path = root / name
            if "captures" in Path(name).parts or path.suffix in {".db", ".sqlite3", ".pdf"} or path.name.startswith(".env"):
                findings.append({"source": source, "file_index": index, "category": "private_artifact"})
                continue
            if path.is_symlink():
                findings.append({"source": source, "file_index": index, "category": "symlink"})
                continue
            content = _git(root, "show", f":{name}") if source == "staged" else path.read_bytes()
            encoding = "utf-16" if content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8"
            text = name + "\n" + content.decode(encoding, "replace")
            if any(value.casefold() in text.casefold() for value in values):
                findings.append({"source": source, "file_index": index, "category": "identity"})
            for node in BeautifulSoup(text, "html.parser").select('input[name="javax.faces.ViewState"], input[type="password"]'):
                value = str(node.get("value", ""))
                if value and not re.fullmatch(r"j_id\d+", value):
                    findings.append({"source": source, "file_index": index, "category": "form_secret"})
            for candidate in re.findall(r"(?<!\d)\d{11}(?!\d)", text):
                if _valid_cpf(candidate):
                    findings.append({"source": source, "file_index": index, "category": "cpf"})
                    break
            for category, pattern in _PATTERNS.items():
                if pattern.search(text):
                    findings.append({"source": source, "file_index": index, "category": category})
    return findings


def check(root: Path, directory: Path, explanations=None):
    identity = json.loads(capture_file(directory, "identity.json").read_text())
    if not all(identity.get(key) for key in ("username", "name", "matricula")):
        return {"ok": False, "error": "private identity.json lacks username, name, or matricula"}
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
