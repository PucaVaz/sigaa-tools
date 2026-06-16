"""Data access over the SQLite store. Returns and accepts domain models."""

from __future__ import annotations

import json
import sqlite3

from ..models import (
    Attendance,
    AttendanceRecord,
    Deadline,
    Grade,
    Material,
    NewsItem,
    Student,
    Turma,
    TurmaGrade,
)


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

    # --- materials -------------------------------------------------------
    def known_material_ids(self, id_turma: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT id FROM material WHERE id_turma = ?", (id_turma,)
        ).fetchall()
        return {r["id"] for r in rows}

    def insert_material(self, item: Material) -> None:
        self._conn.execute(
            """INSERT OR IGNORE INTO material (id, id_turma, topic, title, kind, url, is_new)
               VALUES (?, ?, ?, ?, ?, ?, 1)""",
            (item.id, item.id_turma, item.topic, item.title, item.kind, item.url),
        )
        self._conn.commit()

    def get_materials(
        self, id_turma: str | None = None, kind: str | None = None, unread_only: bool = False
    ) -> list[Material]:
        clauses, params = [], []
        if id_turma:
            clauses.append("id_turma = ?")
            params.append(id_turma)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if unread_only:
            clauses.append("is_new = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM material {where} ORDER BY id_turma, fetched_at", params
        ).fetchall()
        return [_material(r) for r in rows]

    def mark_materials_seen(self, material_ids: list[str]) -> None:
        if not material_ids:
            return
        placeholders = ",".join("?" * len(material_ids))
        self._conn.execute(
            f"UPDATE material SET is_new = 0 WHERE id IN ({placeholders})", material_ids
        )
        self._conn.commit()

    # --- grades ----------------------------------------------------------
    def upsert_grade(self, grade: Grade) -> None:
        self._conn.execute(
            """INSERT INTO grade (semester, code, discipline, units, exam, result,
                                  absences, status, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(semester, code) DO UPDATE SET
                 discipline=excluded.discipline, units=excluded.units, exam=excluded.exam,
                 result=excluded.result, absences=excluded.absences, status=excluded.status,
                 updated_at=datetime('now')""",
            (grade.semester, grade.code, grade.discipline, json.dumps(grade.units),
             grade.exam, grade.result, grade.absences, grade.status),
        )
        self._conn.commit()

    def get_grades(self, semester: str | None = None, code: str | None = None) -> list[Grade]:
        clauses, params = [], []
        if semester:
            clauses.append("semester = ?")
            params.append(semester)
        if code:
            clauses.append("code = ?")
            params.append(code)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM grade {where} ORDER BY semester DESC, code", params
        ).fetchall()
        return [_grade(r) for r in rows]

    # --- turma grades ----------------------------------------------------
    def upsert_turma_grade(self, item: TurmaGrade) -> bool:
        """Insert or refresh a class's grades. Returns True if a real grade was
        posted or changed (empty/MATRICULADO refreshes are not notable)."""
        prev = self._conn.execute(
            "SELECT units, exam, result, status FROM turma_grade WHERE id_turma = ?",
            (item.id_turma,),
        ).fetchone()
        notable = _grade_changed(prev, item)
        self._conn.execute(
            """INSERT INTO turma_grade
                 (id_turma, units, exam, result, absences, status, is_new, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(id_turma) DO UPDATE SET
                 units=excluded.units, exam=excluded.exam, result=excluded.result,
                 absences=excluded.absences, status=excluded.status,
                 is_new=CASE WHEN excluded.is_new = 1 THEN 1 ELSE turma_grade.is_new END,
                 updated_at=datetime('now')""",
            (item.id_turma, json.dumps(item.units), item.exam, item.result,
             item.absences, item.status, 1 if notable else 0),
        )
        self._conn.commit()
        return notable

    def get_turma_grades(
        self, id_turma: str | None = None, unread_only: bool = False
    ) -> list[TurmaGrade]:
        clauses, params = [], []
        if id_turma:
            clauses.append("id_turma = ?")
            params.append(id_turma)
        if unread_only:
            clauses.append("is_new = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM turma_grade {where} ORDER BY id_turma", params
        ).fetchall()
        return [_turma_grade(r) for r in rows]

    def mark_turma_grades_seen(self, id_turmas: list[str]) -> None:
        if not id_turmas:
            return
        placeholders = ",".join("?" * len(id_turmas))
        self._conn.execute(
            f"UPDATE turma_grade SET is_new = 0 WHERE id_turma IN ({placeholders})", id_turmas
        )
        self._conn.commit()

    # --- attendance ------------------------------------------------------
    def upsert_attendance(self, item: Attendance) -> bool:
        """Insert or refresh a class's attendance map. Returns True when the map
        changed after a baseline exists (the first sync is never notable)."""
        prev = self._conn.execute(
            "SELECT records, total_absences FROM attendance WHERE id_turma = ?",
            (item.id_turma,),
        ).fetchone()
        records_json = json.dumps(
            [{"date": r.date, "status": r.status, "justified": r.justified}
             for r in item.records]
        )
        notable = prev is not None and (
            prev["records"] != records_json
            or prev["total_absences"] != item.total_absences
        )
        self._conn.execute(
            """INSERT INTO attendance
                 (id_turma, records, total_absences, justified_absences, max_absences,
                  is_new, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(id_turma) DO UPDATE SET
                 records=excluded.records, total_absences=excluded.total_absences,
                 justified_absences=excluded.justified_absences,
                 max_absences=excluded.max_absences,
                 is_new=CASE WHEN excluded.is_new = 1 THEN 1 ELSE attendance.is_new END,
                 updated_at=datetime('now')""",
            (item.id_turma, records_json, item.total_absences, item.justified_absences,
             item.max_absences, 1 if notable else 0),
        )
        self._conn.commit()
        return notable

    def get_attendance(
        self, id_turma: str | None = None, unread_only: bool = False
    ) -> list[Attendance]:
        clauses, params = [], []
        if id_turma:
            clauses.append("id_turma = ?")
            params.append(id_turma)
        if unread_only:
            clauses.append("is_new = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM attendance {where} ORDER BY id_turma", params
        ).fetchall()
        return [_attendance(r) for r in rows]

    def mark_attendance_seen(self, id_turmas: list[str]) -> None:
        if not id_turmas:
            return
        placeholders = ",".join("?" * len(id_turmas))
        self._conn.execute(
            f"UPDATE attendance SET is_new = 0 WHERE id_turma IN ({placeholders})", id_turmas
        )
        self._conn.commit()

    # --- deadlines -------------------------------------------------------
    def known_deadline_ids(self) -> set[str]:
        rows = self._conn.execute("SELECT id FROM deadline").fetchall()
        return {r["id"] for r in rows}

    def upsert_deadline(self, item: Deadline) -> bool:
        """Insert or refresh a deadline. Returns True if it was new."""
        is_new = item.id not in self.known_deadline_ids()
        self._conn.execute(
            """INSERT INTO deadline (id, id_turma, kind, title, date, detail, is_new)
               VALUES (?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title, date=excluded.date, detail=excluded.detail""",
            (item.id, item.id_turma, item.kind, item.title, item.date, item.detail),
        )
        self._conn.commit()
        return is_new

    def update_deadline_body(self, deadline_id: str, body: str) -> None:
        self._conn.execute("UPDATE deadline SET body = ? WHERE id = ?", (body, deadline_id))
        self._conn.commit()

    def get_deadlines(self, id_turma: str | None = None, unread_only: bool = False) -> list[Deadline]:
        clauses, params = [], []
        if id_turma:
            clauses.append("id_turma = ?")
            params.append(id_turma)
        if unread_only:
            clauses.append("is_new = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM deadline {where} ORDER BY date", params
        ).fetchall()
        return [_deadline(r) for r in rows]

    def mark_deadlines_seen(self, deadline_ids: list[str]) -> None:
        if not deadline_ids:
            return
        placeholders = ",".join("?" * len(deadline_ids))
        self._conn.execute(
            f"UPDATE deadline SET is_new = 0 WHERE id IN ({placeholders})", deadline_ids
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


def _material(row: sqlite3.Row) -> Material:
    return Material(
        id=row["id"], id_turma=row["id_turma"], topic=row["topic"], title=row["title"],
        kind=row["kind"], url=row["url"],
    )


def _grade(row: sqlite3.Row) -> Grade:
    return Grade(
        semester=row["semester"], code=row["code"], discipline=row["discipline"],
        units=json.loads(row["units"]) if row["units"] else [],
        exam=row["exam"], result=row["result"], absences=row["absences"], status=row["status"],
    )


def _grade_changed(prev: sqlite3.Row | None, item: TurmaGrade) -> bool:
    """A grade is notable when it carries real content (a unit/exame/resultado, or
    a terminal status) and differs from what was stored. Empty MATRICULADO rows —
    e.g. every class at the start of term — are never notable, so they don't flood
    the what's-new feed on the first sync."""
    has_content = bool(item.units) or bool(item.exam) or bool(item.result) or (
        item.status not in (None, "", "MATRICULADO")
    )
    if not has_content:
        return False
    if prev is None:
        return True
    prev_units = json.loads(prev["units"]) if prev["units"] else []
    return (
        prev_units != item.units
        or (prev["exam"] or None) != (item.exam or None)
        or (prev["result"] or None) != (item.result or None)
        or (prev["status"] or None) != (item.status or None)
    )


def _turma_grade(row: sqlite3.Row) -> TurmaGrade:
    return TurmaGrade(
        id_turma=row["id_turma"],
        units=json.loads(row["units"]) if row["units"] else [],
        exam=row["exam"], result=row["result"], absences=row["absences"], status=row["status"],
    )


def _attendance(row: sqlite3.Row) -> Attendance:
    records = [
        AttendanceRecord(date=r["date"], status=r["status"], justified=r["justified"])
        for r in (json.loads(row["records"]) if row["records"] else [])
    ]
    return Attendance(
        id_turma=row["id_turma"], records=records,
        total_absences=row["total_absences"],
        justified_absences=row["justified_absences"],
        max_absences=row["max_absences"],
    )


def _deadline(row: sqlite3.Row) -> Deadline:
    return Deadline(
        id=row["id"], id_turma=row["id_turma"], kind=row["kind"], title=row["title"],
        date=row["date"], detail=row["detail"], body=row["body"],
    )
