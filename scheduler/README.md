# 예약 대행 (Cloudflare Worker)

GitHub 의 `schedule` 이 이 저장소에서 하루 1~6회밖에 뜨지 않아(기대 24회),
정시 실행 주체를 밖으로 옮겼다. Worker 가 cron 마다 `workflow_dispatch` 를 호출한다.

가동 첫날(2026-09-02) 실측: obs-hourly **20/20 발동, 오차 초 단위**.
저장소의 `cron:` 은 지우지 않되 **하루 1회로 줄여** 심장박동으로만 남겼다
(obs-hourly 21:25 KST, daily 10:40 KST). 매시로 두면 하루 5회쯤 중복 실행돼
기상청 API 를 헛되이 두들기고 대기열 충돌로 취소까지 유발했다.
Worker 가 죽어도 사이트가 완전히 멎지는 않게 하는 것이 이 잔여 cron 의 유일한 목적이다.

## 설정 (최초 1회)

### 1. GitHub 토큰 발급
Settings → Developer settings → **Fine-grained personal access tokens** → Generate new token

| 항목 | 값 |
|---|---|
| Repository access | **Only select repositories** → `nwp-verify` |
| Permissions → Actions | **Read and write** |
| Permissions → 그 외 | 전부 손대지 않음 |
| Expiration | 최대 1년 |

`contents` 권한은 주지 않는다. 그것까지 있으면 유출 시 워크플로를 고쳐 비밀값을
빼낼 수 있다. Actions 권한만으로는 실행만 가능하고 코드·비밀값은 안전하다.

### 2. Worker 생성
dash.cloudflare.com → Workers & Pages → Create → Worker
이름 `nwp-verify-scheduler` → 배포 후 **Edit code** 에 `worker.js` 내용을 붙여넣고 배포.

### 3. 비밀값 등록
Worker → Settings → Variables and Secrets → **Add (type: Secret)**

- `GH_TOKEN` = 1번에서 받은 토큰
- `TEST_KEY` = (선택) 아무 문자열. 넣으면 브라우저로 수동 시험 가능

### 4. Cron 등록
Worker → Settings → Triggers → Cron Triggers → Add

```
25 * * * *     (매시 :25  — obs-hourly)
10 21 * * *    (06:10 KST — daily)
40 1 * * *     (10:40 KST — daily)
```

`wrangler.toml` 의 `crons` 와 **문자열이 정확히 같아야** 한다.
worker.js 가 cron 식을 그대로 키로 써서 워크플로를 고르기 때문이다.

## 확인

```
https://nwp-verify-scheduler.<계정>.workers.dev/            → "alive"
https://nwp-verify-scheduler.<계정>.workers.dev/?wf=obs-hourly.yml&key=<TEST_KEY>
```

정상이면 `obs-hourly.yml -> 204`. 실패 코드의 뜻:

| 코드 | 원인 |
|---|---|
| 401 | 토큰 만료 또는 오타 |
| 403 | Actions 권한이 Read and write 가 아님 |
| 404 | 저장소 이름 또는 워크플로 파일명 |

실행 기록은 Worker → Logs, 또는 저장소 Actions 탭에서 `workflow_dispatch` 로 확인.

## 남용 방지

토큰이 유출되어도 피해가 제한되도록 `obs-hourly.yml` 에 `gate` 잡을 두었다.
`workflow_dispatch` 로 온 요청은 직전 실행이 **20분 이내면 건너뛴다**(skipped 로 표시).
정상 운영(매시 1회)에는 걸리지 않는다. 급히 다시 돌려야 하면 수동 실행 시
`force` 입력을 켜거나 `gh workflow run obs-hourly.yml -f force=true`.

## 유일한 실패 모드: 토큰 만료

만료되면 Worker 는 계속 돌지만 GitHub 가 401 로 거절해 **사이트가 조용히 멈춘다**.
갱신일은 구글 캘린더에 등록해 두었다. 사이트가 "N시간 전" 을 표시하므로
눈으로도 잡히지만, 캘린더가 1차 방어다.

## 에너지기상 발행 복구 (2026-11-19)

기존 관측·NWP 예약을 유지하면서 에너지기상 작업만 별도로 추가:

- `10 22,23 * * *` UTC = **07:10 / 08:10 KST**: 07:10 최초 발행 확인, 08:10 최종 점검·미발행 경고·재시도 (트리거 한 개).
- `40 22 * * *` UTC = **07:40 KST**: 실제 보고서 JSON 확인 후 미게시·실패 시 재시도.

공개된 `energy/YYYYMMDD/report.json`의 **해당 날짜·9일 보고서·10일 예보 구조**를 확인한다. 25분 이내 진행 중인 GitHub 실행이 있으면 중복 호출하지 않는다. 확인 API 장애 시에는 실패를 성공으로 간주하지 않고 재시도 호출한다. 기존 GitHub `energy-daily.yml` 자체 schedule은 예비 경로로 유지한다.

`energy_runtime/energy_data.py`는 관측 원본을 최대 3회 재조회하고 필요한 경우 00–02:59, 03–04:59, 05–07시로 분할 재조회한다. 유효한 실측만 결합하며 임의 보간/대체 관측소 사용 금지. 실측 최소 400/421분, 시작 00:05 이전, 종료 06:50 이후, 최대 연속 누락 10분을 모두 만족할 때만 부분자료를 허용한다. 미충족 시 발행을 차단하고 로그에 수신 수와 최대 결측 길이를 남긴다. 이미 발행된 당일 보고서는 늦게 발생한 재실행이 덮어쓰지 않는다.

**중요:** GitHub 소스 업데이트만으로 Cloudflare Worker가 자동 배포되지 않는다. 배포 시 기존 이미지 경로와 `GH_TOKEN`, `TEST_KEY`, `IMAGERY_LIMITER`가 유지되도록 `scheduler/` 기준 `npx wrangler deploy`를 실행하거나 Cloudflare 대시보드에 `worker.bundle.js`를 반영하고, 에너지기상 2개 Cron Trigger가 추가됐는지 확인한다. Wrangler 배포는 cron 전체 목록을 동기화하므로 기존 3개 트리거가 반드시 함께 있어야 한다.

### GitHub에서 Worker 배포 (모바일에서도 가능)

[GitHub Actions secrets](https://github.com/futurist38/nwp-verify/settings/secrets/actions)에 `CLOUDFLARE_API_TOKEN`(Workers Scripts Edit 권한)과 `CLOUDFLARE_ACCOUNT_ID`를 비밀값으로 등록한 뒤 [deploy-scheduler 워크플로](https://github.com/futurist38/nwp-verify/actions/workflows/deploy-scheduler.yml)를 수동 실행한다. 이 워크플로는 테스트 후 `scheduler/wrangler.toml`의 기존 세 개와 에너지기상 세 개, 총 다섯 개의 Cron Trigger를 함께 배포한다. `GH_TOKEN`, `TEST_KEY`는 기존 Worker secrets로 계속 유지한다. 배포 성공 여부는 이 워크플로의 로그와 Cloudflare Cron Triggers 화면에서 확인한다.

### Cloudflare Workers Free 5-Cron 한도 대응 (2026-11-20)

Cloudflare Workers Free는 계정당 Cron Trigger 최대 5개다. 기존 3개 + 에너지 3개 = 6개로 배포하면 Worker 코드만 교체되고 Cron 갱신은 실패할 수 있다. 따라서 에너지 07:10과 08:10을 하나의 Cron(`10 22,23 * * *`)으로 합쳐 5개로 운영한다. 07:40은 별도 Cron(`40 22 * * *`). 별도 유료 업그레이드 불필요. **전체 5개**가 Wrangler에서 동기화되므로 수동으로 기존 트리거를 삭제하지 않는다.

배포 시 Dashboard에서 켜 둔 Worker Logs가 꺼지지 않도록 `[observability] enabled = true`를 명시한다. Deploy 결과가 `Deployed ... triggers`여도 최종 단계가 실패하면 Cron 설정이 완전히 반영됐다고 보지 않는다. GitHub Action의 전체 성공과 Cloudflare 대시보드의 5개 트리거를 함께 확인한다.
