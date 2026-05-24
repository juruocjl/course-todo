from datetime import datetime

from pku_todo.models import Assignment, AssignmentStatus
from pku_todo.state import StateStore
from pku_todo.sync import SyncService, task_payload
from pku_todo.pku import assignment_hash


class FakeTodo:
    def __init__(self):
        self.created = []
        self.updated = []
        self.completed = []
        self.existing_task_id = None

    def ensure_task_list(self, display_name):
        return "list-1"

    def ensure_project(self, name):
        return "project-1"

    def create_task(self, payload):
        self.created.append(payload)
        return f"task-{len(self.created)}"

    def find_task_by_source(self, project_id, source_url):
        return self.existing_task_id

    def update_task(self, task_id, payload):
        self.updated.append((task_id, payload))

    def complete_task(self, task_id):
        self.completed.append(task_id)

    def reopen_task(self, task_id):
        self.updated.append((task_id, {"reopened": True}))


class FakeBark:
    def __init__(self):
        self.notified = []

    def notify_new_assignment(self, item):
        self.notified.append(item)

    def notify_login_failure(self, reason):
        self.notified.append(reason)


def assignment(status=AssignmentStatus.OPEN, title="HW1"):
    return Assignment(
        source_id="source-1",
        course_name="Math",
        title=title,
        url="https://course.pku.edu.cn/a",
        due_at=datetime(2026, 5, 1, 23, 59),
        status=status,
        raw_status="未提交" if status == AssignmentStatus.OPEN else "已提交",
    )


def test_task_payload_contains_due_date():
    payload = task_payload(assignment())
    assert payload["content"] == "[Math] HW1"
    assert payload["due_datetime"] == "2026-05-01T23:59:00"
    assert "deadline_date" not in payload


def test_sync_creates_new_task(tmp_path):
    todo = FakeTodo()
    counts = SyncService(StateStore(tmp_path / "state.sqlite3"), todo, "PKU Course").sync([assignment()])
    assert counts["created"] == 1
    assert todo.created[0]["content"] == "[Math] HW1"
    assert todo.created[0]["project_id"] == "project-1"


def test_sync_notifies_new_unfinished_assignment(tmp_path):
    todo = FakeTodo()
    bark = FakeBark()
    counts = SyncService(StateStore(tmp_path / "state.sqlite3"), todo, "PKU Course", bark).sync(
        [assignment()]
    )
    assert counts["notified"] == 1
    assert bark.notified[0].title == "HW1"


def test_sync_does_not_notify_completed_assignment(tmp_path):
    todo = FakeTodo()
    bark = FakeBark()
    counts = SyncService(StateStore(tmp_path / "state.sqlite3"), todo, "PKU Course", bark).sync(
        [assignment(AssignmentStatus.COMPLETED)]
    )
    assert counts["notified"] == 0
    assert bark.notified == []


def test_sync_completes_existing_task_when_course_completed(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    todo = FakeTodo()
    service = SyncService(state, todo, "PKU Course")
    service.sync([assignment(AssignmentStatus.OPEN)])
    counts = service.sync([assignment(AssignmentStatus.COMPLETED)])
    assert counts["completed"] == 1
    assert todo.completed == ["task-1"]


def test_sync_reopens_task_when_false_completed_assignment_becomes_unknown(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    todo = FakeTodo()
    service = SyncService(state, todo, "PKU Course")
    service.sync([assignment(AssignmentStatus.COMPLETED)])
    counts = service.sync([assignment(AssignmentStatus.UNKNOWN)])
    assert counts["reopened"] == 1
    assert todo.updated[0] == ("task-1", {"reopened": True})


def test_sync_reuses_active_duplicate_instead_of_reopening_completed_mapping(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    todo = FakeTodo()
    service = SyncService(state, todo, "PKU Course")
    service.sync([assignment(AssignmentStatus.COMPLETED)])
    todo.existing_task_id = "active-task"
    counts = service.sync([assignment(AssignmentStatus.UNKNOWN)])
    assert counts["reopened"] == 0
    assert todo.updated[0][0] == "active-task"
    assert todo.updated[0][1]["content"] == "[Math] HW1"
    assert state.get("source-1").task_id == "active-task"


def test_sync_updates_changed_open_assignment(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    todo = FakeTodo()
    service = SyncService(state, todo, "PKU Course")
    service.sync([assignment(AssignmentStatus.OPEN, title="HW1")])
    counts = service.sync([assignment(AssignmentStatus.OPEN, title="HW1 revised")])
    assert counts["updated"] == 1
    assert todo.updated[0][1]["content"] == "[Math] HW1 revised"


def test_state_stores_completed_assignment_metadata(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    item = assignment(AssignmentStatus.COMPLETED)
    state.upsert(item, "task-1", assignment_hash(item))
    cached = state.completed_assignments()
    assert cached[item.source_id].title == "HW1"
    assert cached[item.source_id].due_at == datetime(2026, 5, 1, 23, 59)
    assert cached[item.source_id].status == AssignmentStatus.COMPLETED


def test_cached_assignment_without_task_mapping_does_not_block_creation(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    item = assignment(AssignmentStatus.COMPLETED)
    state.cache_assignments([item])
    assert state.get(item.source_id) is None
    assert state.completed_assignments()[item.source_id].status == AssignmentStatus.COMPLETED


def test_state_returns_pending_assignments(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    open_item = assignment(AssignmentStatus.OPEN)
    done_item = assignment(AssignmentStatus.COMPLETED, title="Done")
    done_item = type(done_item)(
        source_id="source-2",
        course_name=done_item.course_name,
        title=done_item.title,
        url="https://course.pku.edu.cn/done",
        due_at=done_item.due_at,
        status=done_item.status,
        raw_status=done_item.raw_status,
    )
    state.upsert(open_item, "task-1", assignment_hash(open_item))
    state.upsert(done_item, "task-2", assignment_hash(done_item))
    pending = state.pending_assignments()
    assert [item.source_id for item in pending] == [open_item.source_id]


def test_sync_reuses_existing_todoist_task_by_source_url(tmp_path):
    class ExistingTaskTodo(FakeTodo):
        def find_task_by_source(self, project_id, source_url):
            return "existing-task"

    todo = ExistingTaskTodo()
    counts = SyncService(StateStore(tmp_path / "state.sqlite3"), todo, "PKU Course").sync([assignment()])
    assert counts["created"] == 0
    assert counts["updated"] == 1
    assert todo.created == []
    assert todo.updated[0][0] == "existing-task"
