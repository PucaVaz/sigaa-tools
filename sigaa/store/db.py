"""SQLite connection and schema. Idempotent: safe to call connect() repeatedly."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS student (
    matricula TEXT PRIMARY KEY,
    name      TEXT,
    course    TEXT,
    email     TEXT,
    semester  TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS turma (
    id_turma     TEXT PRIMARY KEY,
    code         TEXT,
    name         TEXT,
    room         TEXT,
    schedule_raw TEXT,
    semester     TEXT,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS news (
    id         TEXT PRIMARY KEY,
    id_turma   TEXT NOT NULL REFERENCES turma(id_turma),
    date       TEXT,
    title      TEXT,
    body       TEXT,
    is_new     INTEGER NOT NULL DEFAULT 1,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_news_turma ON news(id_turma);
CREATE INDEX IF NOT EXISTS idx_news_new ON news(is_new);

CREATE TABLE IF NOT EXISTS sync_run (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL DEFAULT (datetime('now')),
    new_count   INTEGER NOT NULL DEFAULT 0,
    ok          INTEGER NOT NULL DEFAULT 1,
    detail      TEXT
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    return conn
