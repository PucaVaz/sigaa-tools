from __future__ import annotations

import os
import secrets
from pathlib import Path

import pytest


@pytest.fixture
def mcp_subprocess_env():
    """Factory for the env used to spawn `python -m sigaa.mcp_server` in tests.

    Strips ambient credentials, nulls the keyring backend and redirects the download
    directory into the test's tmp_path, so a spawned server can never reach the
    developer's real account or files. Extra variables are passed as keywords.
    """

    def build(download_dir: Path, **extra: str) -> dict[str, str]:
        environment = dict(os.environ)
        environment.pop("SIGAA_USER", None)
        environment.pop("SIGAA_PASS", None)
        environment.pop("SIGAA_MODE", None)
        environment["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        environment["SIGAA_DOWNLOAD_DIR"] = str(download_dir)
        environment.update(extra)
        return environment

    return build


FIXTURES = Path(__file__).parent / "fixtures"
TEST_USERNAME = "aluno.teste"
# Random per run: the tests only need a value that must never reach the output.
TEST_PASSWORD = secrets.token_urlsafe(16)


class FakeSigaa:
    """Scripted stand-in for ``SigaaClient`` that serves fixture pages.

    ``pages`` maps a turma id to its Principal page HTML and ``bodies`` maps a
    news id to its Visualizar page. ``failure`` is raised on first contact, as
    a login or network problem would be.
    """

    def __init__(self):
        from sigaa.models import Student

        self.student = Student(matricula="000", name="ALUNO TESTE")
        self.turmas = []
        self.pages: dict[str, str] = {}
        self.bodies: dict[str, str] = {}
        self.failure: Exception | None = None
        self.logins: list[tuple[str, str]] = []

    def add_class(self, id_turma: str, code: str, page_fixture: str) -> None:
        from sigaa.models import Turma

        self.turmas.append(Turma(id_turma=id_turma, name=code, code=code))
        self.pages[id_turma] = (FIXTURES / page_fixture).read_text(encoding="utf-8")

    def client_factory(self):
        fake = self

        class Client:
            def __init__(self, username, password, **_):
                fake.logins.append((username, password))

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

            def get_student(self):
                if fake.failure is not None:
                    raise fake.failure
                return fake.student

            def list_turmas(self):
                return list(fake.turmas)

            def enter_turma(self, turma):
                return fake.pages[turma.id_turma]

            def list_news(self, turma, turma_html=None):
                from sigaa.parsers import news as news_parser

                return news_parser.parse_news_list(turma_html, turma.id_turma)

            def get_news_body(self, turma, news_id, turma_html=None):
                from sigaa.parsers import news as news_parser

                html = fake.bodies.get(news_id)
                return news_parser.parse_news_body(html) if html else None

            def list_materials(self, turma, turma_html=None):
                return []

            def get_turma_grades(self, turma, turma_html=None):
                return None

            def get_course_plan(self, turma, turma_html=None):
                return None

            def get_attendance(self, turma, turma_html=None):
                return None

            def list_professors(self, turma, turma_html=None):
                return []

            def list_deadlines(self):
                return []

            def get_grades(self):
                return []

        return Client


@pytest.fixture
def clean_credentials(monkeypatch):
    """No ambient SIGAA env vars and an in-memory keyring. Returns the keyring dict."""
    import keyring

    monkeypatch.delenv("SIGAA_USER", raising=False)
    monkeypatch.delenv("SIGAA_PASS", raising=False)
    store: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(keyring, "get_password", lambda service, name: store.get((service, name)))
    return store


@pytest.fixture
def fake_sigaa(monkeypatch):
    from sigaa.services import sync as sync_module

    fake = FakeSigaa()
    monkeypatch.setattr(sync_module, "SigaaClient", fake.client_factory())
    return fake
