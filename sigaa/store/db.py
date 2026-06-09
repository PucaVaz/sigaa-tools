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

CREATE TABLE IF NOT EXISTS material (
    id         TEXT PRIMARY KEY,
    id_turma   TEXT NOT NULL REFERENCES turma(id_turma),
    topic      TEXT,
    title      TEXT,
    kind       TEXT,
    url        TEXT,
    is_new     INTEGER NOT NULL DEFAULT 1,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_material_turma ON material(id_turma);

CREATE TABLE IF NOT EXISTS grade (
    semester   TEXT NOT NULL,
    code       TEXT NOT NULL,
    discipline TEXT,
    units      TEXT,
    exam       TEXT,
    result     TEXT,
    absences   TEXT,
    status     TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (semester, code)
);

CREATE TABLE IF NOT EXISTS turma_grade (
    id_turma   TEXT PRIMARY KEY REFERENCES turma(id_turma),
    units      TEXT,
    exam       TEXT,
    result     TEXT,
    absences   TEXT,
    status     TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS deadline (
    id         TEXT PRIMARY KEY,
    id_turma   TEXT,
    kind       TEXT,
    title      TEXT,
    date       TEXT,
    detail     TEXT,
    is_new     INTEGER NOT NULL DEFAULT 1,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_deadline_turma ON deadline(id_turma);

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
