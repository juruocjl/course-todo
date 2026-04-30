from __future__ import annotations

from pathlib import Path


class AppPaths:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.storage_state = data_dir / "pku-storage-state.json"
        self.sqlite = data_dir / "state.sqlite3"

    def ensure(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
