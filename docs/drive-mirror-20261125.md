# 브리핑 묶음 드라이브 사본 (2026-11-25)

## 왜

`briefing/YYYYMMDDHH.md` 는 셸(curl)이 있는 AI(Claude)만 직접 읽는다. Gemini 앱처럼 URL 을
못 읽는 AI 는 구글 드라이브 파일만 불러올 수 있으므로, 발행 직후 같은 내용을 드라이브의
**고정 파일 하나**에 덮어쓴다.

## 동작

- `.github/workflows/drive-mirror.yml` — `obs-hourly`·`daily-nwp` 가 끝나면(`workflow_run`) 실행.
  발행 파이프라인은 건드리지 않으며, 여기가 실패해도 사이트 발행과 무관하다.
- `site-data` 브랜치의 `briefing/latest.md` 를 읽어 `tools/drive_mirror.py` 가 드라이브 파일
  내용을 교체한다. 파일 ID 는 그대로라 AI 는 늘 같은 파일을 연다.
- 맨 위에 머리말 두 줄을 붙인다: 원본 정시 주소, 사본 갱신 시각, "생성 시각이 2시간 이상
  이르면 구자료로 취급" 안내.
- 원본 본문 해시를 파일의 `appProperties.src_sha` 에 적어 두고, 내용이 같으면 올리지 않는다.
- 비밀값이 없으면 notice 만 남기고 성공 종료 — 설정 전에 머지해도 안전하다.

## 설정 (한 번)

1. **Google Cloud**: 프로젝트 하나(기존 것도 됨)에서 *Google Drive API* 사용 설정.
2. **서비스 계정** 생성 → 키(JSON) 발급. 역할(IAM)은 필요 없다.
3. **드라이브에서 대상 파일을 직접 만든다** — 권장: 빈 **구글 문서** `nwp-briefing-최신`.
   서비스 계정은 개인 드라이브에 새 파일을 소유할 수 없으므로 반드시 사람이 만든 파일이어야 한다.
4. 그 파일을 서비스 계정 이메일(`…@….iam.gserviceaccount.com`)에 **편집자**로 공유.
5. 파일 ID 확인: 문서 주소 `https://docs.google.com/document/d/<여기>/edit`.
6. GitHub 저장소 설정:
   - Secret `GDRIVE_SA_JSON` = 키 JSON 원문 전체
   - Variable `GDRIVE_FILE_ID` = 파일 ID (Secret 으로 넣어도 된다)
7. Actions → drive-mirror → **Run workflow** 로 한 번 수동 실행해 확인.
   로그에 `[drive] 갱신 완료 — … (구글 문서)` 가 나오고 문서 본문이 채워지면 끝.

## 확인할 점

- 구글 문서 대상은 text/plain 업로드가 본문으로 변환된다. 표(마크다운 `|`)는 글자 그대로 남는다
  — AI 판독에는 문제없다. 변환이 기대와 다르면 대상 파일을 `.txt` 로 바꿔도 같은 코드로 동작한다.
- 오류 문구: 404 = 파일 ID 또는 편집자 공유 누락 / 403 = 공유 권한 또는 Drive API 미사용.
- 드라이브 파일의 버전 기록이 매시 쌓인다(드라이브가 오래된 버전을 자동 정리).

## AI 쪽 사용

Gemini 에서는 드라이브 연결 후 `@Google Drive nwp-briefing-최신` 처럼 파일을 지정해 읽게 한다.
첫 줄 머리말의 '생성' 시각을 먼저 확인하게 하고, 2시간 이상 지났으면 구자료임을 밝히게 한다.
