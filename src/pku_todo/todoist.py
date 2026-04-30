from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any


TODOIST_ROOT = "https://api.todoist.com/api/v1"


class TodoistError(RuntimeError):
    pass


class TodoistClient:
    def __init__(self, api_token: str) -> None:
        self.api_token = api_token

    def ensure_project(self, name: str) -> str:
        for project in self._paged_get("/projects"):
            if project.get("name") == name:
                return project["id"]
        created = self._request("POST", "/projects", {"name": name})
        return created["id"]

    def create_task(self, payload: dict[str, Any]) -> str:
        created = self._request("POST", "/tasks", payload)
        return created["id"]

    def update_task(self, task_id: str, payload: dict[str, Any]) -> None:
        self._request("POST", f"/tasks/{task_id}", payload)

    def complete_task(self, task_id: str) -> None:
        self._request("POST", f"/tasks/{task_id}/close")

    def _paged_get(self, path: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page_params = dict(params or {})
            if cursor:
                page_params["cursor"] = cursor
            query = f"?{urllib.parse.urlencode(page_params)}" if page_params else ""
            data = self._request("GET", f"{path}{query}")
            if isinstance(data, list):
                values.extend(data)
                return values
            if not isinstance(data, dict) or "results" not in data:
                raise TodoistError(
                    f"Expected Todoist paginated response for {path}, got {type(data).__name__}"
                )
            values.extend(data.get("results", []))
            cursor = data.get("next_cursor")
            if not cursor:
                return values

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self.api_token}",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
            headers["X-Request-Id"] = str(uuid.uuid4())
        request = urllib.request.Request(
            f"{TODOIST_ROOT}{path}",
            data=body,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise TodoistError(f"Todoist {method} {path} failed: {exc.code} {detail}") from exc
        if not raw:
            return None
        return json.loads(raw.decode())
