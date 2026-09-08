# NWP 모델 표출·검증 파이프라인 (ECMWF Open Data + GFS NOMADS)

ECMWF IFS 0.25° 오픈데이터와 GFS 0.25°(NOMADS)를 원본 GRIB으로 직접 받아
한반도 운량·기온을 매일 정량 표출하고, ASOS 실황과 대조하는 오답노트를 쌓는다.

> 개인 연구 프로젝트이며 공공기관 공식 서비스가 아니다. 전부 공개 데이터
> (ECMWF Open Data CC-BY 4.0 — 0.25° 재격자 자료, NOAA GFS, KMA API허브 공공누리)로 구성한다.

## 실측 확정 기록 (2026-08-14, 실 GRIB·실 API 대조)

브리프 2-1절의 미확정 항목을 실환경에서 확인한 결과. **추측이 아니라 실측이다.**

| # | 항목 | 실측 결과 |
|---|---|---|
| 1 | GFS 층별 운량 | 변수명은 TCDC가 아니라 **LCDC/MCDC/HCDC** (grib filter `var_` 파라미터 기준). GRIB 내부는 shortName `lcc/mcc/hcc`, typeOfLevel `lowCloudLayer/middleCloudLayer/highCloudLayer`. **instant와 avg(shortName `avg_lcc` 등) 두 계열 공존** → 판독 시 `stepType=instant` 필수 |
| 1b | GFS 전운량 | shortName `tcc`, typeOfLevel **`atmosphere`**, instant/avg 공존 → instant 사용 |
| 2 | ECMWF 00UTC `tcc` | **제공됨** (2026-08-13 00z data.ecmwf.int index 확인). `ssrd`(누적 일사)도 제공 — ⑤태양광 조인 시 활용 가능 |
| 3 | cartopy 해안선 | (첫 지도 생성 시 기록) |
| 4 | 한글 폰트 | Windows 기본 Malgun Gothic 사용. 기존 코드의 rc() 루프는 미설치 폰트에도 예외를 안 던져 무의미했음 → fontManager 조회로 수정 |
| 5 | GFS 일사 | shortName은 dswrf가 아니라 **`sdswrf`**, **avg만 존재**. 평균 구간은 6h마다 리셋(f003=0-3h, f006=0-6h, f009=6-9h …). GFS TCDC/층별 avg 계열도 동일 구간 체계 |
| + | ASOS 지점 | 서울 108·인천 112·수원 119·강릉 105·대전 133·대구 143·전주 146·광주 156·부산 159·제주 184 (stn_inf 실측). **나주는 ASOS 없음** → 실황 검증 제외 |
| + | Python | 3.14는 eccodes Windows 휠 미제공(cp313까지) → **3.13 venv** 사용 |
| + | SSL | 이 PC는 AVG 안티바이러스가 전 HTTPS를 가로챔 → certifi 실패. `sslfix.py`(truststore)로 OS 인증서 저장소 사용 |
| + | KMA API | 호스트는 `apihub-pub.kma.go.kr`(일반키 기준). 시간자료 31일 초과 요청은 조용한 절단 → 30일 청크+검증 (kma_asos.py) |
| + | GK2A (2026-08-23) | typ05 REST(`/api/typ05/api/GK2A/LE2/{산출물}/{영역}/data·dataList`)도 apihub-pub만 일반키 허용. CLA/KO: 2분 간격·지연 ~8분·0.8MB, 900×900 2km LCC(30/60, 원점 38N/126E, UL=(-899,+899)km). **CA(cloud amount)는 units 빈값이지만 raw×0.01=0~1 비율(×100 필요)** — KIM 운량과 같은 함정. CT(운형)는 야간 미산출. netCDF4 C 라이브러리는 한글 경로 불가 → h5netcdf 엔진 |
| + | KIM pres | sub=pres에 u/v 전층(850·700 포함) 존재하나 스텝당 302MB — 스티어링 바람은 GFS NOMADS 서브셋(fetch_gfs_wind.py, 스텝당 ~0.1MB) 사용 |

## 산출물 (output/YYYYMMDD/)

| 산출물 | 내용 |
|---|---|
| `maps_ecmwf/`, `maps_gfs/` | 리드타임별 지도 PNG — 2m 기온(등온선 포함), 전운량, **저·중·상층 운량 HSL 합성**(GFS, ECMWF Newsletter No.101 방식 근사: 저층=갈색, 중층=자홍, 상층=청록) |
| `city_forecast.csv` | 11개 도시 × 전체 리드타임 시계열 (기온, 전운량, 층별 운량, 일사). `rep=1`이 대표 5지점(서울·대전·대구·광주·부산). KST 유효시각 병기 |
| `meteograms/` | 대표 5지점 ECMWF vs GFS 기온·전운량 비교 (태양광 피크 11~14 KST 음영) |

## 설치 (Windows, 확정 절차)

```powershell
py -3.13 -m venv .venv          # 3.14는 eccodes 휠 미제공 (실측 확정 기록 참조)
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m cfgrib selfcheck    # "Your system is ready." 확인 후 진행
```

- 한글 폰트: Windows는 Malgun Gothic 기본 탑재라 추가 조치 불요.
  GitHub Actions(Ubuntu) 이행 시 `apt install fonts-nanum` + matplotlib 캐시 삭제.
- `.env` 파일에 `KMA_AUTH_KEY=...` 저장 (커밋 금지, .gitignore 등록됨).
- cartopy 해안선(Natural Earth)은 첫 실행 시 자동 다운로드 확인됨(50m).

## 실행

```powershell
# 수동 실행 (최신 런 자동 탐지)
.venv\Scripts\python fetch_ecmwf.py
.venv\Scripts\python fetch_gfs.py
.venv\Scripts\python plot_charts.py

# 런 지정
.venv\Scripts\python fetch_ecmwf.py --time 12          # 12UTC 런
.venv\Scripts\python fetch_gfs.py --run 20260813 00    # 특정 런

# 오답노트 (예측 vs ASOS 실황)
.venv\Scripts\python verify.py archive                 # 당일 예측 적재
.venv\Scripts\python verify.py score                   # 어제(KST) 채점 + 사례 태깅
.venv\Scripts\python verify.py score --date 2026-08-13 # 특정일 채점
.venv\Scripts\python verify.py report                  # ME/MAE 집계 + MAE 곡선

# ASOS 단독 수신
.venv\Scripts\python kma_asos.py --from 2026-08-10 --to 2026-08-12

# 일일 요약 메일 (②) — 2026-08-28 발송 중단(daily.yml에서 주석 처리).
# 같은 내용을 웹 검증 탭에서 볼 수 있게 되어 껐다. 아래 명령은 수동 실행용으로 남아 있다.
.venv\Scripts\python send_summary.py --dry-run   # summary_mail.html 로 미리보기
.venv\Scripts\python send_summary.py             # 실발송 (배치 마지막 단계에 포함)
```

메일 인증: `.env`에 `GMAIL_ADDR`, `GMAIL_APP_PASSWORD`(앱 비밀번호 — 공백 포함 표시형식
그대로 붙여넣어도 됨), 선택 `MAIL_TO`. 미설정이면 발송만 조용히 건너뛴다.
이 PC의 AVG Mail Shield는 SMTP를 별도 'Untrusted Root'로 가로채므로, AVG 가로채기가
확인된 경우에 한해 로컬 AV 구간을 비검증으로 연결한다 (send_summary.py `_smtp_connect` 참조).

### 표출 확장 (2026-09-06)

| 탭 | 추가된 것 | 자료·스크립트 |
|---|---|---|
| NWP | **강수**(3h 누적) 지도 패널, 3모델. 컨트롤을 날짜/모델/변수/런 그룹으로 구분. (일사 지도는 사용자 결정으로 제외 — 일사는 Meteogram·검증에만) | `plot_charts.py` `_read_windows` — EC `ssrd`·`tp`, GFS `DSWRF`·`APCP`, KIM `avg_sdswrf`·`lswp+cwp+snol+snoc` |
| Meteogram | 일사·강수 변수 / **이전 런 띠·선**(최대 4런) / **하늘 띠**(그래프 배경을 y축 3단으로 — 상 EC·중 KIM·하 GFS) / 야간 음영·지금 선 | `build_site.py export_meteo` (아카이브 `verification/forecast`) |
| 예보-관측 | 그래프 배경 2단 — **위 예보 하늘**(SKY·PTY, 강수확률은 마우스) · **아래 실측 하늘**(전운량) · 예보−실측 **오차 면** · **중기예보 섹션**(D+3~10 최고·최저 vs 실측, 1~3일 전 발표 겹침, 예보 범위 막대) | `plot_kmafcst.py`(SKY·PTY·POP 캐시), `kma_midfcst.py` |
| 관측 | **전운량** 지도 · **일최고/일최저 평년편차** 지도 · **위성 일사 하루 적산** 지도 | `plot_obsmap.py VARS`, `tools/build_normals.py`(자체 평년), `gk2a_swrad_daily.py` |
| 검증 | 일별 검증표에 **일사** · 일사 MAE 곡선 | `verify.py`(`win_h` 창 규약), `export_verif_daily` |
| 공통 | 갱신 신선도 배지(머리말) · 자동 재생(▶) · 카드 레이아웃 · 고정 탭 · **'오늘 한눈에' 첫 탭**(도시 카드: 지금 기온·오늘/내일 최고 3모델+기상청·평년편차 색·하늘·모델 합의 신호등) | `site/` |
| NWP 고도별 (2026-09-07) | **지상(해면기압 등압선 4hPa + 2m 기온 + H/L) · 925/850(고도+기온+바람깃) · 700(고도+상대습도+바람깃) · 500(고도+절대와도+바람깃) · 300/200(고도+풍속+바람깃)** — 층별 관례. 기온 세 층은 같은 색축(−25~35℃). 동아시아(100~150E, 20~55N), 6h 간격 +120h. ECMWF·GFS 전 층, KIM 지상만. 지상장에 H/L 중심 표시. **원본 GRIB 은 그림 뒤 삭제**(사용자 결정), 보존 14일 | `fetch_upper.py`(EC pl gh·t + sfc msl·2t ≈ 200MB, GFS 필터 14MB), `plot_upper.py --delete-raw`, manifest `psteps`(패널별 스텝) |

하늘 띠 규칙(공통): 3h 강수 ≥ 0.5mm(6h 창은 1mm) → 강수(하늘색) · 전운량 ≥ 85% → 흐림(진회) ·
55~85% → 구름많음(연회) · 그 외 맑음(흰). 단기예보 SKY 1/3/4, ASOS 전운량 0~5/6~8/9~10 을 같은 네 색에 매핑.

### 브리핑 묶음 (2026-09-08) — `briefing/latest.md`·`latest.json`

그림 대신 **값**을 LLM 에게 주고 분석시키기 위한 파일. `export_briefing.py` 가 build_site 안에서 돌아 daily·hourly 마다
덮어쓴다(과거 불보존). 담는 것: 특보 현황(`wrn_now_data`, 육상만) · 전국 종합 개황 문단(`fct_afs_ds` stn=108, 기압계·
강수 시간대 서술) · 최근 7일 모델 MAE/ME · 층별 일기도 링크(당일 archive) · 도시 11곳 일별 7일(평년·EC/GFS/KIM 최고/최저·
**폭(>5℃ ⚠)**·기상청 단기(하늘·강수확률)·중기·낮운량·강수) · 대표 6지점 상세(24h 관측, **직전 발표 vs 최신 발표 Δ**,
3h 시계열 + 기상청 풍향·풍속, **상층 지점값** 850기온/700습도/500지위고도/300풍속 6h) · 해안 4곳(인천·강릉·부산·제주)
기상청 예보 바람. 원수치만 싣고 보정값은 두지 않는다(사용자 원칙). 약 40KB.
실측: 개황 API 응답은 키에 따옴표가 없는 유사 JSON → 정규식 파싱. 단기예보 캐시에 WSD·VEC 추가(같은 응답, 호출 증가 없음).

**지점 추출 규칙 (2026-09-08 확정 — A/B 채점 결과)** — 로컬 GRIB(EC 10런·GFS 11런·KIM 3런, 8/13~20·9/5~7)과 ASOS 10지점으로
최근접 1점·쌍선형·3×3 평균·3×3 육지가중을 채점. **기온은 최근접**이 최선(EC 1.83 / 쌍선형 1.89 / 3×3 1.81 / 육지가중 2.16 ℃;
육지가중은 강릉 1.39→3.80 — 주변 '육지' 격자가 태백산맥이라 오히려 동해 격자가 해안 도시를 대표), **운량은 3×3 평균**이
MAE −12%(EC 25.5→22.6, GFS 24.2→21.6 %p, ME 불변 = 잡음 감소). → 기온·일사·강수 최근접, 운량(전·층별) 3×3 평균으로 확정.
**2026-09-08 이후 운량 채점은 이전과 기준이 다르다.**

**수신 속도 (2026-09-07 실측, 이 PC)** — `ecmwf_parallel.py` 스텝 병렬 수신. ECMWF 서버는 연결당 ~0.34MB/s 라
순차(라이브러리 기본)로는 300MB 에 15분. 상층 21병렬 1.9MB/s(3분), 본 파일 16병렬 2.0MB/s(225MB 112초), 503 없음.
KIM(API허브)은 스텝 병렬 4 로 원본 2.3→5.9MB/s(25스텝 1.9GB ≈ 5.5분). KIM 의 구조적 한계는 변수·층 필터가 없어
스텝당 76MB 를 다 받아 13MB 만 남기는 것과 상층 pres 파일 302MB/스텝. 일 트래픽 한도는 API허브 마이페이지 확인 필요.

**실측 확정 기록 (2026-09-06)**
- ECMWF 오픈데이터 ENS 에 평균(em)·표준편차(es) 산출물은 **없다** — pf 50멤버만(`Client.latest` 는 통과하나 `retrieve` 가 인덱스 없음으로 실패). `fetch_ens.py` 는 06·15 KST 12스텝(≈400MB)만 받아 도시 통계를 내는 수집기로 **보류 상태**(사용자 결정, 표출·파이프라인 미연결). GFS 는 GEFS 가 평균·스프레드 파일을 따로 제공해 훨씬 싸다 — 재개 시 GEFS 먼저.
- **브라우저 렌더링 시제품 보류**(2026-09-08, 사용자 결정: 아직 이득보다 비용이 큼). `tools/proto/render.html`+`tools/export_grid.py` 는 존치 — 격자값(0.25°, 정수 JSON 14MB/모델·런)을 받아 d3-contour 로 등치선·채움·해안선을 그리고 두 모델을 스와이프로 비교·값 읽기까지 동작 확인(로컬 미리보기). 재개 시 순서: 정수 바이너리+gzip 압축(→2~3MB) → R2 저장 → 별도 페이지 → 라벨 배치·바람깃·KIM·층 확장.
- ECMWF HRES 에 `tp`·`ssrd` 추가 시 런 파일 80MB → **208MB**(수신 시간 2.5배).
- KIM k512 의 `tp` 는 전 스텝 최대 0.02mm 인 **빈 필드**. 강수는 `lswp`(=`ncpcp`)·`cwp`, 눈은 `snol`·`snoc` — 모두 3h 창 누적. `avg_sdswrf` 도 3h 창.
- GFS `APCP` 는 f009 에 (6-9)·(0-9) 창이 공존, f006 은 (0-6) 만 → cfgrib 하이퍼큐브 충돌. eccodes 로 직접 읽어 3h 창으로 재조합.
- 기상청 API허브에 **평년값 API 가 없다**(nrm_*, sts_nrm 등 404). 일자료 `kma_sfcdd3`(1년·전지점 한 호출 8.5MB)로 1991~2020 을 받아 자체 산출(유효 20년 이상 73지점, ±7일 평활).
- 중기예보 기온 `fct_afs_wc.php` 는 apihub-pub 에서 일반키 OK, `tmfc1~tmfc2` 범위 조회 가능(백필 도시당 1회). 10도시 예보구역 코드는 `kma_midfcst.py REGS`.
- GK2A SWRAD KO: `DSR`(uint16 ×0.1 W/m²) 900×900, CLA 와 같은 LCC 격자. netCDF4 는 **윈도우 한글 경로를 못 열어** 메모리 모드로 읽는다.

### 그림 저장소 Cloudflare R2 (2026-09-08 이관)

Pages 1GB 상한 때문에 지도·상층 그림(`archive/`)은 **R2(무료 10GB)** 에 두고 site-data 에는 JSON·나우캐스트만 남긴다.
`tools/publish_site.sh` 가 `R2_BUCKET` 이 있을 때만 다음을 한다: R2 보존 정리(날짜 폴더명 기준 — `MAX_DAYS` 지나면 폴더째,
`UPPER_MAX_DAYS` 지나면 상층 p925~p200 만. `build_site.py` 로컬 정리와 같은 규칙) → `rclone lsf` 목록 →
`build_site.py` 가 목록+이번 산출로 manifest 생성(`img_base` 기록) → 새 그림 `rclone copy --size-only` → `site_build/archive` 삭제.
비밀값이 없으면 예전처럼 site-data 에 그림을 넣는다. 뷰어는 `manifest.img_base` 접두어로 그림을 찾는다(img 태그뿐이라 CORS 불필요).
버킷 한정 토큰은 버킷 목록 권한이 없어 `no_check_bucket=true` 로 rclone 의 버킷 확인을 끈다.
로컬 끝-끝 시험(2026-09-08 통과): `rclone serve s3 <폴더> --auth-key k,s --addr 127.0.0.1:9333` 을 띄우고
`R2_ENDPOINT=http://127.0.0.1:9333 R2_BUCKET=<폴더 안 버킷명> … DRY_RUN=1 SITE_DIR=… tools/publish_site.sh "t" --hourly`.

**설정 절차 (1회)**
0. Cloudflare 대시보드 → **R2 Object Storage** → 처음이면 결제수단(카드/PayPal) 등록을 요구한다 — 무료 한도(저장 10GB, A급 100만·B급 1,000만 요청/월, 송출 무료) 안이면 청구 없음. 여기는 월 1GB 미만·요청 수십만 건.
1. **Create bucket**: 이름 `nwp-verify-img`, Location hint **APAC**, 저장 등급 Standard
2. 버킷 → **Settings → Public Development URL(r2.dev)** → Enable → `https://pub-….r2.dev` 복사.
   r2.dev 는 요청 속도 제한이 있는 개발용 주소라 개인 열람엔 충분하고, Cloudflare 에 둔 도메인이 있으면 Custom Domain 이 낫다(캐시·제한 없음).
3. R2 개요 오른쪽 **Manage R2 API Tokens → Create API token**: 이름 `nwp-verify-actions`, Permissions **Object Read & Write**,
   Specify bucket(s) → 이 버킷만, TTL Forever → Create. 화면에 한 번만 보이는 **Access Key ID · Secret Access Key** 와
   엔드포인트 `https://<계정ID>.r2.cloudflarestorage.com` 의 **계정 ID**(R2 개요 오른쪽에도 있음)를 복사
4. GitHub 등록 — 저장소 폴더에서 gh CLI(값은 프롬프트에 붙여 넣는다. 대화·커밋에 남기지 말 것):
   ```
   gh secret set R2_ACCOUNT_ID
   gh secret set R2_ACCESS_KEY_ID
   gh secret set R2_SECRET_ACCESS_KEY
   gh variable set R2_BUCKET --body nwp-verify-img
   gh variable set R2_PUBLIC_URL --body https://pub-….r2.dev
   ```
5. 확인: `gh workflow run obs-hourly.yml -f force=true` → 로그에 `[publish] R2 목록 …` 과 `archive → R2 업로드 후 site-data 에서 제외` →
   사이트 그림 주소가 r2.dev 로 바뀌면 끝. **첫 실행은 기존 그림 ~650MB(1.3만 장)를 올리느라 5~10분 더 걸린다**(로컬 시험 1분).
   실패해도 `::warning::` 만 내고 그림을 site-data 에 남기니 사이트는 깨지지 않는다.
되돌리기: `R2_BUCKET` 변수를 지우면 다음 발행부터 예전 방식. 단 이미 R2 로 옮긴 그림은 site-data 에 없으므로
`rclone copy r2:<버킷>/archive site_build/archive` 로 내려받아 한 번 발행해야 과거 날짜가 보인다.
로컬 미리보기(DRY_RUN)는 R2 없이 그대로 동작.

### 사이트 발행 방식 (2026-09-06 개편)

두 워크플로(`daily-nwp`, `obs-hourly`)는 **서로 기다리지 않는다**. 예전에는 동시성 그룹을
나눠 써서 시간별 관측 갱신이 daily 전체(기상청 API가 막히는 날 80~100분)를 기다리다
다음 시간분에 밀려 취소됐고, 관측·예보-관측이 2~3시간씩 멈췼다(9/5 실측). 대신:

- `tools/publish_site.sh` — **낙관적 잠금 발행**. 최신 site-data 복원 → 이번 산출 얹기 →
  복원 시점 SHA 를 전제로 `--force-with-lease` push. 그 사이 남이 먼저 발행했으면 거부되고
  처음부터 다시(최대 6회). 로컬 시험은 `DRY_RUN=1 SITE_DIR=<임시폴더>` 로.
- `build_site.py` **무회귀 가드** — 관측·예보-관측 JSON은 배포본보다 *덜 찬* 것으로 덮어쓰지
  않는다(daily 는 시작 시각 관측을 종료 시각에 발행하므로 시간별 갱신을 되돌릴 수 있었다).
  `--hourly` 모드는 daily 소유물(모델 지도·미티오그램·검증·예보변화)에 손대지 않는다.
- daily 는 **2단계 발행** — NWP 지도가 나오는 즉시 1차, 검증·관측 뒤 2차. 단계마다 `timeout`
  과 `plot_fcstdiff.py --max-minutes` 로 한 API 지연이 전체를 잡아먹지 못하게 했다.
- 심장박동 cron 은 gate 가 걸러낸다 — 최근(obs 2h·daily 8h)에 성공한 실행이 있으면 건너뜀.
  GitHub 예약은 4~5시간 늦게 발동하는 일이 잦아 정상 실행과 겹쳤다.

일일 자동화는 Windows 작업 스케줄러에 등록되어 있다 (`run_daily.ps1` 상단 참조):
- `kpx-model-06` 06:10 KST — 대개 ECMWF 전일 12UTC + GFS 당일 18UTC(전일 기준) 런
- `kpx-model-10` 10:30 KST — 당일 00UTC 런 (ECMWF 00Z는 09~10 KST 배포)

## 오답노트 (verification/)

| 경로 | 내용 |
|---|---|
| `forecast/YYYY-MM.csv` | 예측 원수치 적재 (run_utc 월별) |
| `obs/YYYY-MM.csv` | ASOS 실황 (TA·CA_TOT·SS·SI 원값) |
| `scores/YYYY-MM.csv` | 행 단위 fcst·obs·err — 원수치 보존, ME/MAE는 report 시 재계산 |
| `cases/*.md` | 임계 초과일(기온 \|ME\|>3℃, 운량 >40%p) 자동 사례 파일. 원인 분석은 사람이 기입 |
| `scores_summary.csv`, `mae_curve_*.png` | 도시×모델×리드타임 버킷 ME/MAE 집계 |

원칙: 모델 간 발산은 평균·중재하지 않고 그대로 표시한다. 요약 옆에는 항상
원수치를 남긴다. 수집 실패는 추정으로 채우지 않고 누락으로 명시한다.

06:10 KST 실행 기준 ECMWF는 전일 12UTC 런, GFS는 당일 18UTC(전일 기준) 런이
잡히는 경우가 많다. 1차 브리핑에 당일 00UTC 런을 쓰려면 ECMWF 오픈데이터
배포 지연(실시간 대비 약 +2시간, 00UTC 런은 대략 09~10 KST 배포)을 감안해
오전 10시 이후 2차 수신을 걸어두는 것을 권장.

## 자료 특성·주의사항

- **ECMWF 오픈데이터**: 0.25°, 0~144h는 3시간·이후 6시간 간격. `tcc`(전운량)는
  2025-11-20부터 제공되나 런에 따라 없을 수 있음 → 코드가 자동으로 `2t`만으로
  재시도한다. 층별 운량(lcc/mcc/hcc)은 오픈데이터에 없다.
- **GFS**: 층별 운량(저·중·상)이 모두 제공되어 3층 HSL 합성은 GFS로만 그린다.
  `DSWRF`(일사)는 순간값이 아니라 **직전 출력시각 이후 평균값**이므로 시간 적분
  시 주의.
- **수치 검증·논문용 원자료로 쓸 때**: ECMWF 오픈데이터는 원해상도(9km)가 아닌
  0.25° 재격자 자료임을 명시할 것.
- NOMADS는 요청 빈도 제한이 있어 스텝 간 0.5초 대기를 넣어두었다. 제한에
  걸리면(HTTP 429/403) 대기 시간을 늘릴 것.
- 방화벽 허용 필요 도메인: `data.ecmwf.int`, `nomads.ncep.noaa.gov`
  (ECMWF 미러 사용 시 `ai4edataeuwest.blob.core.windows.net`(Azure) 또는
  `ecmwf-forecasts.s3...amazonaws.com`(AWS) — `fetch_ecmwf.py --source azure/aws`)

## 커스터마이징

`config.py`에서 영역·도시·리드타임·지도 스텝을 조정한다.
GFS 예측 연장(120h → 384h)은 `GFS_STEPS` 수정 (120h 이후는 3h 간격 유지되나
240h 이후는 12h 간격 파일만 존재하므로 스텝 목록에 반영 필요).
