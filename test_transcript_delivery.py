from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
import server

class DeliveryTests(unittest.TestCase):
    def test_wait_progress_and_completion(self):
        with patch('server.lecture_transcript', return_value={'status':'processing','duration_seconds':100,'processed_seconds':50}):
            result = server.wait_lecture_transcript('video', 0)
            self.assertEqual(result['progress_percent'], 50)
            self.assertEqual(result['next_action'], 'report_progress_then_wait_again')
        with patch('server.lecture_transcript', side_effect=[{'status':'processing'}, {'status':'complete','segments':[]}]), patch('server.time.sleep'):
            self.assertEqual(server.wait_lecture_transcript('video')['next_action'], 'stage_lecture_transcript_then_upload_and_verify_drive')
        with patch('server.lecture_transcript', return_value={'status':'failed'}):
            self.assertEqual(server.wait_lecture_transcript('video')['status'], 'failed')

    def test_stage_and_cleanup(self):
        result = {'status':'complete','segments':[{'start':0,'end':65,'text':'회계 강의'}]}
        with TemporaryDirectory() as directory, patch('server.STAGING', Path(directory)), patch('server.lecture_transcript', return_value=result):
            staged = server.stage_lecture_transcript('video','재무회계',9,'강의')
            path = Path(staged['local_path'])
            self.assertEqual(staged['filename'], '재무회계_09주차_강의_전사.txt')
            self.assertEqual(staged['size_bytes'], path.stat().st_size)
            self.assertIn('[00:00:00–00:01:05] 회계 강의', path.read_text())
            self.assertFalse(staged['drive_saved'])
            server.delete_staged_material(staged['staging_id'])
            self.assertFalse(path.exists())

    def test_reject_partial_and_unsafe_filename(self):
        with TemporaryDirectory() as directory, patch('server.STAGING', Path(directory)), patch('server.lecture_transcript', return_value={'status':'processing'}):
            self.assertEqual(server.stage_lecture_transcript('video','회계',9,'강의')['status'], 'not_ready')
            self.assertEqual(list(Path(directory).iterdir()), [])
            with self.assertRaises(ValueError):
                server.stage_lecture_transcript('video','../회계',9,'강의')

if __name__ == '__main__':
    unittest.main()
