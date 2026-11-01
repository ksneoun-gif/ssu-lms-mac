"""Unit tests for LMS session keep-alive and background auto-refresh."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import requests

import keep_alive
import runtime
import server


class KeepAliveTests(unittest.TestCase):
    def test_ping_session_success_and_updates_status(self):
        client = MagicMock()
        client.lms_token = "valid_token"
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = [{"id": 101, "name": "Computer Networks"}]
        response.cookies = []
        client.get.return_value = response

        with TemporaryDirectory() as directory, \
                patch.object(keep_alive, "APP_DIR", Path(directory)), \
                patch.object(keep_alive, "SESSION_FILE", Path(directory) / "session.json"), \
                patch.object(runtime, "KEEP_ALIVE_STATUS", Path(directory) / "keep-alive-status.json"):
            success = keep_alive.ping_session(client)
            self.assertTrue(success)
            st = runtime.keep_alive_status()
            self.assertEqual(st["status"], "ok")
            self.assertIn("last_ping", st)

    def test_ping_session_syncs_refreshed_cookies(self):
        client = MagicMock()
        client.lms_token = "valid_token"
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = [{"id": 101}]
        cookie = MagicMock()
        cookie.name = "xn_api_token"
        cookie.value = "refreshed_token"
        cookie.domain = "canvas.ssu.ac.kr"
        cookie.path = "/"
        cookie.expires = 2000000000
        cookie.secure = True
        response.cookies = [cookie]
        client.get.return_value = response

        with TemporaryDirectory() as directory, \
                patch.object(keep_alive, "APP_DIR", Path(directory)), \
                patch.object(keep_alive, "SESSION_FILE", Path(directory) / "session.json"), \
                patch.object(server, "APP_DIR", Path(directory)), \
                patch.object(server, "STATE", Path(directory) / "session.json"), \
                patch.object(runtime, "KEEP_ALIVE_STATUS", Path(directory) / "keep-alive-status.json"):
            # write initial session
            server.save_session([{"name": "xn_api_token", "value": "old_token", "domain": "canvas.ssu.ac.kr", "path": "/"}])
            self.assertTrue(keep_alive.ping_session(client))
            # Verify session file was updated with new token
            saved = json.loads((Path(directory) / "session.json").read_text(encoding="utf-8"))
            tok = next(c for c in saved["cookies"] if c["name"] == "xn_api_token")
            self.assertEqual(tok["value"], "refreshed_token")

    def test_keep_alive_once_falls_back_to_auto_refresh(self):
        with patch.object(keep_alive, "ping_session", side_effect=[False, True]), \
                patch.object(keep_alive, "auto_refresh_session", return_value=True):
            res = keep_alive.keep_alive_once()
            self.assertEqual(res["status"], "refreshed")

    def test_session_auto_refreshes_when_expired(self):
        with TemporaryDirectory() as directory, \
                patch.object(server, "APP_DIR", Path(directory)), \
                patch.object(server, "STATE", Path(directory) / "session.json"), \
                patch.object(server, "try_auto_refresh") as mock_refresh:
            # write expired session
            server.save_session([{"name": "xn_api_token", "value": "old", "domain": "canvas.ssu.ac.kr", "path": "/", "expires": 1000}])
            mock_refresh.side_effect = lambda: server.save_session(
                [{"name": "xn_api_token", "value": "new_fresh_token", "domain": "canvas.ssu.ac.kr", "path": "/", "expires": 4000000000}]
            ) or True

            s = server.session(allow_refresh=True)
            self.assertEqual(s.lms_token, "new_fresh_token")
            mock_refresh.assert_called_once()

    def test_get_retries_with_refreshed_session_on_401(self):
        client = MagicMock()
        client.lms_token = "stale"
        client.cookies = MagicMock()

        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_401.is_redirect = False

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.is_redirect = False
        resp_200.headers = {"Content-Type": "application/json"}
        resp_200.cookies = []

        client.get.side_effect = [resp_401, resp_200]

        with patch.object(server, "trusted", return_value=True), \
                patch.object(server, "try_auto_refresh", return_value=True), \
                patch.object(server, "session") as mock_session:
            new_s = MagicMock()
            new_s.lms_token = "fresh"
            mock_session.return_value = new_s

            res = server.get(client, "https://canvas.ssu.ac.kr/learningx/api/v1/courses", allow_refresh=True)
            self.assertEqual(res.status_code, 200)

    def test_tools_registered(self):
        tool_names = [tool.name for tool in server.mcp._tool_manager.list_tools()]
        self.assertIn("keep_alive_session", tool_names)
        self.assertIn("refresh_session", tool_names)
        self.assertIn("keep_alive_status_check", tool_names)


if __name__ == "__main__":
    unittest.main()
