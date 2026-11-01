import json
import sys
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import requests

import learningx
import server


LINK = learningx.CANVAS + "/courses/48795/external_tools/sessionless_launch?verifier=" + "a" * 128 + "&session_token=" + "b" * 100
FORM = '<form id="tool_form" action="/learningx/lti/modulebuilder" method="POST"><input type="hidden" name="oauth_signature" value="signed&amp;value"></form>'


def response(status=200, data=None, text=""):
    result = Mock(status_code=status, text=text or json.dumps(data), is_redirect=False)
    result.json.return_value = data
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    return result


class RecoveryTests(unittest.TestCase):
    def test_only_school_launch_links_are_accepted(self):
        self.assertEqual(learningx.launch_course(LINK), 48795)
        for link in [LINK.replace("canvas.ssu.ac.kr", "evil.test"),
                     LINK.replace("https:", "http:"), LINK + "&return_to=https://evil.test",
                     LINK + "&session_token=duplicate", LINK + "#fragment",
                     LINK.replace("canvas.ssu.ac.kr", "user@canvas.ssu.ac.kr"),
                     LINK.replace("canvas.ssu.ac.kr", "canvas.ssu.ac.kr:8443"),
                     LINK.replace("sessionless_launch", "grades")]:
            with self.subTest(link_type=link.split("?")[0]), self.assertRaises(ValueError):
                learningx.launch_course(link)

    def test_signed_form_decoding_and_rejection(self):
        parser = learningx.ToolForm()
        parser.feed(FORM)
        self.assertEqual(parser.fields, {"oauth_signature": "signed&value"})
        for html in [FORM.replace('method="POST"', 'method="GET"'), FORM + FORM,
                     FORM.replace('type="hidden"', 'type="text"')]:
            with self.assertRaises(ValueError):
                learningx.ToolForm().feed(html)

    def test_redirect_does_not_send_credentials_to_another_host(self):
        client = Mock()
        redirect = response(302)
        redirect.is_redirect = True
        redirect.headers = {"Location": "https://evil.test/"}
        client.request.return_value = redirect
        with self.assertRaises(ValueError):
            learningx.request(client, "GET", LINK)
        self.assertEqual(client.request.call_count, 1)
        with self.assertRaises(ValueError):
            learningx.request(client, "POST", learningx.CANVAS + "/courses/48795/grades", {})
        self.assertEqual(client.request.call_count, 1)

    def recover_with(self, page=FORM, token=True, network_error=None):
        client = requests.Session()
        if token:
            client.cookies.set("xn_api_token", "secret", domain="canvas.ssu.ac.kr", path="/", secure=True)
        replies = [response(404), response(text='while(1);{"id":48795}'), response(text=page), response()]
        with patch("learningx.requests.Session", return_value=client), \
             patch("learningx.request", side_effect=network_error or replies) as request_mock, \
             patch("server.get", return_value=response(data=[{"id": 48795}])) as get_mock, \
             patch("server.materials", return_value=[{"filename": "lecture.pdf"}]) as materials_mock, \
             patch("server.save_session") as save_mock:
            result = learningx.recover(LINK)
            return result, request_mock, get_mock, materials_mock, save_mock

    def test_save_requires_both_api_checks(self):
        result, calls, get_mock, materials_mock, save_mock = self.recover_with()
        self.assertTrue(result["verified_live"])
        self.assertEqual(result["material_count"], 1)
        self.assertEqual(calls.call_count, 4)
        get_mock.assert_called_once()
        materials_mock.assert_called_once()
        cookies, source = save_mock.call_args.args
        self.assertEqual(source, "learningx")
        self.assertEqual(cookies[0]["expires"], -1)
        self.assertNotIn("secret", json.dumps(result))

    def test_missing_token_or_foreign_form_never_replaces_session(self):
        for kwargs in [{"token": False}, {"page": FORM.replace('/learningx/lti/modulebuilder', 'https://evil.test/')},
                       {"network_error": requests.RequestException(LINK)}]:
            result, calls, _, _, save_mock = self.recover_with(**kwargs)
            self.assertFalse(result["authenticated"])
            save_mock.assert_not_called()
            self.assertNotIn("session_token", json.dumps(result))
            if "page" in kwargs:
                self.assertEqual(calls.call_count, 3)

    def test_material_failure_does_not_replace_session(self):
        with patch("server.materials", side_effect=RuntimeError("denied")), \
             patch("server.save_session") as save:
            client = requests.Session()
            client.cookies.set("xn_api_token", "secret", domain="canvas.ssu.ac.kr")
            with patch("learningx.requests.Session", return_value=client), \
                 patch("learningx.request", side_effect=[response(), response(data={"id":48795}), response(text=FORM), response()]), \
                 patch("server.get", return_value=response(data=[{"id":48795}])):
                self.assertFalse(learningx.recover(LINK)["authenticated"])
            save.assert_not_called()

    def test_atomic_session_save_and_failed_replace_preserve_state(self):
        with TemporaryDirectory() as directory, patch("server.APP_DIR", Path(directory)), \
             patch("server.STATE", Path(directory) / "session.json"):
            server.STATE.write_text("old state")
            with patch.object(Path, "replace", side_effect=OSError("write failed")):
                with self.assertRaises(OSError):
                    server.save_session([], "learningx")
            self.assertEqual(server.STATE.read_text(), "old state")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])
            server.save_session([], "learningx")
            self.assertEqual(json.loads(server.STATE.read_text())["source"], "learningx")
            if sys.platform != "win32":
                self.assertEqual(stat.S_IMODE(server.STATE.stat().st_mode), 0o600)

    def test_browser_fallback_and_auto_recovery(self):
        with patch("server.sys.platform", "darwin"), patch.object(Path, "exists", return_value=True):
            self.assertEqual(server.start_login()["next_tool"], "restore_learningx_session")
        with self.assertRaises(ValueError):
            server.start_login("unknown")

    def test_refresh_lti_token_success(self):
        client = requests.Session()
        client.cookies.set("xn_api_token", "new_token", domain="canvas.ssu.ac.kr")
        courses_resp = response(status=200, text='while(1);[{"id": 48795, "name": "Course"}]')
        tool_resp = response(status=200, text=FORM)
        post_resp = response(status=200)

        with patch("server.save_session") as mock_save, \
             patch.object(client, "get", return_value=courses_resp), \
             patch("learningx.request", side_effect=[tool_resp, post_resp]):
            result = learningx.refresh_lti_token(client)
            self.assertTrue(result)
            self.assertEqual(client.lms_token, "new_token")
            mock_save.assert_called_once()



if __name__ == "__main__":
    unittest.main()

