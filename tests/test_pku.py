from datetime import datetime

from pku_todo.models import Assignment, AssignmentStatus
from pku_todo.pku import assignment_hash, parse_due_at, stable_source_id, status_from_text


def test_parse_due_at_chinese_datetime():
    assert parse_due_at("截止时间：2026年5月1日 23:30") == datetime(2026, 5, 1, 23, 30)


def test_parse_due_at_date_defaults_to_end_of_day():
    assert parse_due_at("Due: 2026-05-01") == datetime(2026, 5, 1, 23, 59)


def test_status_open_takes_precedence_over_submitted_hint():
    assert status_from_text("未提交 not submitted") == AssignmentStatus.OPEN


def test_status_completed():
    assert status_from_text("状态：已提交，等待批改") == AssignmentStatus.COMPLETED


def test_status_completed_from_blackboard_submission_history():
    text = "复查提交历史记录: Assignment 2 作业详细信息 成绩 尝试 26-4-20 下午7:29 提交 file.zip"
    assert status_from_text(text) == AssignmentStatus.COMPLETED


def test_stable_source_id_uses_content_id():
    assert (
        stable_source_id(
            "Course",
            "Title",
            "https://course.pku.edu.cn/webapps/assignment?content_id=_123_1&course_id=_9_1",
            None,
        )
        == "content_id:_123_1"
    )


def test_assignment_hash_changes_on_status():
    assignment = Assignment(
        source_id="id",
        course_name="Course",
        title="HW",
        url="https://example.test",
        due_at=None,
        status=AssignmentStatus.OPEN,
    )
    completed = Assignment(
        source_id="id",
        course_name="Course",
        title="HW",
        url="https://example.test",
        due_at=None,
        status=AssignmentStatus.COMPLETED,
    )
    assert assignment_hash(assignment) != assignment_hash(completed)
