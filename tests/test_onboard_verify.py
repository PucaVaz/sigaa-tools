import hashlib
import json
from pathlib import Path
import secrets
import subprocess

import pytest

from sigaa.onboard.check import privacy_findings, check
from sigaa.onboard.probe import probe
from sigaa.onboard.report import report
from sigaa.onboard.scaffold import scaffold

FIXTURES = Path(__file__).parent / "fixtures"


def _capture(tmp_path, feature="student", filename="portal.html"):
    directory = tmp_path / "capture"
    directory.mkdir()
    body = (FIXTURES / filename).read_bytes()
    (directory / "page.body").write_bytes(body)
    manifest = {"institution": "ufpb", "captured_at": "2026-09-21T000000Z", "entries": [
        {"feature": feature, "status": "captured", "file": "page.body", "turma_id": "123",
         "sha256": hashlib.sha256(body).hexdigest(), "encoding": "utf-8"}
    ]}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return directory


def test_probe_and_report_do_not_expose_student_values(tmp_path):
    directory = _capture(tmp_path)
    result = probe(directory)
    student = next(row for row in result["features"] if row["feature"] == "student")
    assert student["status"] == "ok"
    assert student["variant"] == "beta-student"
    assert student["fields"]["name"] is True
    assert any(row["status"] == "not_captured" for row in result["features"])
    path, body = report(directory, tmp_path)
    output = json.dumps(result) + path.read_text() + body
    for private in ("FULANO DE TAL SILVA", "12345678901", "fulano@academico.ufpb.br"):
        assert private not in output


def test_probe_detects_tampering_and_never_reads_outside_capture(tmp_path):
    directory = _capture(tmp_path)
    (directory / "page.body").write_text("changed")
    assert probe(directory)["features"][0]["status"] == "unrecognized"
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["entries"][0]["file"] = "../outside"
    (directory / "manifest.json").write_text(json.dumps(manifest))
    assert probe(directory)["features"][0]["status"] == "unrecognized"


def test_probe_reports_known_empty_and_changed_page(tmp_path):
    directory = _capture(tmp_path, "professors", "professors_empty.html")
    row = next(row for row in probe(directory)["features"] if row["feature"] == "professors")
    assert row["status"] == "empty_confirmed"
    assert row["count"] == 0


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_privacy_gate_scans_staged_blob_even_when_working_copy_is_clean(tmp_path):
    root = _repo(tmp_path)
    identity = {"name": secrets.token_hex(), "username": secrets.token_hex(), "matricula": secrets.token_hex()}
    target = root / "fixture.html"
    target.write_text(identity["matricula"])
    subprocess.run(["git", "add", "fixture.html"], cwd=root, check=True)
    target.write_text("sanitized working copy")
    findings = privacy_findings(root, identity)
    assert any(f["category"] == "identity" and f["source"] == "staged" for f in findings)
    assert identity["matricula"] not in json.dumps(findings)


def test_privacy_gate_scans_untracked_and_reversed_viewstate_attributes(tmp_path):
    root = _repo(tmp_path)
    token = secrets.token_urlsafe()
    (root / "fixture.html").write_text(f'<input value="{token}" name="javax.faces.ViewState">')
    assert any(f["category"] == "form_secret" for f in privacy_findings(root, {}))


def test_check_refuses_incomplete_identity_before_tests(tmp_path):
    root = _repo(tmp_path)
    directory = _capture(tmp_path)
    (directory / "identity.json").write_text('{}')
    assert check(root, directory)["ok"] is False


def test_scaffold_rejects_invalid_host_key_and_existing_provider(tmp_path):
    root = tmp_path
    (root / "sigaa/institutions").mkdir(parents=True)
    (root / "sigaa/institutions/registry.py").write_text("# registry\n")
    for key, host in [("../bad", "https://example.edu"), ("example", "http://example.edu"),
                      ("example", "https://example.edu/path")]:
        with pytest.raises(ValueError):
            scaffold(root, key, host)
    target = scaffold(root, "example", "https://example.edu")
    compile(target.read_text(), str(target), "exec")
    assert "capabilities=frozenset()" in target.read_text()
    assert (root / "tests/fixtures/example").is_dir()
    with pytest.raises(ValueError, match="already exists"):
        scaffold(root, "example", "https://example.edu")


def test_check_reports_test_and_lint_failures_without_hiding_them(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _repo(root)
    directory = _capture(tmp_path)
    identity = {key: secrets.token_hex() for key in ("name", "username", "matricula")}
    (directory / "identity.json").write_text(json.dumps(identity))
    (root / "test_subject.py").write_text("import os\n\ndef test_failure():\n    assert False\n")
    result = check(root, directory)
    assert result["ok"] is False
    assert result["checks"]["pytest"] != 0
    assert result["checks"]["ruff"] != 0
    assert "attendance" in result["not_captured"]
