"""Capture an LMS login from an isolated Chrome profile; never prints cookies."""

import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from server import save_session


from runtime import APP_DIR, browser_channel, login_status
PID = APP_DIR / "login.pid"


def open_dashboard(page):
    """The LMS home login alone does not initialize LearningX API cookies."""
    current = urlparse(page.url)
    if (current.hostname == 'lms.ssu.ac.kr' and current.path in ('/', '')
            and page.locator('a[href="/mypage"]').count()):
        page.goto('https://lms.ssu.ac.kr/mypage', wait_until='domcontentloaded', timeout=30000)
    elif current.hostname == 'smartid.ssu.ac.kr':
        # If credentials are saved/autofilled in the profile, attempt auto-submit
        try:
            has_user = page.evaluate("() => Boolean(document.getElementById('userid')?.value)")
            has_pwd = page.evaluate("() => Boolean(document.getElementById('pwd')?.value)")
            if has_user and has_pwd:
                page.evaluate("() => { const form = document.querySelector('form'); if (form) form.submit(); }")
        except Exception:
            pass


def perform_login(headless: bool = False, timeout_sec: int = 600) -> bool:
    """Execute browser login flow. Returns True if authentication succeeds."""
    APP_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    status_prefix = 'headless_' if headless else ''
    login_status(status_prefix + 'driver_starting')
    try:
        with sync_playwright() as playwright:
            login_status(status_prefix + 'browser_starting')
            browser = playwright.chromium.launch_persistent_context(
                str(APP_DIR / "chrome-profile"), channel=browser_channel(), headless=headless,
                args=["--no-first-run"], timeout=30000)
            try:
                page = browser.pages[0] if browser.pages else browser.new_page()
                page.goto("https://lms.ssu.ac.kr/", wait_until="domcontentloaded", timeout=30000)
                login_status(status_prefix + 'waiting_for_login')
                deadline = time.time() + timeout_sec
                while time.time() < deadline:
                    open_dashboard(page)
                    cookies = browser.cookies("https://canvas.ssu.ac.kr/")
                    if any(cookie["name"] == "xn_api_token" and (
                           cookie.get("expires", -1) <= 0 or cookie["expires"] > time.time())
                           for cookie in cookies):
                        token = next(c["value"] for c in cookies if c["name"] == "xn_api_token")
                        try:
                            check = browser.request.get(
                                "https://canvas.ssu.ac.kr/learningx/api/v1/learn_activities/courses?term_ids[]=50",
                                headers={"Authorization": "Bearer " + token}, timeout=15000)
                            if not check.ok or not isinstance(check.json(), list):
                                time.sleep(2)
                                continue
                        except Exception:
                            time.sleep(2)
                            continue
                        kept = [cookie for cookie in browser.cookies() if cookie["domain"].lstrip(".")
                                in {"ssu.ac.kr", "canvas.ssu.ac.kr", "commons.ssu.ac.kr"}]
                        save_session(kept)
                        login_status('authenticated')
                        return True
                    time.sleep(2)
                login_status(status_prefix + 'login_timeout')
                return False
            finally:
                browser.close()
    except Exception:
        login_status(status_prefix + 'browser_failed')
        return False
    finally:
        PID.unlink(missing_ok=True)


def main() -> None:
    headless = "--headless" in sys.argv
    timeout_sec = 45 if headless else 600
    try:
        PID.write_text(str(os.getpid()), encoding="utf-8")
        success = perform_login(headless=headless, timeout_sec=timeout_sec)
        sys.exit(0 if success else 1)
    finally:
        PID.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
