import hashlib
import json
import secrets
import stat
from dataclasses import replace

import httpx
import pytest

from sigaa.client import SigaaClient
from sigaa.config import Settings
from sigaa.http import Session
from sigaa.institutions import Capability, get
from sigaa.models import Turma
from sigaa.onboard import capture as module
from sigaa.onboard.capture import (
    ReadOnlySession,
    ReadOnlyViolation,
    private_directory,
    private_write,
)
from sigaa.onboard.features import Feature


UFPB = get("ufpb")


def _session(raw):
    return Session(
        "test-student",
        secrets.token_urlsafe(),
        client=raw,
        profile=UFPB.profile,
        navigator=UFPB.navigator,
    )


@pytest.mark.parametrize("data", [
    {"form:botaoSubmissao": "x"}, {"form": "CONFIRMAR"},
    {"form:btaoSelecionarTurmas": ["x"]}, {"foo": ["ok", "submeter"]},
])
def test_read_only_refuses_submit_controls(data):
    with pytest.raises(ReadOnlyViolation):
        ReadOnlySession.validate_post(data)


def test_transport_guard_cannot_be_bypassed_by_a_navigator():
    requests = []
    raw = httpx.Client(transport=httpx.MockTransport(lambda req: requests.append(req)))
    with _session(raw) as session:
        ReadOnlySession(session)
        with pytest.raises(ReadOnlyViolation):
            raw.post(UFPB.profile.ava_url, data={"form:botaoSubmissao": "x"})
    assert requests == []


def test_private_writes_refuse_symlinks_and_overwrites(tmp_path):
    directory = tmp_path / "private"
    private_directory(directory)
    target = directory / "body"
    private_write(target, b"original")
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        private_write(target, b"replacement")
    link = tmp_path / "link"
    link.symlink_to(directory)
    with pytest.raises(ValueError, match="symlinks"):
        private_directory(link / "child")
    assert target.read_bytes() == b"original"


def test_capture_preserves_http_bytes_metadata_and_two_class_contexts(monkeypatch, tmp_path):
    from pathlib import Path
    portal = (Path(__file__).parent / "fixtures/portal.html").read_bytes()
    payload = b'<html><footer>SIGAA v4.20.6-test.4</footer>\xe9</html>'
    requests = []
    def handler(request):
        requests.append(request)
        body = portal if request.method == "GET" else payload
        return httpx.Response(200, content=body,
                              headers={"Content-Type": "text/html; charset=iso-8859-1"})
    def factory(username, password, **kwargs):
        client = SigaaClient(username, password, **kwargs)
        client._session.close()
        client._session = _session(httpx.Client(transport=httpx.MockTransport(handler)))
        url = UFPB.profile.portal_entry_url
        client._session._authenticated = True
        client._session.login = lambda: client._session._client.get(url).text
        turmas = [Turma(id_turma="1", name="First"), Turma(id_turma="2", name="Second")]
        client.list_turmas = lambda: turmas
        return client
    feature = Feature("class", Capability.PORTAL,
                      lambda client, turma: client._session.post(client.profile.ava_url,
                                                                 {"idTurma": turma.id_turma}),
                      lambda *_: [], True)
    monkeypatch.setattr(module, "SigaaClient", factory)
    cached = replace(feature, key="cached", needs_turma=False,
                     fetcher=lambda client, turma: "<html>served from memory</html>")
    features = (feature, replace(feature, key="enroll", opt_in=True), cached)
    monkeypatch.setattr(module, "FEATURES", features)
    monkeypatch.setenv("SIGAA_PASS", secrets.token_urlsafe())
    settings = Settings(username="test-student", db_path=tmp_path / "db")
    directory, manifest = module.capture(settings, output=tmp_path / "captures")
    entries = manifest["entries"]
    assert [e["turma_id"] for e in entries[:2]] == ["1", "2"]
    assert all(e["status"] == "not_captured" for e in entries[2:])
    assert entries[-1]["feature"] == "cached" and "file" not in entries[-1]
    assert len(requests) == 3
    for entry in entries[:2]:
        assert (directory / entry["file"]).read_bytes() == payload
        assert entry["sha256"] == hashlib.sha256(payload).hexdigest()
        assert entry["method"] == "POST"
        assert entry["http_status"] == 200
        assert entry["sigaa_version"] == "4.20.6-test.4"
    for path in directory.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads((directory / "identity.json").read_text())["username"] == "test-student"


def test_recorder_keeps_only_the_last_non_redirect_response():
    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "https://sigaa.ufpb.br/final"})
        return httpx.Response(200, text=request.url.path)

    raw = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    with _session(raw) as session:
        recorder = ReadOnlySession(session)
        raw.get("https://sigaa.ufpb.br/start")
        assert recorder.last_response.text == "/final"
        raw.get("https://sigaa.ufpb.br/other")
        assert recorder.last_response.text == "/other"
        assert not hasattr(recorder, "responses")


def test_login_probe_defaults_to_the_active_institution(monkeypatch, capsys):
    from sigaa import cli
    from sigaa.institutions import registry
    from sigaa.institutions.base import Institution

    other = replace(
        UFPB.profile,
        key="example",
        host="https://sigaa.example.edu",
        logon_url="https://sigaa.example.edu/login",
    )
    monkeypatch.setitem(registry._PROVIDERS, other.key, Institution(other, UFPB.navigator))
    monkeypatch.setenv("SIGAA_INSTITUTION", other.key)
    requested = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url):
            requested.append(url)
            return httpx.Response(200, text="<form></form>", request=httpx.Request("GET", url))

    monkeypatch.setattr("sigaa.onboard.cli.httpx.Client", Client)
    assert cli.main(["onboard", "login-probe"]) == 1
    assert requested == ["https://sigaa.example.edu/login"]


@pytest.mark.parametrize("failure", [ValueError, RuntimeError])
def test_failed_class_lookup_survives_capture_and_probe(monkeypatch, tmp_path, failure):
    from pathlib import Path
    from sigaa.onboard.probe import probe

    body = (Path(__file__).parent / "fixtures/portal.html").read_bytes()
    def factory(username, password, **kwargs):
        client = SigaaClient(username, password, **kwargs)
        client._session.close()
        client._session = _session(httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=body))))
        client._session.login = lambda: client._session._client.get(
            UFPB.profile.portal_entry_url).text
        def fail():
            raise failure("private exception details")
        client.list_turmas = fail
        return client
    monkeypatch.setattr(module, "SigaaClient", factory)
    monkeypatch.setenv("SIGAA_PASS", secrets.token_urlsafe())
    directory, manifest = module.capture(
        Settings(username="test-student", institution="ufpb"), output=tmp_path / "captures")
    class_keys = {f.key for f in module.FEATURES if f.needs_turma}
    entries = [e for e in manifest["entries"] if e["feature"] in class_keys]
    assert entries and all(e["status"] == "nav_failed" for e in entries)
    assert all(e["error_type"] == failure.__name__ for e in entries)
    assert "private exception details" not in json.dumps(manifest)
    rows = [row for row in probe(directory)["features"] if row["feature"] in class_keys]
    assert rows and all(row["status"] == "nav_failed" for row in rows)


def test_capture_destination_must_be_ignored_and_untracked(tmp_path):
    import subprocess
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True,
                              capture_output=True)
    git("init")
    (tmp_path / ".gitignore").write_text("/captures/\n")
    assert module.validate_output(tmp_path / "captures") == tmp_path / "captures"
    with pytest.raises(ValueError, match="Git-ignored"):
        module.validate_output(tmp_path / "tests" / "fixtures")
    assert not (tmp_path / "tests").exists()
    (tmp_path / "captures").mkdir()
    (tmp_path / "captures" / "tracked.body").write_text("synthetic")
    git("add", "-f", "captures/tracked.body")
    with pytest.raises(ValueError, match="tracked"):
        module.validate_output(tmp_path / "captures")
    with pytest.raises(ValueError, match="metadata"):
        module.validate_output(tmp_path / ".git" / "captures")


def test_nested_repository_cannot_bypass_outer_ignore_rules(tmp_path):
    import subprocess
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    nested = tmp_path / "nested"
    subprocess.run(["git", "init", str(nested)], check=True, capture_output=True)
    (nested / ".git/info/exclude").write_text("/captures/\n")
    with pytest.raises(ValueError, match="Git-ignored"):
        module.validate_output(nested / "captures")
