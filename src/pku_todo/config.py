from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*_args: object, **_kwargs: object) -> bool:
        return False


@dataclass(frozen=True)
class Config:
    base_url: str
    data_dir: Path
    todoist_api_token: str | None
    todoist_project_name: str
    bark_key: str | None
    bark_server: str
    pku_username: str | None
    pku_password: str | None
    pku_headless: bool


def load_config(env_file: str | None = None) -> Config:
    if env_file:
        load_dotenv(env_file)
    else:
        load_dotenv()

    data_dir = Path(os.environ.get("PKU_TODO_DATA_DIR", ".pku-todo")).expanduser()
    headless_value = os.environ.get("PKU_HEADLESS", "true").strip().lower()
    return Config(
        base_url=os.environ.get("PKU_BASE_URL", "https://course.pku.edu.cn").rstrip("/"),
        data_dir=data_dir,
        todoist_api_token=os.environ.get("TODOIST_API_TOKEN") or None,
        todoist_project_name=os.environ.get("TODOIST_PROJECT_NAME", "PKU Course"),
        bark_key=os.environ.get("BARK_KEY") or None,
        bark_server=os.environ.get("BARK_SERVER", "https://api.day.app").rstrip("/"),
        pku_username=os.environ.get("PKU_USERNAME") or None,
        pku_password=os.environ.get("PKU_PASSWORD") or None,
        pku_headless=headless_value not in {"0", "false", "no", "off"},
    )
