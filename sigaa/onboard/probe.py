"""Offline, value-free parser diagnostics from immutable capture bodies."""
from dataclasses import fields, is_dataclass
import hashlib
import json
from pathlib import Path

from ..errors import ParseError
from ..institutions import get
from ..parsers._common import page_fingerprint
from ..parsers._variants import resolve_variant
from .features import FEATURES


def capture_file(directory: Path, name: str):
    candidate = directory / name
    if Path(name).name != name or candidate.is_symlink() or not candidate.is_file():
        raise ValueError("invalid capture file")
    return candidate


def summarize(value):
    """Only counts and model field-presence booleans may leave a capture."""
    if value is None:
        return 0, {}
    if isinstance(value, list):
        count = len(value)
        present = {}
        for item in value:
            if is_dataclass(item):
                for field in fields(item):
                    present[field.name] = present.get(field.name, False) or bool(getattr(item, field.name))
        return count, present
    if is_dataclass(value):
        present = {field.name: bool(getattr(value, field.name)) for field in fields(value)}
        if hasattr(value, "records"):
            count = len(value.records)
        elif hasattr(value, "schedule") and hasattr(value, "evaluations"):
            count = len(value.schedule) + len(value.evaluations)
        elif hasattr(value, "units"):
            count = len(value.units) + int(bool(value.result))
        else:
            count = 1
        return count, present
    # Do not expose arbitrary task labels as keys; they come from private HTML.
    return len(value) if isinstance(value, dict) else int(bool(value)), {"content": bool(value)}


def probe(directory: Path):
    manifest = json.loads(capture_file(directory, "manifest.json").read_text())
    provider = get(manifest["institution"])
    entries = manifest.get("entries", [])
    results = []
    for feature in FEATURES:
        captured = [e for e in entries if e.get("feature") == feature.key]
        if not captured:
            captured = [{"status": "not_captured"}]
        for index, entry in enumerate(captured, 1):
            row = {"feature": feature.key, "sample": index, "status": "not_captured",
                   "count": 0, "fields": {}, "variant": None, "fingerprint": None}
            results.append(row)
            if feature.capability not in provider.profile.capabilities:
                row["status"] = "unsupported"
                continue
            if entry.get("status") != "captured":
                row["status"] = entry.get("status") if entry.get("status") in {
                    "unsupported", "nav_failed", "not_captured"} else "unrecognized"
                continue
            try:
                body = capture_file(directory, entry["file"]).read_bytes()
                if hashlib.sha256(body).hexdigest() != entry.get("sha256"):
                    raise ValueError("capture hash mismatch")
                html = body.decode(entry.get("encoding") or "utf-8")
                row["fingerprint"] = page_fingerprint(html)
                result = feature.parse(html, entry.get("turma_id"))
                variants = getattr(feature.parser, "variants", ())
                row["variant"] = (resolve_variant(feature.key, html, variants).name
                                  if variants else feature.key + "-builtin")
                row["count"], row["fields"] = summarize(result)
                row["status"] = "ok" if row["count"] else "empty_confirmed"
            except (ParseError, ValueError, KeyError, TypeError, OSError, LookupError):
                row["status"] = "unrecognized"
    return {"institution": provider.profile.key, "captured_at": manifest.get("captured_at"),
            "versions": sorted({str(e["sigaa_version"]) for e in entries if e.get("sigaa_version")}),
            "features": results}
