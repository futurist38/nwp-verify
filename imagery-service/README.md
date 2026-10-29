# 에너지기상 수동 영상 갱신

기존 `nwp-verify-scheduler` Worker에 `/latest/satellite`, `/latest/radar`를 추가한다. 새 서버와 새 기상청 인증키는 필요하지 않다. 예약 실행과 보호된 수동 dispatch 경로는 유지한다.

## 배포 상태

소스 및 모의 테스트 준비. Cloudflare 운영 배포와 브라우저 실영상·PNG 확인 전에는 `site/energy-weather.html`의 `energy-imagery-endpoint`를 비워 두고 버튼을 숨긴다. GitHub에 코드를 반영하는 것만으로 Cloudflare가 배포되는 것은 아니다.

## 기존 Worker 배포

Cloudflare 인증이 된 환경에서 저장소 `scheduler/` 폴더를 기준으로 `npx wrangler deploy`를 실행한다. 기존 GH_TOKEN 및 TEST_KEY 비밀값을 유지한다. 요청 제한 바인딩 `IMAGERY_LIMITER`를 wrangler.toml대로 등록한다(namespace 1001을 다른 용도로 사용한다면 고유한 숫자로 변경).

대시보드 편집 시 `scheduler/worker.bundle.js`는 모듈 코드를 하나로 합친 동일 구현이다. 예약 cron은 기존대로 유지하며, 요청 제한 바인딩이 없으면 영상 경로는 안전하게 503으로 중단한다.

배포 후 실제 기존 Worker 주소에 Origin `https://futurist38.github.io`로 두 영상 경로를 요청해 200 응답, 영상 시각, 이미지 내용을 확인한다. 그 다음 HTML의 `energy-imagery-endpoint`에 Worker HTTPS 주소를 넣어 main/site-data 프런트엔드를 배포한다. URL에 토큰이나 키를 넣지 않는다.

## 자료

- 위성: 날씨누리 공개 프레임 목록 및 RGB 주야간합성 원본 PNG.
- 레이더: 공개 프레임 목록의 최신 유효시각 + `https://radar.kma.go.kr/cgi-bin/center/nph-rdr_cmp2_img`. HSR, HSO, ECHO, map=HR, legend=1. 2026-10-29 18:25 실제 수신 검증(678×663 PNG, 지도와 mm/h 범례 포함).
- API허브 인증키 및 GitHub 토큰은 영상 수신에 사용하지 않는다.
- 프레임 목록과 이미지가 불일치하거나 수신에 실패하면 다른 최신 프레임 한 번만 시도하고 중단한다. 관측시각을 현재시각으로 대체하지 않는다.

## 화면

오늘 자료에서만 갱신 가능. 위성·레이더는 각각 성공한 것만 교체하며 실패한 패널은 보존한다. 지도 아이콘·경계선·예보는 유지한다. 실제 영상 시각을 표기하고, 편집을 닫아도 갱신 화면을 유지한다. 상단 1페이지 PNG 저장도 갱신·편집 상태를 저장한다. 원본 자동 생성 보고서는 수정하지 않으며 브라우저 저장은 기존 날짜별 저장 버튼을 사용한다.

## 보호 및 검증

고정 공개 호스트/상품만 사용하고 임의 URL, 시간, 쿼리를 거부한다. 타임아웃, 응답 크기 제한, PNG 헤더/크기 검사, 서버 요청 제한, 60초 캐시, 프로세스 내 동시 요청 합치기를 적용한다. Origin은 브라우저 허용 범위이며 인증 수단이 아니다. 제한과 캐시는 Cloudflare 지점별이므로 전 세계 총량에 대한 절대 상한은 아니다.

`node --test imagery-service/*.test.*` — 모의 테스트 13개: 기존 예약 실행, 제한/허용 경로, 인증키 불필요, 중복 수신 억제, 최신 시각, 실패 처리, 기존 편집 유지, 날짜 전환, PNG 내보내기 경로.

`node imagery-service/live-check.mjs` — 비밀값 없이 실제 기상청 접속 확인. Cloudflare 환경에서 수신 성공하는지와 실제 PNG 내보내기는 운영 연결 후 별도 확인한다.
