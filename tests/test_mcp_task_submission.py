from types import SimpleNamespace

import pytest

pytest.importorskip("mcp")

from sigaa import mcp_server


DEADLINE_ID = "dl-1"


def test_task_submission_requires_explicit_confirmation_before_opening_a_network_client(monkeypatch, tmp_path):
    upload = tmp_path / "solucao.zip"
    upload.write_bytes(b"solution")
    deadline = SimpleNamespace(id=DEADLINE_ID, kind="tarefa", title="Lab SOLID")
    monkeypatch.setattr(mcp_server, "_repo", lambda: SimpleNamespace(get_deadlines=lambda: [deadline]))

    class MustNotConnect:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("confirmation gate must run before network access")

    monkeypatch.setattr(mcp_server, "SigaaClient", MustNotConnect)

    result = mcp_server.sigaa_submit_tarefa(DEADLINE_ID, str(upload))

    assert result["status"] == "confirmation_required"
    assert result["title"] == "Lab SOLID"
    assert result["file_name"] == "solucao.zip"
    assert result["bytes"] == len(b"solution")


def test_task_submission_sends_only_when_explicitly_confirmed(monkeypatch, tmp_path):
    upload = tmp_path / "solucao.zip"
    upload.write_bytes(b"solution")
    deadline = SimpleNamespace(id=DEADLINE_ID, kind="tarefa", title="Lab SOLID")
    monkeypatch.setattr(mcp_server, "_repo", lambda: SimpleNamespace(get_deadlines=lambda: [deadline]))
    settings = SimpleNamespace(
        institution="ufpb", username="configured-user", resolve_password=lambda: "test-password"
    )
    monkeypatch.setattr(mcp_server, "Settings", lambda: settings)

    class FakeClient:
        def __init__(self, username, password, **kwargs):
            assert (username, password) == ("configured-user", "test-password")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def submit_tarefa(self, deadline_id, file_path):
            assert deadline_id == DEADLINE_ID
            assert file_path == upload.resolve()
            return {"status": "submitted"}

    monkeypatch.setattr(mcp_server, "SigaaClient", FakeClient)

    assert mcp_server.sigaa_submit_tarefa(DEADLINE_ID, str(upload), confirm=True) == {
        "status": "submitted",
        "deadline_id": DEADLINE_ID,
        "title": "Lab SOLID",
        "file_name": "solucao.zip",
        "bytes": len(b"solution"),
    }
