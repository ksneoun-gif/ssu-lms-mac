from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path

from server import delete_staged_material, session, trusted


def test_download_origin_allowlist():
    assert trusted("https://commons.ssu.ac.kr/file.pdf")
    assert trusted("https://canvas.ssu.ac.kr/learningx/api/v1/courses")
    assert not trusted("http://commons.ssu.ac.kr/file.pdf")
    assert not trusted("https://commons.ssu.ac.kr.evil.example/file.pdf")
    assert not trusted("https://attacker@commons.ssu.ac.kr/file.pdf")


def test_session_cookie_does_not_expire_locally():
    with patch("server.STATE") as state, patch("server.time.time", return_value=10**10):
        state.exists.return_value = True
        state.read_text.return_value = '{"cookies":[{"name":"xn_api_token","value":"test","domain":"canvas.ssu.ac.kr","path":"/","expires":-1}]}'
        assert session().lms_token == "test"


def test_staged_file_cleanup_is_confined():
    with TemporaryDirectory() as directory, patch("server.STAGING", Path(directory)):
        tmp_path = Path(directory)
        staged = tmp_path / "lms-abcdefgh.pdf"
        staged.write_bytes(b"test")
        assert delete_staged_material(staged.name) == {"deleted": True}
        assert not staged.exists()
        try:
            delete_staged_material("../session.json")
        except ValueError:
            pass
        else:
            raise AssertionError("path traversal accepted")


def test_transcript_id_confined():
    from lecture import job_path
    for bad in ('../session', '/tmp/x', 'x?token=secret'):
        try:
            job_path(bad)
        except ValueError:
            pass
        else:
            raise AssertionError('transcript path traversal accepted')


def test_live_auth_rejects_stale_cookie():
    from server import auth_status
    with patch('server.list_courses', side_effect=RuntimeError('expired')):
        assert auth_status()['authenticated'] is False



def test_media_origins():
    from lecture import trusted_media
    assert trusted_media('https://ssuin-object.commonscdn.com/ssu-contents/contents/x.mp4')
    assert trusted_media('https://ssuin-object.commonscdn.com/ssu-contents/contents31/ssu1000001/x.mp4')
    assert trusted_media('https://ssu-toast.commonscdn.com/contents31/ssu1000001/x.mp4')
    for url in ('http://ssu-toast.commonscdn.com/contents31/ssu1000001/x.mp4',
                'https://ssu-toast.commonscdn.com.evil.test/contents31/ssu1000001/x.mp4',
                'https://user@ssu-toast.commonscdn.com/contents31/ssu1000001/x.mp4',
                'https://ssu-toast.commonscdn.com:8443/contents31/ssu1000001/x.mp4',
                'https://ssu-toast.commonscdn.com/other/x.mp4',
                'https://ssuin-object.commonscdn.com/ssu-contents/contents31/ssu1000002/x.mp4',
                'https://ssuin-object.commonscdn.com/ssu-contents/contents31/ssu1000001-evil/x.mp4',
                'http://ssuin-object.commonscdn.com/ssu-contents/contents31/ssu1000001/x.mp4',
                'https://ssuin-object.commonscdn.com.evil.test/ssu-contents/contents31/ssu1000001/x.mp4'):
        assert not trusted_media(url)



def test_weekly_content_keeps_non_files_and_empty_weeks():
    from server import list_weekly_content, materials
    rows = [{"title": "1주차", "module_items": [
        {"title": "영상", "type": "video", "content_data": {"item_content_data": {"content_id": "real-video"}}},
        {"title": "예정", "content_data": {"item_content_data": {"content_id": "not_open"}}}]},
        {"title": "2주차", "module_items": []}]
    with patch('server.modules', return_value=rows), patch('server.session'):
        assert materials(None, 1) == []
        result = list_weekly_content(1)
        assert result[0]['items'][0]['content_id'] == 'real-video'
        assert result[0]['items'][1]['available'] is False
        assert result[1]['items'] == []


def test_media_new_paths_and_malformed_urls():
    from lecture import trusted_media
    assert trusted_media('https://ssuin-object.commonscdn.com/ssu-contents/contents29/ssu1000001/a.mp4')
    assert trusted_media('https://ssu-toast.commonscdn.com/contents15/ssu1000001/a.mp4')
    # Older lectures live in other numbered buckets.
    assert trusted_media('https://ssu-toast.commonscdn.com/contents20/ssu1000001/5d288e033a70c/contents/media_files/main_(c1f0).mp4')
    assert trusted_media('https://ssu-toast.commonscdn.com/contents28/ssu1000001/5f6c45addb95/contents/media_files/main_(e8f6).mp4')
    assert not trusted_media('https://ssu-toast.commonscdn.com/contentsX/ssu1000001/a.mp4')
    assert not trusted_media('https://ssu-toast.commonscdn.com/contents1234/ssu1000001/a.mp4')
    assert not trusted_media('https://ssu-toast.commonscdn.com/contents20/ssu1000002/a.mp4')
    for url in ('https://[bad', 'https://ssu-toast.commonscdn.com:bad/contents15/ssu1000001/a.mp4',
                'https://ssu-toast.commonscdn.com/contents15/ssu1000001/../other/a.mp4',
                'https://ssu-toast.commonscdn.com/contents15/ssu1000001/%2e%2e/a.mp4',
                'https://ssu-toast.commonscdn.com/contents15/ssu1000001/%252e%252e/a.mp4'):
        assert not trusted_media(url)


def test_http_status_is_safe_and_not_expiry_claim():
    import requests
    from server import auth_status
    response = requests.Response()
    response.status_code = 400
    with patch('server.list_courses', side_effect=requests.HTTPError('secret-url', response=response)):
        result = auth_status()
        assert result['http_status'] == 400 and result['authenticated'] is None
        assert 'secret-url' not in str(result)


def test_worker_spawn_failure_is_retryable():
    from server import lecture_transcript
    with TemporaryDirectory() as directory, patch('lecture.ROOT', Path(directory)), patch('server.subprocess.Popen', side_effect=OSError('failed')):
        result = lecture_transcript('test-worker')
        assert result['status'] == 'failed'
        assert lecture_transcript('test-worker', False)['status'] == 'failed'


def test_dead_worker_and_completed_cache():
    import json
    from server import lecture_transcript
    with TemporaryDirectory() as directory, patch('lecture.ROOT', Path(directory)):
        path = Path(directory) / 'test-worker.json'
        path.write_text(json.dumps({'status': 'processing'}))
        assert lecture_transcript('test-worker', False)['status'] == 'failed'
        path.write_text(json.dumps({'status': 'complete', 'segments': []}))
        assert lecture_transcript('test-worker', False)['status'] == 'complete'


if __name__ == "__main__":
    checks = [value for name, value in list(globals().items())
              if name.startswith("test_") and callable(value)]
    for check in checks:
        check()
    print(f"{len(checks)} server regression checks passed")

