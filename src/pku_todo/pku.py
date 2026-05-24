from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urljoin, urlparse

from .models import Assignment, AssignmentStatus

ASSIGNMENT_KEYWORDS = (
    "作业",
    "assignment",
    "assignments",
    "homework",
    "submit",
    "测验",
)
OPEN_HINTS = ("未提交", "未完成", "待提交", "not submitted", "incomplete")
ALERTS_URL = "/webapps/streamViewer/streamViewer?cmd=view&streamName=alerts&globalNavigation=false"


class PkuLoginError(RuntimeError):
    pass


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_due_at(text: str) -> datetime | None:
    patterns = [
        r"(?P<year>20\d{2})[-/.年](?P<month>\d{1,2})[-/.月](?P<day>\d{1,2})日?"
        r"(?:\s*星期[一二三四五六日天])?\s*"
        r"(?P<ampm>上午|下午|AM|PM|am|pm)?\s*"
        r"(?P<hour>\d{1,2})[:：](?P<minute>\d{2})",
        r"(?P<year>20\d{2})[-/.年](?P<month>\d{1,2})[-/.月](?P<day>\d{1,2})日?\s*(?P<hour>\d{1,2})[:：](?P<minute>\d{2})",
        r"(?P<year>20\d{2})[-/.年](?P<month>\d{1,2})[-/.月](?P<day>\d{1,2})日?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            groupdict = match.groupdict(default="0")
            parts = {
                k: int(v)
                for k, v in groupdict.items()
                if k in {"year", "month", "day", "hour", "minute"}
            }
            hour = parts.get("hour") or 23
            minute = parts.get("minute") or 59
            ampm = groupdict.get("ampm", "").lower()
            if ampm in {"下午", "pm"} and hour < 12:
                hour += 12
            elif ampm in {"上午", "am"} and hour == 12:
                hour = 0
            return datetime(
                parts["year"],
                parts["month"],
                parts["day"],
                hour,
                minute,
            )
    return None


def status_from_text(text: str) -> AssignmentStatus:
    lowered = text.lower()
    if any(hint.lower() in lowered for hint in OPEN_HINTS):
        return AssignmentStatus.OPEN
    if "复查提交历史记录" in text and "提交" in text and "尝试" in text:
        return AssignmentStatus.COMPLETED
    if "review submission history" in lowered and "submission" in lowered and "attempt" in lowered:
        return AssignmentStatus.COMPLETED
    return AssignmentStatus.UNKNOWN


def stable_source_id(course_name: str, title: str, url: str, due_at: datetime | None) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("content_id", "assignment_id", "attempt_id", "course_id"):
        if query.get(key):
            return f"{key}:{query[key][0]}"
    digest = hashlib.sha256(
        "|".join([course_name, title, url, due_at.isoformat() if due_at else ""]).encode()
    ).hexdigest()
    return f"sha256:{digest[:24]}"


def assignment_hash(assignment: Assignment) -> str:
    digest = hashlib.sha256(
        "|".join(
            [
                "todoist-due-v5",
                assignment.course_name,
                assignment.title,
                assignment.url,
                assignment.due_at.isoformat() if assignment.due_at else "",
                assignment.status.value,
                assignment.raw_status or "",
            ]
        ).encode()
    ).hexdigest()
    return digest


class PkuCourseClient:
    def __init__(
        self,
        base_url: str,
        storage_state: Path,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.storage_state = storage_state
        self.username = username
        self.password = password

    def save_login_state(self) -> None:
        sync_playwright = _playwright()
        self.storage_state.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto(self.base_url, wait_until="domcontentloaded")
            input("Log in to PKU Course in the browser, then press Enter here...")
            context.storage_state(path=str(self.storage_state))
            browser.close()

    def fetch_assignments(
        self,
        headless: bool = True,
        max_pages: int = 80,
        completed_cache: Mapping[str, Assignment] | None = None,
        review_assignments: list[Assignment] | None = None,
    ) -> list[Assignment]:
        sync_playwright = _playwright()
        if not self.storage_state.exists():
            raise RuntimeError(
                f"PKU login state not found at {self.storage_state}. Run `pku_todo auth-pku` first."
            )
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(storage_state=str(self.storage_state))
            page = context.new_page()
            page.goto(self.base_url, wait_until="networkidle")
            self._ensure_logged_in(page, context)
            assignments = self._fetch_alert_assignments(context, completed_cache or {})
            for assignment in review_assignments or []:
                if assignment.source_id in {item.source_id for item in assignments}:
                    continue
                refreshed = self._assignment_detail(
                    context,
                    {
                        "title": assignment.title,
                        "course": assignment.course_name,
                        "url": assignment.url,
                        "text": assignment.raw_status or "",
                    },
                )
                assignments.append(refreshed)
            if not assignments:
                assignments = self._crawl(context, page, max_pages=max_pages)
            browser.close()
        return assignments

    def _fetch_alert_assignments(
        self,
        context: Any,
        completed_cache: Mapping[str, Assignment],
    ) -> list[Assignment]:
        page = context.new_page()
        try:
            page.goto(urljoin(self.base_url, ALERTS_URL), wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(8000)
            self._ensure_logged_in(page, context)
            if self._is_login_page(page):
                page.goto(urljoin(self.base_url, ALERTS_URL), wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(8000)
            entries = self._alert_entries(page)
        finally:
            page.close()

        assignments: dict[str, Assignment] = {}
        for entry in entries:
            detail = self._assignment_detail(context, entry)
            assignments[detail.source_id] = detail
        return sorted(assignments.values(), key=lambda item: (item.due_at or datetime.max, item.title))

    def _alert_entries(self, page: Any) -> list[dict[str, str]]:
        items = page.eval_on_selector_all(
            ".stream_item",
            """els => els.map((el) => {
                const context = el.querySelector(".stream_context");
                const title = el.querySelector(".eventTitle")?.innerText?.trim() || "";
                const course = el.querySelector(".stream_area_name")?.innerText?.trim() || "";
                const action = context?.innerText?.trim() || "";
                const open = el.querySelector("a.browse[onclick*='uploadAssignment']");
                return {
                    id: el.id || "",
                    title,
                    course,
                    action,
                    onclick: open?.getAttribute("onclick") || "",
                    text: el.innerText || ""
                };
            })""",
        )
        entries: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        for item in items:
            action = normalize_space(item.get("action", ""))
            title = normalize_space(item.get("title", ""))
            course = normalize_space(item.get("course", ""))
            url = self._url_from_onclick(item.get("onclick", ""))
            if not title or not course or not url:
                continue
            if not action.startswith("作业 ") and not action.lower().startswith("assignment "):
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            entries.append({"title": title, "course": course, "url": url, "text": item.get("text", "")})
        return entries

    def _url_from_onclick(self, onclick: str) -> str | None:
        match = re.search(r"loadContentFrame\('([^']+)'", onclick)
        if not match:
            return None
        return urljoin(self.base_url, html.unescape(match.group(1)))

    def _assignment_detail(self, context: Any, entry: dict[str, str]) -> Assignment:
        page = context.new_page()
        try:
            page.goto(entry["url"], wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(500)
            body = normalize_space(page.locator("body").inner_text(timeout=15000))
        finally:
            page.close()
        status = status_from_text(body)
        due_at = parse_due_at(body) or parse_due_at(entry.get("text", ""))
        title = entry["title"]
        course_name = entry["course"]
        source_id = stable_source_id(course_name, title, entry["url"], due_at)
        return Assignment(
            source_id=source_id,
            course_name=course_name,
            title=title,
            url=entry["url"],
            due_at=due_at,
            status=status,
            raw_status=self._raw_status(body, entry.get("text", "")),
        )

    def _raw_status(self, body: str, fallback: str) -> str | None:
        if status_from_text(body) == AssignmentStatus.COMPLETED:
            return "submitted"
        if status_from_text(body) == AssignmentStatus.OPEN:
            return "open"
        return normalize_space(fallback)[:500] or None

    def _ensure_logged_in(self, page: Any, context: Any) -> None:
        if not self._is_login_page(page):
            return
        self._login(page)
        page.wait_for_timeout(3000)
        if self._is_login_page(page):
            raise PkuLoginError("自动登录后仍停留在 PKU 登录页，可能需要验证码、短信验证码或 OTP。")
        context.storage_state(path=str(self.storage_state))

    def _is_login_page(self, page: Any) -> bool:
        current_url = page.url.lower()
        if "iaaa.pku.edu.cn" in current_url or "/webapps/login" in current_url:
            return True
        try:
            title = page.title().lower()
            body = page.locator("body").inner_text(timeout=3000)
        except Exception:
            return False
        return (
            "unified authentication system" in title
            or ("用户名" in body and "密" in body and "验证码" in body)
            or ("User ID" in body and "Password" in body and "CAPTCHA" in body)
        )

    def _login(self, page: Any) -> None:
        if not self.username or not self.password:
            raise PkuLoginError("PKU 登录态已失效，但未配置 PKU_USERNAME/PKU_PASSWORD，无法自动重登。")

        if "iaaa.pku.edu.cn" not in page.url.lower():
            try:
                page.locator("text=校园卡用户").first.click(timeout=5000)
                page.wait_for_load_state("domcontentloaded", timeout=30000)
            except Exception:
                page.goto(
                    urljoin(self.base_url, "/webapps/bb-sso-BBLEARN/login.html"),
                    wait_until="domcontentloaded",
                    timeout=60000,
                )

        try:
            page.locator("#user_name, input[name='userName']").first.fill(self.username, timeout=10000)
            page.locator("#password, input[name='password']").first.fill(self.password, timeout=10000)
            self._check_interactive_challenges(page)
            page.locator("#logon_button, input[type='submit']").first.click(timeout=10000)
            page.wait_for_load_state("networkidle", timeout=60000)
        except PkuLoginError:
            raise
        except Exception as exc:
            raise PkuLoginError(f"自动登录 PKU 失败：{exc}") from exc

    def _check_interactive_challenges(self, page: Any) -> None:
        challenge_selectors = [
            ("#valid_code", "验证码"),
            ("#sms_code", "短信验证码"),
            ("#otp_code", "OTP"),
        ]
        visible: list[str] = []
        for selector, name in challenge_selectors:
            try:
                if page.locator(selector).first.is_visible(timeout=1000):
                    visible.append(name)
            except Exception:
                pass
        if visible:
            raise PkuLoginError(f"PKU 登录需要{('/'.join(visible))}，无法自动完成。")

    def _crawl(self, context: Any, start_page: Any, max_pages: int) -> list[Assignment]:
        seen_pages: set[str] = set()
        queued: list[tuple[str, str | None]] = [(start_page.url, None)]
        assignments: dict[str, Assignment] = {}

        while queued and len(seen_pages) < max_pages:
            url, course_hint = queued.pop(0)
            if url in seen_pages or not url.startswith(self.base_url):
                continue
            seen_pages.add(url)
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(500)
                html_text = normalize_space(page.locator("body").inner_text(timeout=10000))
                course_name = course_hint or self._course_name(page)
                for item in self._assignment_links(page, course_name, html_text):
                    assignments[item.source_id] = item
                for link, link_text in self._candidate_links(page):
                    if link in seen_pages or any(existing == link for existing, _ in queued):
                        continue
                    next_hint = course_name if course_hint else self._course_hint_from_text(link_text)
                    queued.append((link, next_hint))
            finally:
                page.close()

        return sorted(assignments.values(), key=lambda item: (item.due_at or datetime.max, item.title))

    def _candidate_links(self, page: Any) -> list[tuple[str, str]]:
        links = page.eval_on_selector_all(
            "a[href]",
            """els => els.map(a => ({href: a.href, text: a.innerText || a.textContent || ""}))""",
        )
        candidates: list[tuple[str, str]] = []
        for link in links:
            href = link.get("href", "")
            text = normalize_space(link.get("text", ""))
            haystack = f"{href} {text}".lower()
            if not href.startswith(self.base_url):
                continue
            if any(keyword.lower() in haystack for keyword in ASSIGNMENT_KEYWORDS):
                candidates.append((href, text))
            elif "course_id=" in href and "/webapps/" in href:
                candidates.append((href, text))
            elif "type=course" in haystack and "/webapps/blackboard/execute/launcher" in href:
                candidates.append((href, text))
        return candidates[:30]

    def _assignment_links(self, page: Any, course_name: str, page_text: str) -> list[Assignment]:
        links = page.eval_on_selector_all(
            "a[href]",
            """els => els.map(a => ({
                href: a.href,
                text: a.innerText || a.textContent || "",
                parent: a.closest("li, tr, div, article, section")?.innerText || ""
            }))""",
        )
        result: list[Assignment] = []
        page_status = status_from_text(page_text)
        for link in links:
            href = urljoin(self.base_url, link.get("href", ""))
            text = normalize_space(link.get("text", ""))
            parent = normalize_space(link.get("parent", ""))
            haystack = f"{href} {text} {parent}".lower()
            if not self._is_assignment_task(href, text, parent):
                continue
            status = status_from_text(parent) if parent else page_status
            if status == AssignmentStatus.UNKNOWN:
                status = page_status
            due_at = parse_due_at(parent) or parse_due_at(page_text)
            title = text[:180]
            source_id = stable_source_id(course_name, title, href, due_at)
            result.append(
                Assignment(
                    source_id=source_id,
                    course_name=course_name,
                    title=title,
                    url=href,
                    due_at=due_at,
                    status=status,
                    raw_status=parent[:500] if parent else None,
                )
            )
        return result

    def _is_assignment_task(self, href: str, text: str, parent: str) -> bool:
        if not href.startswith(self.base_url):
            return False
        lowered_href = href.lower()
        lowered_text = text.lower()
        lowered_parent = parent.lower()
        if "/bbcswebdav/" in lowered_href:
            return False
        if "homeworkcheck" in lowered_href or "查看作业成绩" in text:
            return False
        if "uploadassignment" in lowered_href:
            return True
        if "listcontent.jsp" in lowered_href:
            return False
        haystack = f"{lowered_href} {lowered_text} {lowered_parent}"
        return any(keyword.lower() in haystack for keyword in ASSIGNMENT_KEYWORDS) and parse_due_at(parent)

    def _course_hint_from_text(self, text: str) -> str | None:
        if not text or ":" not in text:
            return None
        _, name = text.split(":", 1)
        return normalize_space(name).removesuffix("(活动标签)")[:120] or None

    def _course_name(self, page: Any) -> str:
        for selector in ("#crumb_2", "#crumb_1", ".breadcrumbs a", "h1", "title"):
            try:
                text = normalize_space(page.locator(selector).first.inner_text(timeout=1000))
            except Exception:
                continue
            if text:
                return text[:120]
        return "PKU Course"


def _playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Playwright is required for PKU scraping. Install dependencies with "
            "`pip install -e .` and run `python -m playwright install chromium`."
        ) from exc
    return sync_playwright
