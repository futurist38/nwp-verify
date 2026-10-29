# 에너지기상 최신 영상 수신 서비스 — 연결 대기

현재 상태: 서버 및 버튼 코드 준비, 모의 요청 테스트 통과. **Cloudflare 미배포, 실시간 기상청 연결 및 화면 통합 미검증.**
`site/energy-weather.html`의 `energy-imagery-endpoint`가 비어 있으면 버튼을 숨긴다.
기존 예약 실행 서버와 별도 Worker로 배포하여 일일 생성에 영향을 주지 않는다.

## 배포

Cloudflare에 로그인한 관리 환경에서 이 폴더를 기준으로 실행한다.

```
npx wrangler deploy
npx wrangler secret put KMA_AUTH_KEY
```

기상청 키는 비밀값 입력 프롬프트에 입력한다. 코드, GitHub 파일, 채팅, 명령행 인자에 넣지 않는다.
`wrangler.toml`의 `IMAGERY_LIMITER`도 함께 생성해야 한다. 계정에서 namespace 1001을 이미 사용한다면 고유한 숫자로 변경한다.

배포 후 실제 Worker URL로 아래 두 경로를 호출하여 원본과 관측 시각을 확인한다.
요청 Origin은 `https://futurist38.github.io`이다.

- `/latest/satellite`: 주야간 합성 RGB, 한반도
- `/latest/radar`: HSR, 한반도 지도 및 mm/h 범례

응답은 PNG data URI, 영상 종류, 실제 프레임 시각만 포함한다. 공개된 프레임 목록의 최근 1시간 이내 시각만 사용한다. 기상청 원격 접속 실패나 PNG 검증 실패는 502를 반환한다.
실영상 확인 후 `site/energy-weather.html`의 `energy-imagery-endpoint` content에 Worker HTTPS 주소를 넣고, main/site-data 양쪽 프런트엔드를 배포한다.

## 사용 동작

오늘 자료에서만 최신 영상 버튼을 활성화한다. 영상별 실패는 기존 그림을 보존하고 성공한 영상만 교체한다. 예보 수치, 지도 아이콘, 경계선은 보존한다. 이미지 전체 비율을 유지하여 기존 패널에 배치한다. 기존 날짜별 브라우저 저장과 편집본 PNG 내보내기를 사용한다.

## 보호와 한계

키는 Worker secret에만 저장한다. 임의 URL·시각·상품 입력을 받지 않는다. 응답/오류에 인증 URL이나 키를 넣지 않는다. HTTPS 고정 호스트 및 리다이렉트 거부, 응답 크기 제한, 타임아웃, PNG 헤더/크기 검사를 적용한다.

Origin 검사는 인증 수단이 아니다. 서버에서 IP별 요청 제한, 지점별 상품 요청 제한, 60초 캐시 및 동일 프로세스 중복 요청 합치기를 추가한다. Cloudflare 제한과 캐시는 지점별이므로 전 세계 총량을 엄격히 보장하지 않는다. 공개 배포 시 계정 한도/기상청 이용량을 확인한다. 악의적인 분산 호출까지 방지해야 하면 사용자 인증 또는 전역 요청 예산을 추가해야 한다.

## 검증

```
node --test worker.test.mjs
node --check ../site/energy-weather.js
```

모의 테스트는 허용 경로, Origin/메서드 거부, 비밀값 누락 시 중단, 요청 제한, 캐시, 프레임 시각, 오류 응답의 비밀값 비노출을 검증한다. 실배포 후 최신 위성/레이더 로딩, 기존 편집 유지, 실패 시 보존, 날짜 전환 도중 응답 무시, 브라우저 저장과 PNG를 추가 확인해야 한다.

참고: https://developers.cloudflare.com/workers/configuration/secrets/
https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/
https://developers.cloudflare.com/workers/runtime-apis/cache/
