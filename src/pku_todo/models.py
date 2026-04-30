from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class AssignmentStatus(str, Enum):
    OPEN = "open"
    COMPLETED = "completed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Assignment:
    source_id: str
    course_name: str
    title: str
    url: str
    due_at: datetime | None
    status: AssignmentStatus
    raw_status: str | None = None

