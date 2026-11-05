"""The student a hosted MCP request acts for.

A local install serves one student, resolved from the keyring or environment by
``Settings``. A hosted deployment serves many: the auth layer resolves each call
to a ``Tenant`` and runs it inside ``tenant_scope()``, so every store read and
every SIGAA request uses that student's own database and session, and never the
server's keyring or environment.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Tenant:
    username: str
    institution: str
    db_path: Path
    # A live SIGAA credential: kept out of repr so it cannot reach a log line.
    session_cookie: str = field(repr=False)


_current: ContextVar[Tenant | None] = ContextVar("sigaa_tenant", default=None)


def current_tenant() -> Tenant | None:
    """The tenant of the running call, or None on a single-student install."""
    return _current.get()


@contextmanager
def tenant_scope(tenant: Tenant) -> Iterator[Tenant]:
    token = _current.set(tenant)
    try:
        yield tenant
    finally:
        _current.reset(token)
