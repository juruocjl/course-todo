from __future__ import annotations

import json
import urllib.error
import urllib.request

from .models import Assignment


class BarkError(RuntimeError):
    pass


class BarkClient:
    def __init__(self, key: str, server: str = "https://api.day.app") -> None:
        self.key = key
        self.server = server.rstrip("/")

    def notify_new_assignment(self, assignment: Assignment) -> None:
        due = assignment.due_at.strftime("%Y-%m-%d %H:%M") if assignment.due_at else "无截止时间"
        payload = {
            "title": "PKU 新作业",
            "body": f"{assignment.course_name}\n{assignment.title}\n截止：{due}",
            "url": assignment.url,
            "group": "PKU Course",
        }
        self._post(payload)

    def notify_login_failure(self, reason: str) -> None:
        payload = {
            "title": "PKU 登录失败",
            "body": reason,
            "group": "PKU Course",
        }
        self._post(payload)

    def _post(self, payload: dict[str, str]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode()
        request = urllib.request.Request(
            f"{self.server}/{self.key}",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise BarkError(f"Bark push failed: {exc.code} {detail}") from exc
