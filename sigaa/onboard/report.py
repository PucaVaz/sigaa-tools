"""Render a public compatibility summary without copying capture values."""
from pathlib import Path
from .probe import probe


def report(directory: Path, root: Path):
    result = probe(directory)
    key = result["institution"]
    lines = [f"# {key.upper()} compatibility", "", f"Capture date: {result['captured_at']}",
             f"SIGAA version: {', '.join(result['versions']) or 'not identified'}", "",
             "| Feature | Sample | Status | Count | Variant |", "| --- | --- | --- | --- | --- |"]
    for row in result["features"]:
        lines.append(f"| {row['feature']} | {row['sample']} | {row['status']} | {row['count']} | {row['variant'] or '—'} |")
    path = root / "docs/institutions" / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    unresolved = sum(row["status"] in {"unrecognized", "nav_failed"} for row in result["features"])
    body = (f"Add {key.upper()} institution support.\n\n"
            f"Compatibility report: docs/institutions/{key}.md. "
            f"The probe has {unresolved} unrecognized or navigation-failed samples. "
            "See the report for unsupported and uncaptured features.\n\n"
            "Attach the tested commit and the actual onboard check result before requesting review.")
    return path, body
