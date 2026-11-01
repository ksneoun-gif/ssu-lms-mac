"""Exchange a fresh LearningX launch link for a verified LMS session."""

import json
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse

import requests


CANVAS = "https://canvas.ssu.ac.kr"


def launch_course(url: str) -> int:
    if len(url) > 16384:
        raise ValueError("LearningX 링크가 너무 깁니다.")
    parsed = urlparse(url)
    match = re.fullmatch(r"/courses/([1-9][0-9]*)/external_tools/sessionless_launch", parsed.path)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (parsed.scheme != "https" or parsed.netloc not in {"canvas.ssu.ac.kr", "canvas.ssu.ac.kr:443"}
            or parsed.fragment or not match
            or set(query) - {"session_token", "verifier", "platform", "display"}
            or any(len(values) != 1 for values in query.values())
            or not re.fullmatch(r"[A-Za-z0-9_-]{20,4096}", query.get("session_token", [""])[0])
            or not re.fullmatch(r"[a-fA-F0-9]{64,256}", query.get("verifier", [""])[0])):
        raise ValueError("숭실대 LearningX에서 새로 발급한 주차학습 링크가 필요합니다.")
    return int(match[1])


class ToolForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.action = None
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and attrs.get("id") == "tool_form":
            if self.action is not None or attrs.get("method", "").lower() != "post":
                raise ValueError("주차학습 인증 양식이 올바르지 않습니다.")
            self.action = urljoin(CANVAS, attrs.get("action", ""))
            self.active = True
        if tag == "input" and self.active and attrs.get("name"):
            name = attrs["name"]
            if name in self.fields or attrs.get("type", "").lower() != "hidden":
                raise ValueError("주차학습 인증 양식이 올바르지 않습니다.")
            self.fields[name] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.active = False


def request(client, method, url, data=None):
    for _ in range(8):
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc not in {"canvas.ssu.ac.kr", "canvas.ssu.ac.kr:443"}:
            raise ValueError("학교 인증이 허용되지 않은 주소로 이동했습니다.")
        if method == "POST" and url != CANVAS + "/learningx/lti/modulebuilder":
            raise ValueError("허용되지 않은 인증 양식입니다.")
        response = client.request(method, url, data=data, timeout=30, allow_redirects=False)
        if not response.is_redirect:
            return response
        # Never replay the signed LTI form to a different endpoint.
        if method == "POST" and response.status_code not in (301, 302, 303):
            response.close()
            raise ValueError("인증 양식을 다시 전송하는 이동은 허용되지 않습니다.")
        url = urljoin(url, response.headers["Location"])
        response.close()
        method, data = "GET", None
    raise RuntimeError("학교 인증 이동 횟수가 제한을 초과했습니다.")


def recover(launch_url: str) -> dict:
    from server import COOKIE_DOMAINS, get, materials, save_session

    course_id = launch_course(launch_url)
    try:
        with requests.Session() as client:
            client.headers["User-Agent"] = "Mozilla/5.0"
            # A consumed verifier can return 404 while still creating the Canvas session.
            response = request(client, "GET", launch_url)
            if response.status_code not in (200, 404):
                response.raise_for_status()
            response.close()
            with request(client, "GET", f"{CANVAS}/api/v1/courses/{course_id}") as check:
                check.raise_for_status()
                course = json.loads(check.text.removeprefix("while(1);"))
                if not isinstance(course, dict) or course.get("id") != course_id:
                    raise ValueError("앱 링크로 강좌 인증을 확인하지 못했습니다.")
            with request(client, "GET", f"{CANVAS}/courses/{course_id}/external_tools/71") as page:
                page.raise_for_status()
                form = ToolForm()
                form.feed(page.text)
            if form.action != CANVAS + "/learningx/lti/modulebuilder" or not form.fields.get("oauth_signature"):
                raise ValueError("학교가 주차학습 인증 양식을 제공하지 않았습니다.")
            with request(client, "POST", form.action, form.fields) as response:
                response.raise_for_status()
            token = next((c.value for c in client.cookies
                          if c.name == "xn_api_token" and c.domain.lstrip(".") == "canvas.ssu.ac.kr"), None)
            if not token:
                raise ValueError("LearningX API 인증을 발급받지 못했습니다.")
            client.lms_token = token
            with get(client, CANVAS + "/learningx/api/v1/learn_activities/courses?term_ids[]=50") as response:
                courses = response.json()
            if not isinstance(courses, list) or not all(isinstance(row, dict) and row.get("id") for row in courses):
                raise ValueError("학교 강좌 API 응답이 올바르지 않습니다.")
            files = materials(client, course_id)
            cookies = [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path,
                        "expires": c.expires if c.expires is not None else -1, "secure": c.secure}
                       for c in client.cookies if c.domain.lstrip(".") in COOKIE_DOMAINS]
            save_session(cookies, "learningx")
            return {"authenticated": True, "verified_live": True, "source": "learningx",
                    "course_count": len(courses), "verified_course_id": course_id, "material_count": len(files)}
    except (requests.RequestException, ValueError, KeyError, RuntimeError, OSError):
        # HTTP exceptions contain credential-bearing URLs; never return them to MCP.
        return {"authenticated": False, "verified_live": False, "source": "learningx",
                "message": "LearningX 인증 복구 실패. 앱에서 새 주차학습 링크로 재시도하세요. 기존 세션은 유지됩니다."}


def refresh_lti_token(client: requests.Session | None = None) -> bool:
    """Silently renew xn_api_token using the active Canvas session via LTI tool launch."""
    from server import COOKIE_DOMAINS, save_session, session

    if client is None:
        try:
            client = session(allow_refresh=False)
        except Exception:
            return False

    try:
        check = client.get(f"{CANVAS}/api/v1/users/self/courses", params={"enrollment_state": "active"}, timeout=15)
        if check.status_code != 200:
            return False
        courses = json.loads(check.text.removeprefix("while(1);"))
        if not isinstance(courses, list) or not courses:
            return False
        course_id = courses[0].get("id")
        if not course_id:
            return False

        with request(client, "GET", f"{CANVAS}/courses/{course_id}/external_tools/71") as page:
            if page.status_code != 200:
                return False
            form = ToolForm()
            form.feed(page.text)
        if form.action != CANVAS + "/learningx/lti/modulebuilder" or not form.fields.get("oauth_signature"):
            return False
        with request(client, "POST", form.action, form.fields) as response:
            if response.status_code != 200:
                return False
        token = next((c.value for c in client.cookies
                      if c.name == "xn_api_token" and c.domain.lstrip(".") == "canvas.ssu.ac.kr"), None)
        if not token:
            return False
        client.lms_token = token
        cookies = [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path,
                    "expires": c.expires if c.expires is not None else -1, "secure": c.secure}
                   for c in client.cookies if c.domain.lstrip(".") in COOKIE_DOMAINS]
        save_session(cookies, "lti_refresh")
        return True
    except (requests.RequestException, ValueError, KeyError, RuntimeError, OSError):
        return False


