'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawnSync, spawn} = require('node:child_process');
const home = os.homedir();
const win = process.platform === 'win32';
const executable = directory => path.join(directory, win ? 'Scripts/python.exe' : 'bin/python');
const candidates = [process.env.SSU_LMS_PYTHON,
  process.env.SSU_LMS_ENV && executable(process.env.SSU_LMS_ENV),
  executable(path.join(__dirname, '.venv')),
  executable(path.join(__dirname, '.runtime')),
  executable(path.join(__dirname, '../../.runtime')),
  executable(path.join(home, 'Downloads/ssu-lms-download-mcp/.venv')),
  executable(path.join(home, 'Library/Application Support/ssu-lms-download-mcp/venv')),
  path.join(home, '.cache/codex-runtimes/codex-primary-runtime/dependencies/python', win ? 'python.exe' : 'bin/python3')];
if (win && process.env.LOCALAPPDATA) {
  const root = path.join(process.env.LOCALAPPDATA, 'Programs/Python');
  if (fs.existsSync(root)) for (const entry of fs.readdirSync(root)) candidates.push(path.join(root, entry, 'python.exe'));
}
candidates.push(win ? 'python.exe' : 'python3');
let selected;
for (const candidate of candidates.filter(Boolean)) {
  if (/[/\\]WindowsApps[/\\]/i.test(candidate)) continue;
  const probe = spawnSync(candidate, ['-I', '-c', 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,15) else 1)'], {windowsHide:true, timeout:10000, stdio:'ignore'});
  if (!probe.error && probe.status === 0) {selected=candidate;break;}
}
if (!selected) {
  console.error('Python 3.10-3.15 required. Install Python 3.12 or set SSU_LMS_PYTHON.');
  process.exit(1);
}
const child = spawn(selected, ['-u', path.join(__dirname, 'bootstrap.py'), ...process.argv.slice(2)], {windowsHide:true, stdio:['pipe','pipe','inherit']});
process.stdin.pipe(child.stdin);
child.stdout.pipe(process.stdout);
child.stdin.on('error', error => { if (error.code !== 'EPIPE') console.error(error.code); });
child.on('error', error => { console.error('LMS startup failed:', error.code); process.exit(1); });
child.on('close', code => process.exit(code ?? 1));
