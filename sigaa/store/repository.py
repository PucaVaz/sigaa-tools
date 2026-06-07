"""Data access over the SQLite store. Returns and accepts domain models."""

from __future__ import annotations

import sqlite3

from ..models import NewsItem, Student, Turma


class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # --- student ---------------------------------------------------------
    def upsert_student(self, student: Student) -> None:
        self._conn.execute(
            """INSERT INTO student (matricula, name, course, email, semester, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(matricula) DO UPDATE SET
                 name=excluded.name, course=excluded.course, email=excluded.email,
                 semester=excluded.semester, updated_at=datetime('now')""",
            (student.matricula, student.name, student.course, student.email, student.semester),
        )
        self._conn.commit()

    def get_student(self) -> Student | None:
        row = self._conn.execute("SELECT * FROM student LIMIT 1").fetchone()
        return _student(row) if row else None

    # --- turmas ----------------------------------------------------------
    def upsert_turma(self, turma: Turma) -> None:
        self._conn.execute(
            """INSERT INTO turma (id_turma, code, name, room, schedule_raw, semester, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(id_turma) DO UPDATE SET
                 code=excluded.code, name=excluded.name, room=excluded.room,
                 schedule_raw=excluded.schedule_raw, semester=excluded.semester,
                 updated_at=datetime('now')""",
            (turma.id_turma, turma.code, turma.name, turma.room, turma.schedule_raw, turma.semester),
        )
        self._conn.commit()

    def get_turmas(self) -> list[Turma]:
        rows = self._conn.execute("SELECT * FROM turma ORDER BY name").fetchall()
        return [_turma(r) for r in rows]

    def get_turma(self, code_or_id: str) -> Turma | None:
        row = self._conn.execute(
            "SELECT * FROM turma WHERE id_turma = ? OR code = ? LIMIT 1",
            (code_or_id, code_or_id),
        ).fetchone()
        return _turma(row) if row else None

    # --- news ------------------------------------------------------------
    def known_news_ids(self, id_turma: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT id FROM news WHERE id_turma = ?", (id_turma,)
        ).fetchall()
        return {r["id"] for r in rows}

    def insert_news(self, item: NewsItem) -> None:
        self._conn.execute(
            """INSERT OR IGNORE INTO news (id, id_turma, date, title, body, is_new)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (item.id, item.id_turma, item.date, item.title, item.body),
        )
        self._conn.commit()

    def update_news_body(self, news_id: str, body: str) -> None:
        self._conn.execute("UPDATE news SET body = ? WHERE id = ?", (body, news_id))
        self._conn.commit()

    def get_news(
        self, id_turma: str | None = None, unread_only: bool = False, since: str | None = None
    ) -> list[NewsItem]:
        clauses, params = [], []
        if id_turma:
            clauses.append("id_turma = ?")
            params.append(id_turma)
        if unread_only:
            clauses.append("is_new = 1")
        if since:
            clauses.append("date >= ?")
            params.append(since)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM news {where} ORDER BY date DESC", params
        ).fetchall()
        return [_news(r) for r in rows]

    def mark_news_seen(self, news_ids: list[str]) -> None:
        if not news_ids:
            return
        placeholders = ",".join("?" * len(news_ids))
        self._conn.execute(
            f"UPDATE news SET is_new = 0 WHERE id IN ({placeholders})", news_ids
        )
        self._conn.commit()

    # --- audit -----------------------------------------------------------
    def record_sync(self, new_count: int, ok: bool = True, detail: str | None = None) -> None:
        self._conn.execute(
            "INSERT INTO sync_run (new_count, ok, detail) VALUES (?, ?, ?)",
            (new_count, 1 if ok else 0, detail),
        )
        self._conn.commit()


def _student(row: sqlite3.Row) -> Student:
    return Student(
        matricula=row["matricula"], name=row["name"], course=row["course"],
        email=row["email"], semester=row["semester"],
    )


def _turma(row: sqlite3.Row) -> Turma:
    return Turma(
        id_turma=row["id_turma"], name=row["name"], code=row["code"], room=row["room"],
        schedule_raw=row["schedule_raw"], semester=row["semester"],
    )


def _news(row: sqlite3.Row) -> NewsItem:
    return NewsItem(
        id=row["id"], id_turma=row["id_turma"], date=row["date"], title=row["title"],
        body=row["body"],
    )
