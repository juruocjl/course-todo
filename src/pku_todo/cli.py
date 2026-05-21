from __future__ import annotations

import argparse
import json
import sys

from .bark import BarkClient, BarkError
from .config import load_config
from .paths import AppPaths
from .pku import PkuCourseClient, PkuLoginError
from .state import StateStore
from .sync import SyncService
from .todoist import TodoistClient, TodoistError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pku_todo")
    parser.add_argument("--env-file", default=None, help="Path to a .env file.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("auth-pku", help="Open browser login and save PKU session state.")
    sync_parser = subparsers.add_parser("sync", help="Sync assignments to Todoist.")
    sync_parser.add_argument("--dry-run", action="store_true", help="Fetch PKU assignments without writing Todoist.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.env_file)
    paths = AppPaths(config.data_dir)
    paths.ensure()

    try:
        if args.command == "auth-pku":
            PkuCourseClient(
                config.base_url,
                paths.storage_state,
                config.pku_username,
                config.pku_password,
            ).save_login_state()
            print(f"Saved PKU login state to {paths.storage_state}")
            return 0

        if args.command == "sync":
            pku = PkuCourseClient(
                config.base_url,
                paths.storage_state,
                config.pku_username,
                config.pku_password,
            )
            state = StateStore(paths.sqlite)
            assignments = pku.fetch_assignments(
                headless=config.pku_headless,
                completed_cache=state.completed_assignments(),
                review_assignments=state.pending_assignments(),
            )
            if args.dry_run:
                state.cache_assignments(assignments)
                print(
                    json.dumps(
                        [assignment.__dict__ | {"status": assignment.status.value} for assignment in assignments],
                        default=str,
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            if not config.todoist_api_token:
                raise RuntimeError("TODOIST_API_TOKEN is required. Put it in .env or the environment.")
            service = SyncService(
                state,
                TodoistClient(config.todoist_api_token),
                config.todoist_project_name,
                BarkClient(config.bark_key, config.bark_server) if config.bark_key else None,
            )
            counts = service.sync(assignments)
            print(json.dumps(counts, ensure_ascii=False))
            return 0

    except PkuLoginError as exc:
        if config.bark_key:
            try:
                BarkClient(config.bark_key, config.bark_server).notify_login_failure(str(exc))
            except BarkError as bark_exc:
                print(f"error: {exc}; also failed to send Bark alert: {bark_exc}", file=sys.stderr)
                return 1
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (RuntimeError, TodoistError, BarkError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 2
