"""OS paths and non-destructive worker status checks."""
import ctypes
import os
import subprocess
import sys
from pathlib import Path

APP_DIR = (Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local')))
           if sys.platform == 'win32' else Path.home() / 'Library/Application Support') / 'ssu-lms-download-mcp'
WORKER_OPTIONS = ({'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
                  if sys.platform == 'win32' else {'start_new_session': True})

LOGIN_STATUS = APP_DIR / 'login-status.json'
KEEP_ALIVE_STATUS = APP_DIR / 'keep-alive-status.json'
KEEP_ALIVE_PID = APP_DIR / 'keep-alive.pid'


def login_status(status=None):
    """Persist only fixed status codes, never browser errors or credential URLs."""
    import json
    if status is not None:
        temporary = LOGIN_STATUS.with_suffix('.tmp')
        temporary.write_text(json.dumps({'status': status}), encoding='utf-8')
        temporary.replace(LOGIN_STATUS)
        return {'status': status}
    try:
        return json.loads(LOGIN_STATUS.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'status': 'not_started'}


def keep_alive_status(status=None, **kwargs):
    """Track session keep-alive status and metrics."""
    import json
    import time
    if status is not None:
        data = {'status': status, 'updated_at': time.time()}
        data.update(kwargs)
        temporary = KEEP_ALIVE_STATUS.with_suffix('.tmp')
        temporary.write_text(json.dumps(data), encoding='utf-8')
        temporary.replace(KEEP_ALIVE_STATUS)
        return data
    try:
        return json.loads(KEEP_ALIVE_STATUS.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'status': 'idle'}

def browser_channel():
    """Use an installed Chrome or Edge; keep Chrome on other platforms."""
    if sys.platform != 'win32':
        return 'chrome'
    roots = [Path(os.environ[key]) for key in
             ('LOCALAPPDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)') if os.environ.get(key)]
    selected = os.environ.get('SSU_LMS_BROWSER', '').lower()
    if selected and selected not in ('chrome', 'msedge'):
        raise RuntimeError('SSU_LMS_BROWSER must be chrome or msedge.')
    for channel, relative in (('chrome', 'Google/Chrome/Application/chrome.exe'),
                              ('msedge', 'Microsoft/Edge/Application/msedge.exe')):
        if (not selected or selected == channel) and any((root / relative).is_file() for root in roots):
            return channel
    raise RuntimeError('Install Google Chrome or Microsoft Edge first.')


def process_running(pid):
    if pid <= 0:
        return False
    if sys.platform != 'win32':
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:
            return False
        raise OSError(error, 'Cannot query worker process')
    try:
        code = ctypes.c_ulong()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise OSError(ctypes.get_last_error(), 'Cannot query worker exit code')
        return code.value == 259
    finally:
        kernel.CloseHandle(handle)
