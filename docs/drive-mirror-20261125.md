# Gemini용 브리핑 Markdown 사본

`drive-mirror`는 main의 `obs-hourly` 또는 `daily-nwp` 실행이 끝나면 `site-data:briefing/latest.md`를 읽어 Google Drive의 고정 파일 하나를 갱신한다. 일부 자료를 이미 발행한 뒤 수집 작업이 실패할 수 있어 실패 종료 때도 최신 발행본을 확인한다. 내용이 같으면 업로드를 생략한다. 파일 주소와 공유 권한은 계속 유지된다.

## 최초 설정

1. Gemini에서 사용할 Google 계정의 내 드라이브에 `nwp-briefing-최신.md`를 한 번 업로드한다. 이미 첫 사본이 있으면 그 파일을 사용한다. 파일의 '링크 복사' 주소에서 `/d/` 다음 문자열이 파일 ID다.
2. [Google Cloud 콘솔](https://console.cloud.google.com/apis/library/drive.googleapis.com)에서 자동화에 사용할 프로젝트를 선택하고 Google Drive API를 사용 설정한다. [서비스 계정](https://console.cloud.google.com/iam-admin/serviceaccounts)에서 해당 계정을 선택하거나 만든다. 개별 파일 접근은 Drive에서 부여한다.
3. Drive 파일의 공유 메뉴에서 서비스 계정의 `…@….iam.gserviceaccount.com` 주소에 편집자 권한을 준다.
4. [저장소의 Actions 설정](https://github.com/futurist38/nwp-verify/settings/secrets/actions)에 두 값을 등록한다.
   - **Secrets**의 `GDRIVE_SA_JSON`에 서비스 계정 키 JSON 전체를 넣는다. 키는 서비스 계정의 **키 → 키 추가 → 새 키 만들기 → JSON**에서 발급할 수 있다.
   - **Variables**의 `GDRIVE_FILE_ID`에 1단계의 파일 ID를 넣는다. 같은 이름의 Secret도 지원한다. 둘 다 있으면 Variable을 사용한다.
5. [drive-mirror 실행 화면](https://github.com/futurist38/nwp-verify/actions/workflows/drive-mirror.yml)에서 **Run workflow → main**을 선택한다. 로그에서 `[drive] 갱신 완료`와 `text/markdown`을 확인한다. 다시 실행했을 때 원본이 같으면 `[drive] 변경 없음`이 정상이다. `미설정`은 업로드를 건너뛴 결과다.

## Gemini에서 읽기

Gemini의 **파일 추가 → Drive에서 추가**에서 `nwp-briefing-최신.md`를 선택한다. 새 브리핑을 요청할 때는 해당 시점의 Drive 파일을 다시 첨부한다. Drive 연결에 필요한 설정은 [Gemini 도움말](https://support.google.com/gemini/answer/14903178?hl=ko)에서 확인할 수 있다.

> 첨부한 브리핑에서 원본 생성 시각(KST)과 모델별 발표 시각을 먼저 알려줘. 생성 후 2시간 이상 지났으면 구자료임을 밝혀줘. 기상청 예보와 모델 전망을 구분해서 전력수요 브리핑을 작성해줘.

사본 첫 줄에는 시간별 원본 주소와 사본 갱신 시각이 있다. 신선도 판단 기준은 그 아래 본문의 **생성 시각**이다. Markdown 표와 한글 본문은 UTF-8로 보존된다. HTTP 404가 뜨면 파일 ID와 공유 대상을, 403이 뜨면 서비스 계정 편집 권한과 해당 프로젝트의 Drive API 사용 설정을 확인한다.
