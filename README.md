# 숭실대 LMS 다운로드 MCP

Windows의 Chrome/Edge 또는 macOS의 LearningX/Chrome에서 인증한 뒤 주차별 자료를 Google Drive에 업로드합니다. 로그인 쿠키는 Windows의 `%LOCALAPPDATA%/ssu-lms-download-mcp/`, macOS의 `~/Library/Application Support/ssu-lms-download-mcp/`에 저장되며 GitHub에 올라가지 않습니다.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

MCP 클라이언트는 `mcp.json`의 stdio 설정을 사용합니다. Mac에 LearningX가 있으면 `start_login()`은 앱 인증 복구를 안내합니다. Codex는 앱에서 수강 강좌의 주차학습을 열어 새 링크를 얻고 `restore_learningx_session(launch_url)`에 전달합니다. 링크로 독립된 Canvas 세션을 만든 뒤, 학교가 제공한 주차학습 LTI 인증 양식을 제출하여 `xn_api_token`을 받습니다. 기존 강좌·자료 API가 모두 성공한 경우에만 인증 쿠키를 원자적으로 저장합니다. 실패 시 기존 세션은 유지하며 인증 URL을 오류에 출력하지 않습니다. 링크와 토큰을 답변·로그·파일에 남기지 마세요.

LearningX 복구 후 `auth_status`를 확인하고 `list_courses`, `list_materials`, `stage_material` 순서로 사용합니다. 앱이 없거나 앱 인증도 실패하면 `start_login(method="browser")`로 기존 Chrome 로그인 창을 엽니다. `stage_material`의 임시 경로를 Google Drive `upload_file`에 전달하고 업로드를 확인한 뒤 `delete_staged_material`로 지웁니다. 앱 조작은 Codex의 `auth-recovery` 스킬이 담당하며, MCP 서버가 혼자 앱 화면을 자동 조작하는 것은 아닙니다. 데스크톱 앱에 접근할 수 없는 실행에서는 사용자 로그인이 필요할 수 있습니다.

2026년 2학기 기본 `term_id`는 50입니다. 자료는 LMS에서 열린 파일만 표시됩니다. 파일 한 개당 100MB로 제한합니다.

## 강의 영상 대본과 요약 (0.2)

`lecture_transcript(content_id)`는 Commons 영상의 실제 메타데이터를 확인한 뒤 백그라운드에서 한국어 음성을 인식합니다. 같은 ID를 다시 호출하면 처리 상태 또는 시간표시 대본을 반환합니다. `retry_lecture_transcript`는 실패한 작업만 재시작합니다. 초기 모델 다운로드 이후 로컬 CPU로 처리하며, 영상은 최대 3시간/1GB까지만 임시로 보관하고 성공·실패 후 삭제합니다. 대본은 Application Support의 transcripts에 재사용 캐시로 보관됩니다. 출석/진도 API에는 요청하지 않습니다.

Codex `lecture-summary` 스킬이 전체 대본과 강의록을 근거로 요약합니다. 음성 인식 전문용어·수식 오류가 있을 수 있으므로 원문 시간 구간을 함께 제공합니다. 여러 영상은 순차 처리합니다.

## 유세인트 및 추가 기능

설치된 `facility-reservation` 스킬은 로그인된 유세인트 화면에서 예약 현황 조회, 신청 준비, 사용자 지시에 따른 제출과 진행현황 확인을 안내합니다. 시설 예약 MCP HTTP API가 추가된 것은 아닙니다. 2026-10-07 일반 Chrome 기본 접근성 조작으로 건물·강의실 선택과 조회를 검증했습니다. 내장 브라우저의 SAP 중첩 iframe 조작 오류는 일반 Chrome에서 정상 포털 메뉴로 다시 접근해 처리합니다. '예약가능' 셀보다 별도의 공휴일·사용 제한 안내를 우선합니다. 실제 제출·승인은 아직 검증하지 않았습니다.

2026-10-07 전사 검증에서 Commons가 반환한 `ssu-toast.commonscdn.com/contents31/ssu1000001/` 경로를 기존 CDN 허용 목록에 추가했습니다. 이 CDN은 Commons Referer와 User-Agent가 없는 다운로드를 HTTP 403으로 거부하므로 해당 헤더를 포함합니다. HTTPS, 호스트·경로 제한과 1GB 한도는 유지합니다.

`study-briefing`은 로그인된 LMS 화면의 미완료 강의·과제·퀴즈와 가까운 마감을 정리합니다. 자료 Drive 동기화는 기존 weekly-sync를 사용합니다. `auth_status`와 로그인 저장은 실제 학교 API로 검증하며, 학교 측 만료를 우회하지 않습니다.

## Codex 플러그인 업데이트

이 저장소는 `plugins/ssu-lms` 플러그인을 포함한 GitHub 마켓플레이스입니다. 최초 연결은 `codex plugin marketplace add ksneoun-gif/ssu-lms-mac --ref main`으로 합니다. GitHub에 변경을 올린 뒤 `codex plugin marketplace upgrade ssu-lms-github`와 `codex plugin add ssu-lms@ssu-lms-github`를 실행하고 Codex를 다시 시작해 설치본을 갱신합니다. GitHub에 push하는 것만으로 로컬 Codex가 즉시 바뀌지는 않습니다. MCP 서버 코드는 갱신된 마켓플레이스 체크아웃에서 실행하며 Python 가상환경은 `~/Downloads/ssu-lms-download-mcp/.venv`를 사용합니다.

## 0.2.7 사용 장애 수정

- `list_weekly_content(course_id)`는 주차별 영상·퀴즈 항목과 빈 주차를 구분합니다. `list_materials`는 파일만 반환합니다. 실제 Commons iframe 확인은 여전히 필요합니다.
- `auth_status`는 학교 API HTTP 상태를 토큰/URL 없이 반환합니다. HTTP 400은 토큰 만료의 확정 증거가 아닙니다.
- 관찰된 contents15/contents29 영상 경로를 지원하고, 잘못된 포트·경로 이탈 주소는 거부합니다.
- 전사 시작 실패는 재시도 가능한 실패 상태로 기록하고, 임시 상태 파일은 고유 이름으로 원자적으로 교체합니다. 영상 HTTP 오류의 인증 URL은 반환하지 않습니다.
- 자료 파일명은 NFC로 정규화합니다. Drive 업로드 후 name/parents/size를 확인한 다음 임시 파일을 삭제하세요.

제한: 학교 세션이 만료되면 앱/브라우저 복구가 필요합니다. 퀴즈 실제 문항·시설 예약은 로그인된 UI에서 확인합니다. 컴퓨터가 꺼진 상태의 자동화, 동시 전사 실행 제어, 자동 전사 정확도 보장은 제공하지 않습니다.


## 0.3.0 Windows/macOS 실행

Node.js와 64비트 Python 3.10~3.13이 필요합니다. Python 실행 별칭을 제외하고 실제 설치본을 찾습니다. 서버 코드는 플러그인 안에 포함하며 MCP 설정은 `${CODEX_PLUGIN_ROOT}/launch.cjs`를 사용합니다. 기존 Mac 자료·영상 API와 보안 검사는 유지합니다.

저장소를 내려받은 폴더에서 최초 1회 실행하세요.

```sh
node plugins/ssu-lms/launch.cjs --setup --check
```

`SSU_LMS_PYTHON`으로 Python 실행 파일, `SSU_LMS_ENV`로 기존 가상환경을 지정할 수 있습니다. 의존성 설치는 `--setup` 때만 실행합니다. 일반 MCP 시작 중에는 인터넷 설치를 하지 않습니다. 설치 후 `--check`의 `ready:true`를 확인하세요. Windows에서는 설치된 Chrome/Edge를 사용하며 `SSU_LMS_BROWSER=msedge`로 Edge를 선택할 수 있습니다.

```sh
codex plugin marketplace add ksneoun-gif/ssu-lms-mac --ref main
codex plugin marketplace upgrade ssu-lms-github
codex plugin add ssu-lms@ssu-lms-github
```

이미 마켓플레이스가 등록되어 있다면 첫 줄을 생략하세요. Codex를 다시 시작하고 플러그인을 선택하세요. 로그인 창은 독립 프로필을 사용하므로 다른 Chrome/Edge 창의 로그인과 공유되지 않습니다. `auth_status`의 실제 학교 API 검증 성공 후에만 로그인 성공으로 판정하세요.

Windows에서 PID 존재 확인에 `os.kill(pid,0)`을 사용하지 않고 Win32 프로세스 조회를 사용합니다. 로그인 시작은 제한 시간과 실패 상태를 반환하며, 한글 파일·캐시는 UTF-8로 처리합니다. `test_server.py`, `test_learningx.py`, `test_windows.py`, `test_login.py`, `test_mcp.py`로 회귀검사를 실행할 수 있습니다.

시설 예약은 로그인된 브라우저 UI를 사용하는 스킬이며 독립 예약 HTTP 도구가 아닙니다. Drive 동기화는 연결된 Drive 도구가 필요합니다. 강의 전사는 최초 Whisper 모델 다운로드가 필요합니다. 학교 로그인·실제 자료 다운로드·영상 전사는 해당 계정과 네트워크에서 별도로 검증해야 합니다.

2026-10-17 Windows 검증: 서버 11개, 인증 복구 8개, 로그인 7개, 패키지 4개 검사 및 Windows PID/UTF-8 검사를 통과했습니다. MCP 실행 준비는 ready:true입니다. 이 작업의 제한 실행 환경에서는 Python asyncio 내부 socketpair 생성이 대기하여 실제 stdio 연결은 검증하지 못했습니다. 현재 저장된 학교 세션도 없어 과목 조회·자료 다운로드·실제 전사는 미검증입니다.

2026-10-17 Windows 검증: 서버 11개, 인증 복구 8개, 로그인 7개, 패키지 4개 검사 및 Windows PID/UTF-8 검사를 통과했습니다. MCP 실행 준비는 ready:true입니다. 이 작업의 제한 실행 환경에서는 Python asyncio 내부 socketpair 생성이 대기하여 실제 stdio 연결은 검증하지 못했습니다. 현재 저장된 학교 세션도 없어 과목 조회·자료 다운로드·실제 전사는 미검증입니다.

## 0.3.1 Windows setup and connection diagnosis

On Windows, Node is no longer required for setup or normal MCP operation after configuring the plugin. Run this in ordinary PowerShell from the downloaded repository:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start.ps1 -Setup -Configure
```

For an installed plugin, run its own `start.ps1` from the plugin folder. Setup finds a real Python executable, checks dependencies, then writes both `.mcp.json` and `mcp.json` with the resolved Python and server paths. Existing configurations are backed up once. `start.ps1 -Check` does not write configuration. `ready:true` only confirms dependencies, not school authentication or MCP communication. Local absolute paths are generated on the user's PC; do not commit the configured manifests back to GitHub. Reinstalling/upgrading a cached plugin can replace local configuration; configure the newly installed version again.

`verify_local.py` checks the actual stdio handshake, live school authentication, course/material lists and one temporary download/cleanup. It updates both launch configurations only after these checks pass. It finds the installed version automatically, or accepts `--plugin-root`. It does not start speech transcription without a selected lecture.

A native stdio server showing `auth_status:unsupported` in `codex mcp list --json` means MCP OAuth is not supported; it is not evidence of failed LMS authentication. If direct MCP verification succeeds but a running conversation has no LMS tools, first check the effective server configuration and the tool list exposed to that conversation. A restart alone is not proof of tool availability. A cloud execution environment cannot use a Windows-local stdio server or its local session.

## 0.3.2 Material resolution and transcript review

- File-list `size_bytes` is null until downloaded. The school's unverified number is preserved as `reported_size_bytes`; `stage_material` returns actual `bytes` and `size_verified: true`.
- Missing LearningX content metadata is reported as `available: null` with a reason, rather than incorrectly claiming a file is closed.
- Canvas-native File module items are resolved through the standard, paginated Canvas module and file APIs. Existing account access and HTTPS host restrictions remain required. External storage redirects are refused; denied or incomplete lookups are exposed through `diagnose_materials(course_id)`. A missing LearningX ID is not proof that a file is private.
- New ASR jobs include per-segment average log probability and no-speech probability, with the verified content title as context. Raw wording is preserved. New and cached transcripts are marked unreviewed; confidence is not proof that a formula or word is correct.
- `auth_status` exposes `server_version`. `verify_local.py` rejects an old server and diagnoses empty material lists.
- On Windows run `powershell.exe -NoProfile -File .\reconnect_windows.ps1` from this repository, then restart Codex. It upgrades the existing marketplace, installs 0.3.2, uses the existing setup helper, and runs live MCP checks. It stops on failure and preserves session/transcript data.

Validation: 9 new material/ASR regressions, 11 existing server checks, 8 LearningX tests, 7 login tests, and Windows process/UTF-8 checks passed. Native Canvas access for a particular school account still requires live verification after installing; this release does not claim that inaccessible school files have become available.

## 0.3.4 세션 자동 유지(Keep-Alive) 및 무인 자동 갱신(Silent Refresh)

- **세션 유휴 만료 방지 (Keep-Alive)**: 서버 실행 중 백그라운드 스레드가 10분마다 학교 LMS API에 가벼운 핑을 보내 세션 수명을 계속 연장합니다. 학교 서버가 내려주는 신규 쿠키도 실시간으로 `session.json`에 반영됩니다.
- **무인 백그라운드 재로그인 (Silent Auto-Refresh)**: 절전 모드 복귀 등으로 세션이 만료된 경우에도, Chrome 프로필에 저장된 정보를 바탕으로 Headless 브라우저가 백그라운드에서 자동으로 재로그인하여 새 세션을 캡처합니다. 대화형 브라우저 창을 띄워 매번 수동으로 로그인할 필요가 없습니다.
- **신규 MCP 도구**:
  - `keep_alive_session`: 즉시 세션 유지 핑을 수행하고 상태를 갱신합니다.
  - `refresh_session`: 백그라운드 무인 세션 갱신을 수행합니다.
  - `keep_alive_status_check`: 현재 keep-alive 상태와 마지막 핑 시각을 조회합니다.
- **macOS 백그라운드 데몬(LaunchAgent) 지원**:
  ```sh
  python keep_alive.py --install-agent
  ```
  맥이 켜져 있는 동안 백그라운드에서 24시간 세션을 상시 유지합니다.

