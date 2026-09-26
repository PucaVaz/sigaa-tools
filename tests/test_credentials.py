"""Credential resolution: keyring first, environment as an optional override."""

import json

import pytest

from conftest import TEST_PASSWORD, TEST_USERNAME
from sigaa import cli, config
from sigaa.institutions import ufpb
from sigaa.config import Settings
from sigaa.errors import STAGE_AUTH, LoginRejectedError, MissingCredentialsError


def _save_login(keyring_store: dict, username: str, password: str) -> None:
    """What `sigaa login` leaves in the keyring."""
    keyring_store[(ufpb.KEYRING_SERVICE, config.KEYRING_ACTIVE_USERNAME)] = username
    keyring_store[(ufpb.KEYRING_SERVICE, username)] = password


def test_keyring_only_login_resolves_both_username_and_password(clean_credentials, tmp_path):
    _save_login(clean_credentials, TEST_USERNAME, TEST_PASSWORD)

    settings = Settings(db_path=tmp_path / "t.db")

    assert settings.require_credentials() == (TEST_USERNAME, TEST_PASSWORD)
    assert settings.credentials_problem() is None


def test_keyring_only_sync_logs_in_without_environment(clean_credentials, fake_sigaa, tmp_path):
    _save_login(clean_credentials, TEST_USERNAME, TEST_PASSWORD)
    fake_sigaa.add_class("900001", "TEST0001", "news_empty.html")

    exit_code = cli.main(["--db", str(tmp_path / "t.db"), "sync", "--json"])

    assert exit_code == 0
    assert fake_sigaa.logins == [(TEST_USERNAME, TEST_PASSWORD)]


def test_environment_overrides_username_and_supplies_password(
    clean_credentials, monkeypatch, tmp_path
):
    _save_login(clean_credentials, "someone.else", "other-password")
    monkeypatch.setenv("SIGAA_USER", TEST_USERNAME)
    monkeypatch.setenv("SIGAA_PASS", TEST_PASSWORD)

    settings = Settings(db_path=tmp_path / "t.db")

    assert settings.require_credentials() == (TEST_USERNAME, TEST_PASSWORD)


def test_keyring_password_wins_over_environment_password(
    clean_credentials, monkeypatch, tmp_path
):
    _save_login(clean_credentials, TEST_USERNAME, TEST_PASSWORD)
    monkeypatch.setenv("SIGAA_PASS", "stale-env-password")

    assert Settings(db_path=tmp_path / "t.db").require_credentials()[1] == TEST_PASSWORD


def test_environment_username_with_keyring_password_needs_no_sigaa_pass(
    clean_credentials, monkeypatch, tmp_path
):
    clean_credentials[(ufpb.KEYRING_SERVICE, TEST_USERNAME)] = TEST_PASSWORD
    monkeypatch.setenv("SIGAA_USER", TEST_USERNAME)

    assert Settings(db_path=tmp_path / "t.db").require_credentials() == (
        TEST_USERNAME, TEST_PASSWORD,
    )


def test_missing_account_fails_clearly(clean_credentials, tmp_path):
    settings = Settings(db_path=tmp_path / "t.db")

    with pytest.raises(MissingCredentialsError) as excinfo:
        settings.require_credentials()

    assert excinfo.value.stage == STAGE_AUTH
    assert "no SIGAA account configured" in str(excinfo.value)
    assert "sigaa login" in str(excinfo.value)


def test_missing_password_names_the_account_and_the_fix(
    clean_credentials, monkeypatch, tmp_path
):
    monkeypatch.setenv("SIGAA_USER", TEST_USERNAME)

    problem = Settings(db_path=tmp_path / "t.db").credentials_problem()

    assert problem.startswith("missing credentials: no password for account")
    assert TEST_USERNAME in problem
    assert "sigaa login" in problem


def test_missing_credentials_sync_fails_as_auth_and_is_recorded(
    clean_credentials, fake_sigaa, tmp_path, capsys
):
    db = tmp_path / "t.db"

    assert cli.main(["--db", str(db), "sync", "--json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error_stage"] == STAGE_AUTH
    assert fake_sigaa.logins == []
    from sigaa.store.db import connect
    from sigaa.store.repository import Repository

    last = Repository(connect(db)).last_sync()
    assert last["ok"] is False
    assert "missing credentials" in last["detail"]


@pytest.mark.parametrize(
    "argv",
    [
        ["sync"],
        ["sync", "--json"],
        ["watch", "--once"],
        ["watch", "--once", "--json"],
        ["watch", "--once", "--jsonl"],
    ],
)
def test_no_secret_is_printed_when_login_is_rejected(
    argv, clean_credentials, fake_sigaa, tmp_path, capsys
):
    _save_login(clean_credentials, TEST_USERNAME, TEST_PASSWORD)
    fake_sigaa.failure = LoginRejectedError(
        "login failed: SIGAA rejected the credentials or showed a CAPTCHA"
    )

    cli.main(["--db", str(tmp_path / "t.db"), *argv])

    captured = capsys.readouterr()
    assert TEST_PASSWORD not in captured.out
    assert TEST_PASSWORD not in captured.err
    assert "login failed" in captured.out + captured.err


def test_no_secret_is_printed_when_the_password_is_missing(
    clean_credentials, monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("SIGAA_USER", TEST_USERNAME)
    clean_credentials[(ufpb.KEYRING_SERVICE, "unrelated")] = TEST_PASSWORD

    cli.main(["--db", str(tmp_path / "t.db"), "watch", "--once", "--json"])

    captured = capsys.readouterr()
    assert TEST_PASSWORD not in captured.out + captured.err
