# Meteogram 표출 백업 — 2026-10-21

사용자 요청에 따라 운영 화면의 Meteogram 탭을 제거하기 전에 소스 전체를 별도 Git 브랜치로 보존했다.

- 백업 브랜치: `backup/meteogram-20261021`
- 원본 커밋: `6f2b07201422cde6f98be5d754738bbbb2f4ef4e`
- [백업 소스 열기](https://github.com/futurist38/nwp-verify/tree/backup/meteogram-20261021)
- 백업 당시 `site/index.html`, `site/app.js`, `site/style.css`의 Git blob SHA는 실제 배포 브랜치 `site-data`의 대응 파일과 모두 일치했다.
- 별도 브랜치는 기존 Git 객체를 참조하므로 대용량 그림 파일을 추가로 복사하지 않는다.

## 보존한 표출 방식

- 기온(℃), 전운량(%), 일사(W/m²), 강수(mm)의 도시별 모델 비교 시계열.
- ECMWF·GFS·KIM의 최신 런 선, 이전 최대 4개 런의 범위 띠/가는 선/끄기.
- 하늘 상태 배경 3단(위 ECMWF, 중간 KIM, 아래 GFS), 야간 음영, 현재시각 선.
- 모델별 색상, 범례, 날짜 선택, 마우스/터치 툴팁.
- 공통 SVG 차트 렌더러와 CSS, 시계열 JSON 생성 및 원자료 처리 코드.

| 위치(백업 브랜치 기준) | 내용 |
| --- | --- |
| `site/index.html` | `data-tab="meteo"` 메뉴, `#tab-meteo` 화면·설명·컨트롤 |
| `site/app.js` | `METEO_UNIT`, `METEO_ND`, `STRIP_ORDER`, `METEO`, `renderMeteoCharts()`, `renderMeteo()`, 초기화 연결 |
| `site/style.css` | `#meteoCharts` 배치·SVG 스타일 및 공통 스타일 |
| `build_site.py` | `export_meteo()`: 최신 런·이전 런, 3시간 격자 JSON, `meteo_dates` |
| `plot_charts.py` | 모델 일사 평균창 처리, `city_series()`, `plot_meteograms()` |
| `config.py`, `fetch_*.py`, `requirements.txt` | 수집 변수·예측시간·의존성 |
| `.github/workflows/`, `tools/publish_site.sh` | 자동 수집·발행 흐름 |

## 제거 범위와 유지 범위

운영 소스에서 메뉴, 전용 HTML, 전용 JavaScript 상태·렌더링·이벤트 초기화, 전용 CSS를 제거했다.
관련 안내 문구를 수정하고 CSS/JS 캐시 버전을 올렸다.

`meteo/*.json`, `manifest.meteo_dates`, `export_meteo()`는 `renderToday()`가 읽는 **공통 도시별 예측자료**이므로 유지한다.
공통 `drawPanel()`, 하늘 상태 색상 함수, 기상청 예보-관측·중기예보·검증 기능도 유지한다.
모델자료 수집, CSV 아카이브, 일사 검증, 지도 생성 설정은 변경하지 않았다.

## 복구 절차

1. 백업 브랜치의 위 3개 화면 파일을 현재 파일과 비교한다.
2. `index.html`에서 Meteogram 메뉴 및 `#tab-meteo` 구간만 복원한다.
3. `app.js`에서 미티오그램 상수·상태·렌더러, `renderMeteo()`, `init()`의 컨트롤 연결과 최초 호출을 복원한다.
4. `style.css`에서 `#meteoCharts` 규칙과 SVG 공통 선택자를 복원한다.
5. 안내 문구와 캐시 버전을 맞추고, 날짜/변수/이전 런/하늘 띠/툴팁 및 ‘오늘’·‘예보-관측’을 확인한 뒤 기존 발행 경로로 배포한다.

향후 수정사항을 보존하기 위해 현재 파일 전체를 옛 버전으로 덮어쓰지 말고 해당 구간만 복원한다.
전체 스냅샷 확인이 필요하면 별도 worktree에 백업 브랜치를 체크아웃한다.

## 일사량 표출 가능성 확인

`verification/city_forecast/20261021.csv`의 실제 값과 수집·판독 코드를 확인했다.

| 모델 | 수집 변수 | 현재 파일에서 확인한 평균 일사 자료 |
| --- | --- | --- |
| ECMWF | `ssrd` 누적값 → 차분/시간 | +3~144h: 3h 평균, +150~240h: 6h 평균 |
| GFS | `DSWRF` / GRIB shortName `sdswrf` | +3~120h: 3h 평균, 이후 12h 출력간격의 6h 평균 표본(+240h까지) |
| KIM NC | `dswrsfc` 매시값 → 3장 평균 | +3~120h: 3h 평균 |

11개 도시 전체에서 일사 값이 있는 행은 ECMWF 704개, GFS 550개, KIM 440개였다(야간 0 포함).
단위는 W/m²이며 순간 일사가 아닌 평균창의 값이다. 세 모델의 동일 시간창 비교는 +120h 이내가 명확하다.
GFS의 +120h 이후 6h 평균 표본은 출력간격이 12h이므로 연속 일적산으로 단순 합산하면 안 된다.

지도 렌더링 분기는 `plot_charts.py`에 남아 있으나 현재 패널 반복 목록에서 제외되어 있고,
`build_site.py`의 일사 지도 제외/정리 규칙 및 `site/app.js`의 `PANEL_ORDER`도 비활성 상태다.
지도 표출 시 이 세 위치를 함께 수정해야 한다. 이번 요청에서는 가능 여부만 조사하고 일사 지도를 추가하지 않았다.
