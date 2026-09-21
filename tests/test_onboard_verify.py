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
    for key, host in [("../bad", "https://example.edu"), ("example", "http://example.edu"),
                      ("example", "https://example.edu/path"), ("registry", "https://example.edu"),
                      ("auth_example", "https://example.edu")]:
        with pytest.raises(ValueError):
            scaffold(root, key, host)
    target = scaffold(root, "example", "https://example.edu")
    compile(target.read_text(), str(target), "exec")
    assert "capabilities=frozenset()" in target.read_text()
    assert (root / "tests/fixtures/example").is_dir()
    assert not (root / "sigaa/institutions/registry.py").exists()
    with pytest.raises(ValueError, match="already exists"):
        scaffold(root, "example", "https://example.edu")


def test_scaffolded_provider_is_discovered_and_inherits_nothing(tmp_path, monkeypatch):
    import sys

    from sigaa import institutions
    from sigaa.errors import NavigationError
    from sigaa.institutions import registry

    (tmp_path / "sigaa/institutions").mkdir(parents=True)
    scaffold(tmp_path, "example", "https://sigaa.example.edu")
    monkeypatch.setattr(institutions, "__path__",
                        [*institutions.__path__, str(tmp_path / "sigaa/institutions")])
    monkeypatch.delitem(sys.modules, "sigaa.institutions.example", raising=False)
    try:
        providers = registry._discover()
    finally:
        sys.modules.pop("sigaa.institutions.example", None)

    assert list(providers)[0] == "ufpb"
    profile, navigator = providers["example"].profile, providers["example"].navigator
    assert profile.host == "https://sigaa.example.edu"
    assert profile.logon_url.startswith(profile.host)
    assert profile.capabilities == frozenset() and profile.menu_labels == {}
    urls = [getattr(profile, name) for name in profile.__dataclass_fields__
            if name.endswith("_url") and name != "logon_url"]
    assert urls and not any(urls)
    assert type(navigator).__mro__[1] is object
    calls = [("login", None), ("looks_logged_out", "<html></html>"),
             ("portal_menu_post", None, "", "Minhas Notas"), ("enter_turma", None, "", None),
             ("turma_menu_post", None, "", "Ver Notas"), ("open_event", None, "", "1")]
    for name, *args in calls:
        with pytest.raises(NavigationError, match="requires live onboarding captures"):
            getattr(navigator, name)(*args)


def test_registry_refuses_unknown_keys():
    from sigaa.institutions import get

    with pytest.raises(ValueError, match="unknown institution"):
        get("not-registered")


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


def _identity():
    return {"username": secrets.token_hex(), "matricula": secrets.token_hex(),
            "name": "JOSÉ ANTÔNIO DA COSTA", "email": "jose.costa@academico.ufpb.br"}


@pytest.mark.parametrize("text, found", [
    ("<td>Antonio</td>", True),          # one name token, accents folded
    ("<p>Prof. COSTA</p>", True),        # a surname alone
    ("contato: jose.costa", True),       # e-mail local part without the domain
    ("<td>COSTAS</td>", False),          # token inside a longer word
    ("<td>da</td>", False),              # tokens shorter than 4 letters are ignored
    ("<td>José Silva</td>", True),       # 4-letter first name
])
def test_privacy_gate_matches_name_tokens_and_email_local_part(tmp_path, text, found):
    root = _repo(tmp_path)
    (root / "fixture.html").write_text(text)
    identity = _identity()

    findings = privacy_findings(root, identity)

    assert any(f["category"] == "identity" for f in findings) is found
    for finding in findings:
        assert set(finding) == {"source", "file_index", "category"}


def test_offline_probe_does_not_resolve_local_credentials_or_active_institution(
    tmp_path, monkeypatch, capsys
):
    from sigaa.cli import main

    directory = _capture(tmp_path)
    monkeypatch.setenv("SIGAA_INSTITUTION", "invalid-local-configuration")
    assert main(["onboard", "probe", "--from", str(directory), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["institution"] == "ufpb"


def test_live_probe_captures_with_the_requested_institution(tmp_path, monkeypatch, capsys):
    from sigaa import cli
    from sigaa.onboard import cli as onboard_cli

    captured = []

    def fake_capture(settings):
        captured.append(settings.institution)
        return _capture(tmp_path), {}

    monkeypatch.setattr(onboard_cli, "capture", fake_capture)
    monkeypatch.delenv("SIGAA_INSTITUTION", raising=False)
    assert cli.main(["onboard", "probe", "--institution", "ufpb"]) == 0
    assert captured == ["ufpb"]
