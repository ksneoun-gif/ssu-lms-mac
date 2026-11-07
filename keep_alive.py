"""Keep LMS session alive via periodic pings and silent background re-authentication."""

import argparse
import json
import os
import plistlib
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from runtime import APP_DIR, KEEP_ALIVE_PID, KEEP_ALIVE_STATUS, WORKER_OPTIONS, keep_alive_status, process_running

SESSION_FILE = APP_DIR / "session.json"
LAUNCH_AGENT_LABEL = "kr.ac.ssu.lms-keepalive"
LAUNCH_AGENT_PATH = Path.home() / "Library/LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"


def ping_session(client: requests.Session | None = None) -> bool:
    """Send a lightweight authenticated request to keep the session alive."""
    from server import COOKIE_DOMAINS, save_session, session

    if client is None:
        try:
            client = session(allow_refresh=False)
        except Exception:
            return False

    url = "https://canvas.ssu.ac.kr/learningx/api/v1/learn_activities/courses?term_ids[]=50"
    try:
        headers = {"Authorization": "Bearer " + client.lms_token}
        response = client.get(url, headers=headers, timeout=20, allow_redirects=False)
        if response.status_code in (400, 401, 403):
            try:
                from learningx import refresh_lti_token
                if refresh_lti_token(client):
                    headers = {"Authorization": "Bearer " + client.lms_token}
                    response = client.get(url, headers=headers, timeout=20, allow_redirects=False)
            except Exception:
                pass
        if response.status_code == 200 and isinstance(response.json(), list):
            # Capture any refreshed cookies
            if response.cookies:
                try:
                    current_data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
                    cookie_dict = {c["name"]: c for c in current_data.get("cookies", [])}
                    for cookie in response.cookies:
                        if cookie.domain.lstrip(".") in COOKIE_DOMAINS:
                            cookie_dict[cookie.name] = {
                                "name": cookie.name,
                                "value": cookie.value,
                                "domain": cookie.domain,
                                "path": cookie.path,
                                "expires": cookie.expires if cookie.expires is not None else -1,
                                "secure": cookie.secure,
                            }
                    save_session(list(cookie_dict.values()), source="keep_alive")
                except Exception:
                    pass
            keep_alive_status("ok", last_ping=time.time())
            return True
        return False
    except Exception:
        return False


def auto_refresh_session() -> bool:
    """Attempt silent LTI token refresh or non-interactive headless browser login."""
    try:
        from learningx import refresh_lti_token
        if refresh_lti_token():
            keep_alive_status("refreshed", last_refresh=time.time())
            return True
    except Exception:
        pass

    script_path = Path(__file__).resolve().with_name("login.py")
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path), "--headless"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=50,
            check=False,
            **WORKER_OPTIONS,
        )
        if proc.returncode == 0 and ping_session():
            keep_alive_status("refreshed", last_refresh=time.time())
            return True
        return False
    except Exception:
        return False


def keep_alive_once() -> dict:
    """Perform one check-and-keepalive cycle with automatic silent fallback."""
    if ping_session():
        return {"status": "ok", "message": "세션이 정상 유지되고 있습니다."}
    # Session appears invalid or expired, try silent headless refresh
    if auto_refresh_session():
        return {"status": "refreshed", "message": "만료된 세션이 백그라운드에서 자동으로 갱신되었습니다."}
    keep_alive_status("expired", failed_at=time.time())
    return {"status": "expired", "message": "세션이 만료되었으며 수동 로그인이 필요합니다 (start_login 호출)."}


def run_daemon(interval_sec: int = 600, stop_event: threading.Event | None = None) -> None:
    """Continuously keep LMS session alive."""
    APP_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    KEEP_ALIVE_PID.write_text(str(os.getpid()), encoding="utf-8")
    keep_alive_status("running", interval_sec=interval_sec)
    try:
        last_run = 0.0
        while stop_event is None or not stop_event.is_set():
            # Wall-clock scheduling: after the Mac wakes from sleep, ping immediately
            # instead of finishing a stale sleep(), so the token is renewed before it is needed.
            if time.time() - last_run >= interval_sec:
                last_run = time.time()
                keep_alive_once()
            tick = min(30, interval_sec)
            if stop_event is not None:
                if stop_event.wait(timeout=tick):
                    break
            else:
                time.sleep(tick)
    finally:
        KEEP_ALIVE_PID.unlink(missing_ok=True)
        keep_alive_status("stopped")


def start_daemon_process() -> dict:
    """Launch background keep-alive worker process."""
    if KEEP_ALIVE_PID.exists():
        try:
            pid = int(KEEP_ALIVE_PID.read_text(encoding="utf-8"))
            if process_running(pid):
                return {"status": "already_running", "pid": pid}
        except (ValueError, OSError):
            pass
        KEEP_ALIVE_PID.unlink(missing_ok=True)

    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--run-daemon"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **WORKER_OPTIONS,
    )
    KEEP_ALIVE_PID.write_text(str(proc.pid), encoding="utf-8")
    keep_alive_status("running", pid=proc.pid)
    return {"status": "started", "pid": proc.pid}


def stop_daemon_process() -> dict:
    """Terminate background keep-alive worker process."""
    if not KEEP_ALIVE_PID.exists():
        return {"status": "not_running"}
    try:
        pid = int(KEEP_ALIVE_PID.read_text(encoding="utf-8"))
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(pid, 15)  # SIGTERM
    except Exception:
        pass
    finally:
        KEEP_ALIVE_PID.unlink(missing_ok=True)
        keep_alive_status("stopped")
    return {"status": "stopped"}


def install_launch_agent() -> dict:
    """Install and load macOS LaunchAgent for persistent session keep-alive."""
    if sys.platform != "darwin":
        return {"installed": False, "error": "LaunchAgent는 macOS에서만 지원됩니다."}

    LAUNCH_AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    plist_content = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [
            sys.executable,
            str(Path(__file__).resolve()),
            "--run-daemon",
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(APP_DIR / "keep-alive.log"),
        "StandardErrorPath": str(APP_DIR / "keep-alive.err"),
    }
    with open(LAUNCH_AGENT_PATH, "wb") as f:
        plistlib.dump(plist_content, f)

    # Load agent
    subprocess.run(["launchctl", "unload", str(LAUNCH_AGENT_PATH)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    res = subprocess.run(["launchctl", "load", "-w", str(LAUNCH_AGENT_PATH)], capture_output=True, text=True, check=False)
    if res.returncode == 0:
        return {"installed": True, "plist": str(LAUNCH_AGENT_PATH), "message": "macOS 백그라운드 세션 유지 에이전트가 설치되었습니다."}
    return {"installed": False, "error": res.stderr}


def uninstall_launch_agent() -> dict:
    """Unload and remove macOS LaunchAgent."""
    if sys.platform != "darwin" or not LAUNCH_AGENT_PATH.exists():
        return {"uninstalled": False, "message": "설치된 LaunchAgent가 없습니다."}
    subprocess.run(["launchctl", "unload", str(LAUNCH_AGENT_PATH)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    LAUNCH_AGENT_PATH.unlink(missing_ok=True)
    return {"uninstalled": True, "message": "macOS 백그라운드 세션 유지 에이전트가 삭제되었습니다."}


def main() -> None:
    parser = argparse.ArgumentParser(description="Soongsil LMS Session Keep-Alive")
    parser.add_argument("--ping", action="store_true", help="Send a single keep-alive ping")
    parser.add_argument("--run-daemon", action="store_true", help="Run keep-alive loop in foreground")
    parser.add_argument("--start", action="store_true", help="Start background keep-alive daemon")
    parser.add_argument("--stop", action="store_true", help="Stop background keep-alive daemon")
    parser.add_argument("--status", action="store_true", help="Check keep-alive daemon status")
    parser.add_argument("--install-agent", action="store_true", help="Install macOS LaunchAgent for 24/7 session maintenance")
    parser.add_argument("--uninstall-agent", action="store_true", help="Uninstall macOS LaunchAgent")
    parser.add_argument("--interval", type=int, default=600, help="Interval in seconds between pings (default: 600)")

    args = parser.parse_args()
    if args.ping:
        res = keep_alive_once()
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif args.run_daemon:
        run_daemon(interval_sec=args.interval)
    elif args.start:
        res = start_daemon_process()
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif args.stop:
        res = stop_daemon_process()
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif args.status:
        st = keep_alive_status()
        is_running = False
        if KEEP_ALIVE_PID.exists():
            try:
                pid = int(KEEP_ALIVE_PID.read_text(encoding="utf-8"))
                is_running = process_running(pid)
            except Exception:
                pass
        st["process_running"] = is_running
        print(json.dumps(st, ensure_ascii=False, indent=2))
    elif args.install_agent:
        res = install_launch_agent()
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif args.uninstall_agent:
        res = uninstall_launch_agent()
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
