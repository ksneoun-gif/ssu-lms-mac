"""Offline checks for the shipped plugin, without school access."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import bootstrap

ROOT = Path(__file__).resolve().parent
PLUGIN = ROOT / 'plugins/ssu-lms'

class PackageTests(unittest.TestCase):
    def test_runtime_copies_match(self):
        for name in ('server.py','learningx.py','lecture.py','login.py','runtime.py','keep_alive.py','bootstrap.py','launch.cjs','requirements.txt'):
            self.assertEqual((ROOT/name).read_bytes(), (PLUGIN/name).read_bytes(), name)

    def test_portable_manifest(self):
        config = json.loads((PLUGIN/'.mcp.json').read_text(encoding='utf-8'))
        self.assertEqual(config['mcpServers']['ssu-lms']['command'], 'node')
        self.assertEqual(config['mcpServers']['ssu-lms']['cwd'], '.')
        self.assertEqual(config['mcpServers']['ssu-lms']['args'], ['./launch.cjs'])
        self.assertEqual(config, json.loads((ROOT/'mcp.json').read_text(encoding='utf-8')))

    def test_normal_startup_never_installs(self):
        with patch('sys.argv',['bootstrap.py']), patch('bootstrap.missing_modules',return_value=[]), patch('bootstrap.subprocess.run') as install, patch('bootstrap.subprocess.call',return_value=7):
            self.assertEqual(bootstrap.main(),7)
            install.assert_not_called()

    def test_launcher_uses_existing_environment(self):
        import shutil
        node_bin = shutil.which('node') or next((p for p in ['/usr/local/bin/node', '/opt/homebrew/bin/node', '/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node', os.path.expanduser('~/.aside/runtime/bin/node')] if os.path.exists(p)), None)
        if not node_bin:
            self.skipTest('Node.js binary not available')
        env=dict(os.environ,SSU_LMS_PYTHON=sys.executable,SSU_LMS_ENV=str(Path(sys.executable).parent.parent))
        result=subprocess.run([node_bin,str(PLUGIN/'launch.cjs'),'--check'],env=env,capture_output=True,text=True,check=True,timeout=30)
        self.assertTrue(json.loads(result.stdout)['ready'])

if __name__=='__main__':
    unittest.main()
