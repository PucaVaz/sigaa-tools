"""`sigaa watch`: event stream, idempotence, and failures that never look quiet."""

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from conftest import FIXTURES, TEST_PASSWORD, TEST_USERNAME
from sigaa import cli, config
from sigaa.institutions import ufpb
from sigaa.config import Settings
from sigaa.errors import (
    STAGE_AUTH,
    STAGE_NETWORK,
    STAGE_PARSE,
    LoginRejectedError,
    UnsafeUrlError,
)
from sigaa.services import watch
from sigaa.store.db import connect
from sigaa.store.repository import Repository

REMOTE_ID = "900001"
REMOTE_CODE = "TEST0001"
OTHER_ID = "900002"
OTHER_CODE = "TEST0002"
REMOTE_NEWS_ID = "90000001"
FIXED_NOW = datetime(2026, 9, 14, 1, 40, tzinfo=timezone.utc)


@pytest.fixture
def logged_in(clean_credentials):
    clean_credentials[(ufpb.KEYRING_SERVICE, config.KEYRING_ACTIVE_USERNAME)] = TEST_USERNAME
    clean_credentials[(ufpb.KEYRING_SERVICE, TEST_USERNAME)] = TEST_PASSWORD


@pytest.fixture
def remote_class(fake_sigaa, logged_in):
    """One class whose Principal page carries the remote-class notice."""
    fake_sigaa.add_class(REMOTE_ID, REMOTE_CODE, "news_remote_class.html")
    fake_sigaa.bodies[REMOTE_NEWS_ID] = (FIXTURES / "news_remote_class_body.html").read_text(
        encoding="utf-8"
    )
    return fake_sigaa


def _settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "t.db")


def _run(tmp_path, **kwargs) -> watch.WatchRun:
    return watch.run_once(_settings(tmp_path), now=lambda: FIXED_NOW, **kwargs)


def _watch_cli(tmp_path, capsys, *flags) -> tuple[int, str, str]:
    exit_code = cli.main(["--db", str(tmp_path / "t.db"), "watch", "--once", *flags])
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def _jsonl(stdout: str) -> list[dict]:
    return [json.loads(line) for line in stdout.splitlines()]


# --- new announcements -----------------------------------------------------

def test_first_run_emits_the_remote_class_announcement(remote_class, tmp_path):
    run = _run(tmp_path, fetch_bodies=True)

    assert run.status == watch.STATUS_CHANGES
    assert run.events == [{
        "type": "news",
        "status": "new",
        "class_id": REMOTE_ID,
        "class_code": REMOTE_CODE,
        "item_id": REMOTE_NEWS_ID,
        "title": "Aula remota",
        "published_at": "13/09/2026 21:58",
        "body": run.events[0]["body"],
        "url": "https://meet.google.com/aaa-bbbb-ccc",
        "detected_at": "2026-09-14T01:40:00+00:00",
    }]
    assert "será remota" in run.events[0]["body"]
    assert run.classes == [{
        "class_id": REMOTE_ID, "class_code": REMOTE_CODE,
        "news_found": 1, "news_new": 1, "materials_new": 0, "deadlines_new": 0,
        "grades_changed": 0, "attendance_changed": 0, "errors": [],
    }]


def test_repeated_unchanged_run_emits_no_changes(remote_class, tmp_path):
    _run(tmp_path)

    run = _run(tmp_path)

    assert run.status == watch.STATUS_NO_CHANGES
    assert run.events == []
    assert run.classes[0]["news_found"] == 1
    assert run.classes[0]["news_new"] == 0


def test_unchanged_runs_serialize_to_identical_bytes(remote_class, tmp_path, capsys):
    _watch_cli(tmp_path, capsys, "--json")

    _, second, _ = _watch_cli(tmp_path, capsys, "--json")
    _, third, _ = _watch_cli(tmp_path, capsys, "--json")

    assert second == third
    assert json.loads(second)["status"] == "no_changes"


def test_only_the_newly_added_announcement_is_emitted(remote_class, tmp_path):
    _run(tmp_path)
    page = remote_class.pages[REMOTE_ID]
    remote_class.pages[REMOTE_ID] = page.replace(
        "<br>\n\n    </div></div>",
        """<br>
				15/09/2026 10:00<br>
				<i>Material da aula remota </i> <br>
<form id="row2" name="row2" method="post" action="/sigaa/ava/index.jsf">
				<input type="hidden" name="id" value="90000002"/>
</form>
    </div></div>""",
    )

    run = _run(tmp_path)

    assert run.status == watch.STATUS_CHANGES
    assert [(e["item_id"], e["status"], e["title"]) for e in run.events] == [
        ("90000002", "new", "Material da aula remota"),
    ]


def test_a_retitled_announcement_is_reported_as_changed(remote_class, tmp_path):
    _run(tmp_path)
    with connect(tmp_path / "t.db") as conn:
        conn.execute("UPDATE news SET title = 'Aula remota (link novo)' WHERE id = ?",
                     (REMOTE_NEWS_ID,))

    run = _run(tmp_path)

    assert [(e["item_id"], e["status"]) for e in run.events] == [(REMOTE_NEWS_ID, "changed")]


def test_items_synced_by_another_client_are_still_emitted_once(remote_class, tmp_path):
    """The MCP server or `sigaa sync` may store a news item before the watcher runs."""
    cli.main(["--db", str(tmp_path / "t.db"), "sync"])

    first = _run(tmp_path)
    second = _run(tmp_path)

    assert [e["item_id"] for e in first.events] == [REMOTE_NEWS_ID]
    assert second.status == watch.STATUS_NO_CHANGES


def test_baseline_records_existing_items_without_emitting_them(remote_class, tmp_path):
    baseline = _run(tmp_path, baseline=True)
    after = _run(tmp_path)

    assert baseline.status == watch.STATUS_BASELINE
    assert baseline.events == []
    assert after.status == watch.STATUS_NO_CHANGES


def test_watcher_does_not_consume_the_whatsnew_feed(remote_class, tmp_path, capsys):
    _run(tmp_path)

    cli.main(["--db", str(tmp_path / "t.db"), "whatsnew", "--json"])

    feed = json.loads(capsys.readouterr().out)
    assert [n["id"] for n in feed["news"]] == [REMOTE_NEWS_ID]
    assert feed["last_sync"]["ok"] is True


# --- failures ---------------------------------------------------------------

def test_auth_failure_is_an_error_event_not_no_changes(remote_class, tmp_path):
    remote_class.failure = LoginRejectedError("login failed: SIGAA rejected the credentials")

    run = _run(tmp_path)

    assert run.status == watch.STATUS_FAILED
    assert run.events == [{
        "type": "error", "status": "failed", "stage": STAGE_AUTH,
        "message": "login failed: SIGAA rejected the credentials",
        "class_id": None, "class_code": None,
    }]


def test_blocked_redirect_is_a_network_error_naming_the_hop(remote_class, tmp_path):
    remote_class.failure = UnsafeUrlError("http", "sigaa.ufpb.br", None, "is not HTTPS")

    run = _run(tmp_path)

    assert run.status == watch.STATUS_FAILED
    assert run.events[0]["stage"] == STAGE_NETWORK
    assert "http://sigaa.ufpb.br" in run.events[0]["message"]


def test_missing_credentials_are_an_auth_error(fake_sigaa, clean_credentials, tmp_path):
    run = _run(tmp_path)

    assert run.status == watch.STATUS_FAILED
    assert run.events[0]["stage"] == STAGE_AUTH
    assert run.events[0]["message"].startswith("missing credentials")


def test_network_failure_is_a_network_error(remote_class, tmp_path):
    remote_class.failure = httpx.ConnectError("[Errno 8] nodename nor servname provided, or not known")

    run = _run(tmp_path)

    assert run.status == watch.STATUS_FAILED
    assert run.events[0]["stage"] == STAGE_NETWORK


def test_parser_failure_is_reported_per_class_while_other_classes_still_sync(remote_class, tmp_path):
    remote_class.add_class(OTHER_ID, OTHER_CODE, "news_changed_markup.html")

    run = _run(tmp_path)

    assert run.status == watch.STATUS_FAILED
    news, error = run.events
    assert (news["type"], news["item_id"]) == ("news", REMOTE_NEWS_ID)
    assert error["type"] == "error"
    assert error["stage"] == STAGE_PARSE
    assert (error["class_id"], error["class_code"]) == (OTHER_ID, OTHER_CODE)
    summary = {c["class_id"]: c for c in run.classes}
    assert summary[OTHER_ID]["errors"][0]["stage"] == STAGE_PARSE
    assert summary[REMOTE_ID]["errors"] == []


def test_a_persistent_parser_failure_never_turns_into_no_changes(fake_sigaa, logged_in, tmp_path):
    fake_sigaa.add_class(REMOTE_ID, REMOTE_CODE, "news_panel_missing.html")

    runs = [_run(tmp_path) for _ in range(3)]

    assert [r.status for r in runs] == [watch.STATUS_FAILED] * 3


def test_declared_empty_class_is_no_changes(fake_sigaa, logged_in, tmp_path):
    fake_sigaa.add_class(REMOTE_ID, REMOTE_CODE, "news_empty.html")

    run = _run(tmp_path)

    assert run.status == watch.STATUS_NO_CHANGES
    assert run.classes[0]["news_found"] == 0


def test_failed_sync_is_recorded_in_the_sync_log(remote_class, tmp_path):
    remote_class.failure = httpx.ReadTimeout("The read operation timed out")

    _run(tmp_path)

    last = Repository(connect(tmp_path / "t.db")).last_sync()
    assert last["ok"] is False
    assert last["detail"] == "The read operation timed out"


# --- exit codes and stdout contract ----------------------------------------

@pytest.mark.parametrize("flags", [(), ("--json",), ("--jsonl",)])
def test_failure_exits_zero_without_fail_on_error(remote_class, tmp_path, capsys, flags):
    remote_class.failure = LoginRejectedError("login failed")

    exit_code, _, _ = _watch_cli(tmp_path, capsys, *flags)

    assert exit_code == 0


@pytest.mark.parametrize("flags", [(), ("--json",), ("--jsonl",)])
def test_failure_exits_non_zero_with_fail_on_error(remote_class, tmp_path, capsys, flags):
    remote_class.failure = LoginRejectedError("login failed")

    exit_code, _, _ = _watch_cli(tmp_path, capsys, "--fail-on-error", *flags)

    assert exit_code == cli.EXIT_WATCH_FAILED


def test_success_exits_zero_with_fail_on_error(remote_class, tmp_path, capsys):
    exit_code, _, _ = _watch_cli(tmp_path, capsys, "--fail-on-error", "--json")

    assert exit_code == 0


def test_loop_stops_at_first_failure_with_fail_on_error(remote_class, tmp_path, capsys, monkeypatch):
    remote_class.failure = LoginRejectedError("login failed")
    monkeypatch.setattr(cli.time, "sleep", lambda _: pytest.fail("must not sleep after failure"))

    exit_code = cli.main(["--db", str(tmp_path / "t.db"), "watch", "--jsonl", "--fail-on-error"])

    assert exit_code == cli.EXIT_WATCH_FAILED
    events = _jsonl(capsys.readouterr().out)
    assert [e["type"] for e in events] == ["error", "sync"]


def test_jsonl_stdout_is_only_json_and_ends_with_a_sync_event(remote_class, tmp_path, capsys):
    _, first, _ = _watch_cli(tmp_path, capsys, "--jsonl", "--bodies")
    _, second, _ = _watch_cli(tmp_path, capsys, "--jsonl")

    first_events = _jsonl(first)
    assert [(e["type"], e["status"]) for e in first_events] == [
        ("news", "new"), ("sync", "changes"),
    ]
    assert first_events[-1]["event_count"] == 1
    assert _jsonl(second) == [{
        "type": "sync", "status": "no_changes", "event_count": 0,
        "classes": [{
            "class_id": REMOTE_ID, "class_code": REMOTE_CODE,
            "news_found": 1, "news_new": 0, "materials_new": 0, "deadlines_new": 0,
            "grades_changed": 0, "attendance_changed": 0, "errors": [],
        }],
    }]


def test_json_document_carries_events_and_summary(remote_class, tmp_path, capsys):
    exit_code, out, err = _watch_cli(tmp_path, capsys, "--json", "--bodies")

    document = json.loads(out)
    assert exit_code == 0
    assert err == ""
    assert document["type"] == "sync"
    assert document["status"] == "changes"
    assert [e["title"] for e in document["events"]] == ["Aula remota"]


def test_loop_banner_goes_to_stderr_in_machine_modes(remote_class, tmp_path, capsys, monkeypatch):
    def stop(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", stop)

    cli.main(["--db", str(tmp_path / "t.db"), "watch", "--jsonl", "--interval", "30m"])

    captured = capsys.readouterr()
    assert "every 1800s" in captured.err
    assert [e["type"] for e in _jsonl(captured.out)] == ["news", "sync"]


def test_json_without_once_is_rejected(remote_class, tmp_path, capsys):
    exit_code = cli.main(["--db", str(tmp_path / "t.db"), "watch", "--json"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "--jsonl" in captured.err


def test_human_output_still_lists_new_items(remote_class, tmp_path, capsys):
    _, out, _ = _watch_cli(tmp_path, capsys)

    assert "1 change(s)" in out
    assert f"news new [13/09/2026 21:58] {REMOTE_CODE} Aula remota" in out


@pytest.mark.parametrize(
    ("raw", "seconds"), [("900", 900), ("45s", 45), ("30m", 1800), ("1h", 3600)]
)
def test_interval_accepts_seconds_and_units(raw, seconds):
    assert cli._parse_interval(raw) == seconds


@pytest.mark.parametrize("raw", ["0", "-5", "5d", "abc", ""])
def test_interval_rejects_nonsense(raw):
    with pytest.raises(Exception):
        cli._parse_interval(raw)


def test_sync_json_keeps_old_keys_and_adds_class_summaries(remote_class, tmp_path, capsys):
    cli.main(["--db", str(tmp_path / "t.db"), "sync", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert {"ok", "error", "classes", "grade_rows", "new_news", "new_materials",
            "grade_updates", "new_deadlines", "attendance_updates"} <= payload.keys()
    assert payload["error_stage"] is None
    assert payload["class_summaries"][0]["news_new"] == 1
