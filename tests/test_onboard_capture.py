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
from sigaa.institutions import get
from sigaa.models import Turma
from sigaa.onboard import capture as module
from sigaa.onboard.capture import ReadOnlySession, ReadOnlyViolation, private_write, private_directory
from sigaa.onboard.features import Feature
from sigaa.institutions import Capability


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
    with Session("test", secrets.token_urlsafe(), client=raw) as session:
        ReadOnlySession(session)
        with pytest.raises(ReadOnlyViolation):
            raw.post(get().profile.ava_url, data={"form:botaoSubmissao": "x"})
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
        client._session = Session(username, password,
                                  client=httpx.Client(transport=httpx.MockTransport(handler)))
        client._session._authenticated = True
        client._session.login = lambda: client._session._client.get(get().profile.portal_entry_url).text
        client.list_turmas = lambda: [Turma(id_turma="1", name="First"), Turma(id_turma="2", name="Second")]
        return client
    feature = Feature("class", Capability.PORTAL,
                      lambda client, turma: client._session.post(client.profile.ava_url,
                                                                 {"idTurma": turma.id_turma}),
                      lambda *_: [], True)
    monkeypatch.setattr(module, "SigaaClient", factory)
    monkeypatch.setattr(module, "FEATURES", (feature, replace(feature, key="enroll", opt_in=True)))
    monkeypatch.setenv("SIGAA_PASS", secrets.token_urlsafe())
    settings = Settings(username="test-student", db_path=tmp_path / "db")
    directory, manifest = module.capture(settings, output=tmp_path / "captures")
    entries = manifest["entries"]
    assert [e["turma_id"] for e in entries[:2]] == ["1", "2"]
    assert all(e["status"] == "not_captured" for e in entries[2:])
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
