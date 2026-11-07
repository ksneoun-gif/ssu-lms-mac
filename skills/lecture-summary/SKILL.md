---
name: lecture-summary
description: Summarize Soongsil LMS lecture videos using verified timestamped speech transcripts and lecture notes.
---
# 강의 영상 요약
1. 사용자의 과목과 주차를 확인한다. 로그인된 LMS 브라우저의 마이페이지 → 과목 → 강의콘텐츠에서 영상 제목과 주차를 읽는다. 이미 로그인된 브라우저를 우선 사용한다. 로컬 MCP 세션과 브라우저 로그인은 별개다.
2. `list_weekly_content(course_id)`로 파일 이외의 영상·퀴즈와 빈 주차를 먼저 구분한다. `list_materials`가 비었다는 이유로 재로그인하거나 영상이 없다고 결론 내리지 않는다. API 콘텐츠 ID만으로 Commons 영상 ID라고 단정하지 않는다. 영상 iframe의 실제 Commons `/em/{content_id}` 주소를 DOM에서 확인한다. 추측한 ID를 사용하지 않는다. 재생 및 진도 기록 요청을 보내지 않는다.
3. `lecture_transcript(content_id)`를 호출한다. 작업은 백그라운드에서 로컬 음성 인식을 수행한다. `processing`이면 단계와 진행 시간을 알리고, 완료될 때 조회한다. 중단/실패는 `retry_lecture_transcript`로 재시도한다. 반복 호출은 기존 완료 대본을 재사용한다.
4. `complete`의 segments를 읽고 한국어로 핵심 개념, 설명 흐름, 사례, 복습 질문을 요약한다. 각 주요 주장에 영상 시간 구간을 붙인다. 강의록이 제공되면 전문용어·수식을 대조한다. 음성 인식 오류와 원문에 없는 추론을 구분한다. 제목만으로 내용을 만들어내거나 부분 대본을 전체 요약이라고 표현하지 않는다.
5. 영상은 처리 후 삭제된다. 대본은 사용자 로컬 Application Support에 재사용 캐시로 남는다. Drive 저장을 요청한 경우 기존 숭실대 / 3-2 / 과목 / 주차 폴더에 요약을 저장하고 결과를 확인한다.
6. MCP 인증이 실패하면 같은 플러그인의 `auth-recovery/SKILL.md`에 따라 LearningX로 먼저 복구하고 다시 검증한다. 앱 인증도 실패하면 브라우저 로그인이 필요하다. 최초 로그인으로 영구 인증을 보장하지 않는다.

## 전사 요청은 저장 검증까지 한 작업으로 수행
- 전사/강의록 요청은 요약 요청과 구분한다. 전사는 요약으로 대체하지 않고 전체 TXT를 저장한다.
- 먼저 auth_status와 실제 강좌·주차 조회로 인증과 영상 ID를 검증한다. 기존 Drive 숭실대 / 3-2 / 과목 / 주차 폴더를 찾는다. 폴더를 임의로 새로 만들지 않는다.
- lecture_transcript로 시작한 뒤 processing이면 wait_lecture_transcript(content_id, timeout_seconds=45)를 반복한다. 응답마다 phase, processed_seconds/duration_seconds, progress_percent와 마지막 갱신 시각을 가능한 범위에서 사용자에게 알린다. 다운로드·모델 로딩처럼 분모를 모르는 단계는 퍼센트를 지어내지 않는다.
- processing 응답을 받고 최종 답변으로 턴을 종료하지 않는다. 진행 확인을 사용자에게 다시 요청하지 않는다. failed이면 원인을 확인하고 retry_lecture_transcript로 재시도한다. 반복 실패는 오류를 보고하고 완료로 표시하지 않는다.
- complete이면 즉시 stage_lecture_transcript(content_id, course_name, week, lecture_name)를 호출한다. course_name과 lecture_name은 실제 LMS 조회값을 사용한다. 출력 filename은 NFC 정규화된 과목명_주차_강의이름_전사.txt다.
- 해당 Drive 주차 폴더를 조회하고 NFC 파일명으로 중복을 확인한다. 파일명이 같아도 비어 있거나 크기가 다르면 저장 완료라고 단정하지 말고 기존 내용을 확인한다. Google Drive 도구로 local_path의 TXT를 filename으로 업로드한다. 업로드 후 메타데이터를 다시 조회해 name, parents, size가 맞는지 검증한다.
- 검증 성공 후에만 delete_staged_material(staging_id)로 임시 TXT를 삭제하고 Drive 링크와 함께 완료를 보고한다. 실패하면 TXT를 보존하고 업로드를 재시도한다. staged 또는 complete는 Drive 저장 완료를 뜻하지 않는다.
- 서버는 Drive 연결 인증을 소유하지 않는다. 업로드는 호스트의 Google Drive 도구가 수행한다. 대화가 종료되면 독립 업로드나 알림을 보장하지 않는다. 도구 접근 불가·실행 제한 등 실제 차단이 있으면 남은 항목을 명시한다.
