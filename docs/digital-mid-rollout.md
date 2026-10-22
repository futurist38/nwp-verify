# 디지털 중기예보 전환 준비 (2026-10-22)

## 준비 범위와 현재 상태

기본값은 `digital_mid_config.json`의 `mode: off`이다. 수집 요청은 없고 기존 API·기온 그래프·발표 비교는 그대로 유지한다. 새 데이터는 `verification/digital_mid/revisions/`에 별도 저장하고, 활성화 후 예보 비교 탭 하단의 전용 영역에 표시한다. 기존 지역예보를 도시 격자예보로 조용히 덮어쓰지 않는다.

- `off`: 요청 중지, 새 영역 숨김. 이미 수집한 이력 보존.
- `shadow`: 수집·검증·도시별 추출 및 정정 이력 저장. 화면에는 미반영.
- `active`: 같은 검증을 거친 자료를 표시. 직전 디지털 발표와 기온 변화 비교.

현업 전환 예정은 첨부 2026-10-07 공문 기준 2026-11-12 18시이다. 날짜에 의한 자동 활성화는 없다. 기존 API 종료나 신규 API 제공 시각은 확인되지 않았다.

## 실제 파일 확보 시 진행 순서

1. 공식 제공 경로·이용권한과 NetCDF 샘플을 확보한다. 기관용 자료라면 공개 GitHub Pages에 도시 추출값을 제공할 수 있는지도 자료 제공 조건에서 확인한다.
2. 파일의 변수·좌표·CF 시간·발표시각·단위·결측 처리·TMN/TMX 집계일 및 코드표를 확인한다. 파일명 `HR36`에서 시각을 추측하지 않는다.
3. 아래 profile을 실제 규격에 맞게 채운다. 격자 해석과 통보문 대조가 확인되면 `verified: true`를 지정한다. **합성 테스트의 변수명·코드표를 실자료 설정으로 복사하지 않는다.**
4. mode를 `shadow`로 설정하고 원본 폴더로 시험한다.
   ```bash
   python digital_mid.py --input-dir /path/to/sample --issue 2026111218
   ```
5. 수신 주소를 저장소 Secret `KMA_DIGITAL_MID_URL_TEMPLATE`에, 인증키를 별도 Secret `KMA_DIGITAL_MID_AUTH_KEY`에 등록한다. 템플릿은 `{filename}`, `{element}`, `{issue}`(YYYYMMDDHHmm), `{auth_key}` 치환을 지원한다. 실제 호스트를 config의 `allowed_hosts`에 넣는다. URL과 키는 로그·JSON에 기록하지 않는다.
6. obs-hourly 워크플로가 수집한다. 발표 18시 + 설정된 지연(초기 30분) 후 최신 발표를 선택한다. 기본 180분 재확인 간격은 자료 제공 지연·정정 정책을 실측해 조정한다. 외부 timeout 240초 초과 시 기존 예보는 계속 발행한다.
7. 도시·시간·극값·강수 코드·분위수를 통보문 및 원자료와 대조한다. 가능한 경우 연속 발표 2건 이상과 정정 사례를 확인한다. 검증 완료 후 `mode: active`로 바꾸고 obs-hourly를 실행한다.
8. 문제가 있으면 `mode: off` 또는 `shadow`로 변경하고 사이트를 다시 발행한다. 빌드가 기존에 복원된 active JSON을 빈 목록으로 바꿔 새 영역을 숨긴다.

## profile 규약

`profile.id`: 실제 자료 규격 버전 이름. 구조·해석 변경 시 새 이름 사용.
`profile.timezone`: CF decoded time 및 naive 발표시각의 시간대(`UTC` 또는 `Asia/Seoul`).
`profile.cities`: `{도시명: [위도, 경도]}`. 플랫폼 `config.CITIES`의 좌표를 출발점으로 사용하며 해안·산지 대표성을 확인한다.
`profile.max_distance_km`: 최근접 좌표와 도시 간 최대 허용 거리. 결측 격자는 먼 유효 격자로 대체하지 않는다.
`profile.daily_leads`: 발표일 기준 공식 TMN/TMX 대상일의 정수 오프셋 전체 목록.
`profile.hourly_leads`: 발표시각 기준 TMP/SKY/PTY/RPOS/RVAR의 리드시간 전체 목록. 3h/6h 간격을 지원한다.

`profile.fields`에는 최소 TMP, TMN, TMX, SKY, PTY, RPOS, RVAR를 지정한다. 선택 기온 분위수는 각 기본요소별 10P/25P/75P/90P 4개를 한 묶음으로 지정한다.

각 요소의 필수 mapping:

| 키 | 의미 |
|---|---|
| variable | 파일 내부 실제 변수명 |
| time | decoded datetime이면서 자료 차원인 시간 좌표명 |
| latitude / longitude | 지리적 위경도 좌표명 (서로 다른 축의 1D 또는 동일 차원의 2D) |
| units | 예상 원본 변수 단위 문자열. 다르면 거부 |
| issue_attribute 또는 issue_variable | 발표시각을 읽을 전역 속성 또는 스칼라 변수 |
| date_offset_hours | TMN/TMX 시간좌표를 공식 대상일로 매핑할 시차. 집계 규약 확인 후 필수 지정 |
| scale / offset | 선택 기온 단위변환. CF scale_factor/add_offset은 xarray에서 이미 반영됨. 이중 적용 금지 |

`profile.codes`에는 SKY/PTY/RPOS/RVAR별 `{원시코드 문자열: 공식 표시문구}`를 지정한다. RPOS 원시값을 %로 추측하지 않는다. 예를 들어 공식 규격에서 60이 60%에 해당함이 확인된 경우에만 `"60": "60% · 보통"`으로 설정한다. RVAR는 공식 정의를 따르며 강수량이나 표준편차로 임의 해석하지 않는다.

현재 판독기가 지원하는 형태는 CF datetime + 시간×공간 3차원 + 위경도 좌표가 있는 파일이다. 투영 x/y만 있거나, 숫자 리드타임만 있거나, 발표 메타데이터가 없거나, 추가 레벨 차원이 있으면 추측하지 않고 거부한다. 실제 파일이 이 형태라면 공식 규격에 따른 좌표/시간 변환 어댑터를 추가해야 한다. 실제 파일 확인 전에는 설정만으로 모든 형식에 대응된다고 보장하지 않는다.

## 저장 및 표출

- 원본 NetCDF는 임시 폴더에 받고 처리 후 삭제한다. 도시별 값·profile hash·발표·수신시각·정정 revision만 보존한다.
- 같은 발표의 내용이 달라지면 별도 revision 파일을 남기며 화면에는 가장 나중에 수신된 revision을 사용한다.
- 활성화해도 최신 실자료가 없으면 새 영역에 자료 없음 표시. 이전 발표는 발표시각 및 오래된 자료 안내를 표시한다.
- 기존 ±폭과 새 백분위는 혼합하지 않는다. 기본값을 중앙값으로 간주하지 않는다.
- 공식 TMN/TMX를 사용한다. 3~6시간 TMP의 극값으로 대체하지 않는다.
- 자료 시간축을 그대로 표시하며 임의로 시간별 보간하거나 광역 오전·오후 예보로 요약하지 않는다.
- 지도·전체 격자 장기 저장·기존 브리핑 출력의 자동 교체는 이번 준비 범위에 포함하지 않았다. 첫 실자료 검증 후 필요한 범위로 확장한다.

## 검증

`python -m unittest discover -s tests -p 'test_digital_mid.py'`

합성 NetCDF로 시간대 변환, 공식 일 기온, 코드·결측·영역·시간축·발표일 검증, 백분위 순서, 정정 이력, off/shadow/active 및 롤백을 검사한다. 합성 테스트 통과는 실제 기상청 규격 검증을 대체하지 않는다.
