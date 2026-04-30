from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .models import Assignment, AssignmentStatus


@dataclass(frozen=True)
class TaskMapping:
    source_id: str
    task_id: str
    assignment_hash: str
    last_status: AssignmentStatus
    last_seen_at: str


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assignments (
              source_id TEXT PRIMARY KEY,
              task_id TEXT NOT NULL,
              assignment_hash TEXT NOT NULL,
              last_status TEXT NOT NULL,
              last_seen_at TEXT NOT NULL,
              course_name TEXT,
              title TEXT,
              url TEXT,
              due_at TEXT,
              raw_status TEXT
            )
            """
        )
        self._ensure_columns(
            conn,
            {
                "course_name": "TEXT",
                "title": "TEXT",
                "url": "TEXT",
                "due_at": "TEXT",
                "raw_status": "TEXT",
            },
        )
        return conn

    def _ensure_columns(self, conn: sqlite3.Connection, columns: dict[str, str]) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(assignments)")}
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE assignments ADD COLUMN {name} {definition}")

    def get(self, source_id: str) -> TaskMapping | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM assignments WHERE source_id = ?", (source_id,)
            ).fetchone()
        if row is None:
            return None
        if not row["task_id"]:
            return None
        return TaskMapping(
            source_id=row["source_id"],
            task_id=row["task_id"],
            assignment_hash=row["assignment_hash"],
            last_status=AssignmentStatus(row["last_status"]),
            last_seen_at=row["last_seen_at"],
        )

    def upsert(self, assignment: Assignment, task_id: str, assignment_hash: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO assignments
                  (
                    source_id, task_id, assignment_hash, last_status, last_seen_at,
                    course_name, title, url, due_at, raw_status
                  )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                  task_id = excluded.task_id,
                  assignment_hash = excluded.assignment_hash,
                  last_status = excluded.last_status,
                  last_seen_at = excluded.last_seen_at,
                  course_name = excluded.course_name,
                  title = excluded.title,
                  url = excluded.url,
                  due_at = excluded.due_at,
                  raw_status = excluded.raw_status
                """,
                (
                    assignment.source_id,
                    task_id,
                    assignment_hash,
                    assignment.status.value,
                    now,
                    assignment.course_name,
                    assignment.title,
                    assignment.url,
                    assignment.due_at.isoformat() if assignment.due_at else None,
                    assignment.raw_status,
                ),
            )

    def cache_assignments(self, assignments: list[Assignment]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            for assignment in assignments:
                existing = conn.execute(
                    "SELECT task_id FROM assignments WHERE source_id = ?",
                    (assignment.source_id,),
                ).fetchone()
                task_id = existing["task_id"] if existing and existing["task_id"] else ""
                conn.execute(
                    """
                    INSERT INTO assignments
                      (
                        source_id, task_id, assignment_hash, last_status, last_seen_at,
                        course_name, title, url, due_at, raw_status
                      )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_id) DO UPDATE SET
                      assignment_hash = excluded.assignment_hash,
                      last_status = excluded.last_status,
                      last_seen_at = excluded.last_seen_at,
                      course_name = excluded.course_name,
                      title = excluded.title,
                      url = excluded.url,
                      due_at = excluded.due_at,
                      raw_status = excluded.raw_status
                    """,
                    (
                        assignment.source_id,
                        task_id,
                        _assignment_hash(assignment),
                        assignment.status.value,
                        now,
                        assignment.course_name,
                        assignment.title,
                        assignment.url,
                        assignment.due_at.isoformat() if assignment.due_at else None,
                        assignment.raw_status,
                    ),
                )

    def completed_assignments(self) -> dict[str, Assignment]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT source_id, course_name, title, url, due_at, last_status, raw_status
                FROM assignments
                WHERE last_status = ?
                  AND course_name IS NOT NULL
                  AND title IS NOT NULL
                  AND url IS NOT NULL
                """,
                (AssignmentStatus.COMPLETED.value,),
            ).fetchall()
        return {
            row["source_id"]: Assignment(
                source_id=row["source_id"],
                course_name=row["course_name"],
                title=row["title"],
                url=row["url"],
                due_at=datetime.fromisoformat(row["due_at"]) if row["due_at"] else None,
                status=AssignmentStatus.COMPLETED,
                raw_status=row["raw_status"],
            )
            for row in rows
        }


def _assignment_hash(assignment: Assignment) -> str:
    from .pku import assignment_hash

    return assignment_hash(assignment)
