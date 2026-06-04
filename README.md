# PKU Course Todoist

Synchronize assignments from `course.pku.edu.cn` to a dedicated Todoist project.

## Setup

```bash
uv sync --extra dev
uv run python -m playwright install chromium
cp .env.example .env
```

Put your Todoist API token in `.env` as `TODOIST_API_TOKEN`.
You can find it in Todoist under `Settings` -> `Integrations` -> `Developer` -> `API token`.
Optionally set `BARK_KEY` to push newly-created unfinished assignments through Bark.
Optionally set `PKU_USERNAME` and `PKU_PASSWORD` to let the sync command retry PKU IAAA login when the saved browser session expires. If PKU requires CAPTCHA, SMS code, or OTP, the command sends a Bark login-failure alert instead.

## First Login

```bash
uv run pku_todo auth-pku
```

`auth-pku` opens a browser. Log in to the PKU course site manually, then press Enter in the terminal.

## Sync

```bash
uv run pku_todo sync
```

The command creates or reuses a Todoist project named `PKU Course`, creates one task per course assignment, and marks tasks completed only when the course page is a Blackboard submission-history page.

Use cron, systemd timers, launchd, or Windows Task Scheduler to run `pku_todo sync` periodically.
The `deploy/systemd/` directory contains user-unit templates for the current `ubuntu@hajimi` deployment.

## Notes

- Local state is stored under `.pku-todo/` by default.
- Assignment metadata and completion status are cached in SQLite. Completed assignments seen again in Blackboard alerts are reused from the cache and are not reopened for detail verification.
- Bark notifications are sent only when a new unfinished assignment is first created in Todoist.
- If the PKU session expires, the command tries IAAA username/password login and refreshes `.pku-todo/pku-storage-state.json`; interactive challenges trigger a Bark failure alert.
- The scraper is intentionally conservative. If the course page layout changes or completion cannot be confirmed, it keeps the Todoist task open rather than completing it incorrectly.
- The program does not submit assignments or modify anything on `course.pku.edu.cn`.
