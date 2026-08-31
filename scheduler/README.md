# 예약 대행 (Cloudflare Worker)

GitHub 의 `schedule` 이 이 저장소에서 하루 1~6회밖에 뜨지 않아(기대 24회),
정시 실행 주체를 밖으로 옮겼다. Worker 가 cron 마다 `workflow_dispatch` 를 호출한다.
저장소의 `cron:` 설정은 지우지 않고 보조로 남겨 두었다.

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
