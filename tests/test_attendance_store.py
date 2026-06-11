from sigaa.models import Attendance, AttendanceRecord, Turma
from sigaa.store.db import connect
from sigaa.store.repository import Repository

ID_TURMA = "369279"


def _repo(tmp_path):
    repo = Repository(connect(tmp_path / "t.db"))
    repo.upsert_turma(Turma(id_turma=ID_TURMA, name="SD", code="DSCO00022"))
    return repo


def _attendance(total=6, records=None):
    records = records if records is not None else [
        AttendanceRecord(date="07/05/2026", status="2 Falta(s)"),
    ]
    return Attendance(
        id_turma=ID_TURMA, records=records,
        total_absences=total, justified_absences=0, max_absences=15,
    )


def test_attendance_roundtrip(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_attendance(_attendance())
    stored = repo.get_attendance(id_turma=ID_TURMA)
    assert len(stored) == 1
    assert stored[0].total_absences == 6
    assert stored[0].max_absences == 15
    assert stored[0].records[0].date == "07/05/2026"
    assert stored[0].records[0].justified is False


def test_first_sync_is_baseline_not_notable(tmp_path):
    repo = _repo(tmp_path)
    assert repo.upsert_attendance(_attendance()) is False
    assert repo.get_attendance(unread_only=True) == []


def test_new_absence_is_notable_and_unread(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_attendance(_attendance())
    grown = _attendance(total=8, records=[
        AttendanceRecord(date="07/05/2026", status="2 Falta(s)"),
        AttendanceRecord(date="12/06/2026", status="2 Falta(s)"),
    ])
    assert repo.upsert_attendance(grown) is True
    unread = repo.get_attendance(unread_only=True)
    assert len(unread) == 1 and unread[0].total_absences == 8


def test_unchanged_attendance_is_not_notable(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_attendance(_attendance())
    assert repo.upsert_attendance(_attendance()) is False


def test_mark_attendance_seen_clears_unread(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_attendance(_attendance())
    repo.upsert_attendance(_attendance(total=8))
    repo.mark_attendance_seen([ID_TURMA])
    assert repo.get_attendance(unread_only=True) == []
