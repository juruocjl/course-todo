from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .bark import BarkClient
from .models import Assignment, AssignmentStatus
from .pku import assignment_hash
from .state import StateStore
from .todoist import TodoistClient


def task_payload(assignment: Assignment) -> dict[str, Any]:
    body_lines = [
        f"Course: {assignment.course_name}",
        f"Source: {assignment.url}",
        f"PKU status: {assignment.raw_status or assignment.status.value}",
        f"Synced at: {datetime.now(timezone.utc).isoformat()}",
    ]
    payload: dict[str, Any] = {
        "content": f"[{assignment.course_name}] {assignment.title}",
        "description": "\n".join(body_lines),
    }
    if assignment.due_at is not None:
        payload["due_datetime"] = assignment.due_at.strftime("%Y-%m-%dT%H:%M:%S")
        payload["due_lang"] = "en"
    return payload


class SyncService:
    def __init__(
        self,
        state: StateStore,
        todo: TodoistClient,
        project_name: str,
        bark: BarkClient | None = None,
    ) -> None:
        self.state = state
        self.todo = todo
        self.project_name = project_name
        self.bark = bark

    def sync(self, assignments: list[Assignment]) -> dict[str, int]:
        project_id = self.todo.ensure_project(self.project_name)
        counts = {"seen": len(assignments), "created": 0, "updated": 0, "completed": 0, "notified": 0}

        for assignment in assignments:
            current_hash = assignment_hash(assignment)
            mapping = self.state.get(assignment.source_id)
            if mapping is None:
                payload = task_payload(assignment) | {"project_id": project_id}
                task_id = self.todo.create_task(payload)
                counts["created"] += 1
                if assignment.status == AssignmentStatus.COMPLETED:
                    self.todo.complete_task(task_id)
                    counts["completed"] += 1
                elif self.bark is not None:
                    self.bark.notify_new_assignment(assignment)
                    counts["notified"] += 1
                self.state.upsert(assignment, task_id, current_hash)
                continue

            if mapping.assignment_hash != current_hash and assignment.status != AssignmentStatus.COMPLETED:
                self.todo.update_task(mapping.task_id, task_payload(assignment))
                counts["updated"] += 1

            if (
                assignment.status == AssignmentStatus.COMPLETED
                and mapping.last_status != AssignmentStatus.COMPLETED
            ):
                self.todo.complete_task(mapping.task_id)
                counts["completed"] += 1

            self.state.upsert(assignment, mapping.task_id, current_hash)

        return counts
