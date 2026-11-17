"""A sync splits its classes across independent SIGAA sessions.

SIGAA keeps the current turma in per-session state, so requests inside one
session cannot overlap. Separate logins have separate state: measured live at
UFPB with one login per class (seven), every class was read correctly in about
a quarter of the time and the server answered no slower. An
imported browser session (``auth_mode="session"``) is one server session however
many clients replay it, so it always syncs sequentially.
"""

import secrets
import threading

import pytest

from sigaa.config import MAX_SYNC_SESSIONS, SYNC_SESSIONS_ENV, Settings
from sigaa.errors import STAGE_AUTH, STAGE_NETWORK, STAGE_PARSE, LoginRejectedError
from sigaa.models import NewsItem, Student, Turma
from sigaa.services import sync as sync_module
from sigaa.store.db import connect
from sigaa.store.repository import Repository

CODES = ["GDSCO0055", "1107202", "DINF00051", "GDLPL0063", "DSCO00021", "DSCO00022", "DINF00054"]
TURMAS = [
    Turma(id_turma=str(379201 + index), name=f"TURMA {code}", code=code)
    for index, code in enumerate(CODES)
]
OVERLAP_WAIT_SECONDS = 5


class _Sigaa:
    """A fake SIGAA: every client is a separate login with its own turma log."""

    def __init__(self, turmas=TURMAS):
        self.turmas = turmas
        self.logins: list["_Client"] = []
        self.failing_login: int | None = None
        self.unreadable_code: str | None = None
        # Set to prove two sessions are inside enter_turma at the same moment.
        self.overlap: threading.Barrier | None = None

    def client_class(self):
        sigaa = self

        class Client(_Client):
            def __init__(self, *args, **kwargs):
                super().__init__(sigaa)

        return Client

    def entered_by_session(self) -> list[list[str]]:
        return [client.entered for client in self.logins]


class _Client:
    def __init__(self, sigaa: _Sigaa):
        self.sigaa = sigaa
        self.entered: list[str] = []
        self.thread = threading.get_ident()
        sigaa.logins.append(self)
        self.number = len(sigaa.logins)

    def __enter__(self):
        if self.sigaa.failing_login == self.number:
            raise LoginRejectedError("login failed: SIGAA rejected the credentials")
        return self

    def __exit__(self, *exc):
        return None

    def get_student(self):
        return Student(matricula="000", name="ALUNO TESTE")

    def list_turmas(self):
        return list(self.sigaa.turmas)

    def list_deadlines(self):
        return []

    def get_grades(self):
        return []

    def enter_turma(self, turma):
        self.thread = threading.get_ident()
        if self.sigaa.overlap is not None and not self.entered:
            self.sigaa.overlap.wait(timeout=OVERLAP_WAIT_SECONDS)
        self.entered.append(turma.code)
        return f"<html>{turma.code}</html>"

    def list_news(self, turma, turma_html=None):
        return [
            NewsItem(id=f"news-{turma.code}", id_turma=turma.id_turma, date="17/11/2026",
                     title=f"Aviso {turma.code}")
        ]

    def list_materials(self, turma, turma_html=None):
        return []

    def get_turma_grades(self, turma, turma_html=None):
        return None

    def get_course_plan(self, turma, turma_html=None):
        return None

    def list_activity_topics(self, turma, turma_html=None):
        return []

    def list_tarefas(self, turma, turma_html=None):
        return []

    def get_attendance(self, turma, turma_html=None):
        return None

    def list_professors(self, turma, turma_html=None):
        if turma.code == self.sigaa.unreadable_code:
            raise TimeoutError("The read operation timed out")
        return []


@pytest.fixture
def settings(monkeypatch, tmp_path):
    monkeypatch.setenv("SIGAA_USER", "test-student")
    monkeypatch.setenv("SIGAA_PASS", secrets.token_urlsafe(16))
    monkeypatch.setattr("keyring.get_password", lambda *a: None)
    monkeypatch.delenv(SYNC_SESSIONS_ENV, raising=False)
    return Settings(institution="ufpb", db_path=tmp_path / "t.db")


def _run(monkeypatch, settings, sigaa: _Sigaa):
    monkeypatch.setattr(sync_module, "SigaaClient", sigaa.client_class())
    return sync_module.sync(settings)


def test_every_class_gets_a_login_of_its_own(monkeypatch, settings):
    sigaa = _Sigaa()

    result = _run(monkeypatch, settings, sigaa)

    assert result.ok, result.error
    shares = sigaa.entered_by_session()
    assert sorted(shares) == sorted([code] for code in CODES)


def test_the_sessions_run_at_the_same_time(monkeypatch, settings):
    sigaa = _Sigaa()
    sigaa.overlap = threading.Barrier(len(CODES))

    result = _run(monkeypatch, settings, sigaa)

    # A sequential run never gathers every party at the barrier and breaks it.
    assert result.ok, result.error
    assert len({client.thread for client in sigaa.logins}) == len(CODES)


def test_more_classes_than_the_session_cap_share_logins(monkeypatch, settings):
    extra = [
        Turma(id_turma=str(900000 + index), name=f"EXTRA {index}", code=f"EXTRA{index}")
        for index in range(2)
    ]
    sigaa = _Sigaa(turmas=TURMAS + extra)

    result = _run(monkeypatch, settings, sigaa)

    assert result.ok, result.error
    shares = sigaa.entered_by_session()
    assert len(shares) == MAX_SYNC_SESSIONS
    assert sum(len(share) for share in shares) == len(TURMAS) + len(extra)


def test_the_session_count_can_be_lowered(monkeypatch, settings):
    monkeypatch.setenv(SYNC_SESSIONS_ENV, "3")
    sigaa = _Sigaa()

    result = _run(monkeypatch, Settings(institution="ufpb", db_path=settings.db_path), sigaa)

    assert result.ok, result.error
    assert sorted(len(share) for share in sigaa.entered_by_session()) == [2, 2, 3]


def test_results_keep_the_portal_order_whatever_finishes_first(monkeypatch, settings):
    result = _run(monkeypatch, settings, _Sigaa())

    assert [summary.code for summary in result.classes] == CODES
    assert [item.id for item in result.new_items] == [f"news-{code}" for code in CODES]
    assert result.turma_count == len(CODES)


def test_every_session_writes_to_the_same_store(monkeypatch, settings):
    _run(monkeypatch, settings, _Sigaa())

    conn = connect(settings.db_path)
    try:
        repo = Repository(conn)
        stored = {
            turma.code: repo.known_news_ids(turma.id_turma) for turma in TURMAS
        }
    finally:
        conn.close()
    assert stored == {code: {f"news-{code}"} for code in CODES}


def test_a_class_error_in_either_session_fails_the_run_but_not_the_other_classes(
    monkeypatch, settings
):
    sigaa = _Sigaa()
    sigaa.unreadable_code = CODES[1]

    result = _run(monkeypatch, settings, sigaa)

    assert not result.ok
    assert result.error_stage == STAGE_NETWORK
    assert CODES[1] in result.error
    assert [s.code for s in result.classes if s.errors] == [CODES[1]]
    assert len(result.new_items) == len(CODES)


def test_a_second_login_that_is_rejected_fails_the_run(monkeypatch, settings):
    sigaa = _Sigaa()
    sigaa.failing_login = 2

    result = _run(monkeypatch, settings, sigaa)

    assert not result.ok
    assert result.error_stage == STAGE_AUTH
    # Only the rejected session's class is missing from the report.
    assert len(result.classes) == len(CODES) - 1
    assert result.classes[0].code == CODES[0]


def test_a_class_missing_from_the_second_sessions_portal_fails_the_run(monkeypatch, settings):
    sigaa = _Sigaa()
    original = _Client.list_turmas

    def portal(client):
        return original(client) if client.number == 1 else TURMAS[:1]

    monkeypatch.setattr(_Client, "list_turmas", portal)

    result = _run(monkeypatch, settings, sigaa)

    assert not result.ok
    assert result.error_stage == STAGE_PARSE


def test_a_single_class_needs_a_single_login(monkeypatch, settings):
    sigaa = _Sigaa(turmas=TURMAS[:1])

    result = _run(monkeypatch, settings, sigaa)

    assert result.ok, result.error
    assert len(sigaa.logins) == 1


def test_the_session_count_can_be_set_to_one(monkeypatch, settings):
    monkeypatch.setenv(SYNC_SESSIONS_ENV, "1")
    sigaa = _Sigaa()

    result = _run(monkeypatch, Settings(institution="ufpb", db_path=settings.db_path), sigaa)

    assert result.ok, result.error
    assert sigaa.entered_by_session() == [CODES]


@pytest.mark.parametrize("count", ["0", str(MAX_SYNC_SESSIONS + 1), "many"])
def test_an_invalid_session_count_is_rejected(monkeypatch, settings, count):
    monkeypatch.setenv(SYNC_SESSIONS_ENV, count)

    with pytest.raises(ValueError, match=SYNC_SESSIONS_ENV):
        Settings(institution="ufpb", db_path=settings.db_path)


def test_an_imported_browser_session_is_never_shared_between_threads(monkeypatch, tmp_path):
    monkeypatch.setenv("SIGAA_USER", "test-student")
    monkeypatch.setenv("SIGAA_SESSION", f"JSESSIONID={secrets.token_hex(16)}")
    monkeypatch.setattr("keyring.get_password", lambda *a: None)
    monkeypatch.delenv(SYNC_SESSIONS_ENV, raising=False)
    sigaa = _Sigaa()

    result = _run(monkeypatch, Settings(institution="ufg", db_path=tmp_path / "t.db"), sigaa)

    assert result.ok, result.error
    assert sigaa.entered_by_session() == [CODES]
