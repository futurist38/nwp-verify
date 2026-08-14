# KPX 모델 표출 파이프라인 (ECMWF Open Data + GFS NOMADS)

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

## 산출물 (output/YYYYMMDD/)

| 산출물 | 내용 |
|---|---|
| `maps_ecmwf/`, `maps_gfs/` | 리드타임별 지도 PNG — 2m 기온(등온선 포함), 전운량, **저·중·상층 운량 HSL 합성**(GFS, ECMWF Newsletter No.101 방식 근사: 저층=갈색, 중층=자홍, 상층=청록) |
| `city_forecast.csv` | 11개 도시 × 전체 리드타임 시계열 (기온, 전운량, 층별 운량, 일사). `rep=1`이 대표 5지점(서울·대전·대구·광주·부산). KST 유효시각 병기 |
| `meteograms/` | 대표 5지점 ECMWF vs GFS 기온·전운량 비교 (태양광 피크 11~14 KST 음영) |

## 설치

```bash
pip install ecmwf-opendata cfgrib eccodes xarray pandas matplotlib requests cartopy
```

- `cfgrib`는 eccodes 시스템 라이브러리가 필요하다. pip의 `eccodes` 패키지로 안 되면
  `sudo apt install libeccodes0` (Ubuntu) 후 재시도.
- `cartopy`가 설치 안 되거나 해안선 데이터(Natural Earth) 다운로드가 방화벽에 막히면
  자동으로 해안선 없는 평면 지도로 대체된다. 폐쇄망이면 Natural Earth shapefile을
  미리 받아 `~/.local/share/cartopy/`에 넣어두면 된다.
- 그림의 한글 라벨은 나눔고딕 등 한글 폰트 필요: `sudo apt install fonts-nanum`
  후 matplotlib 캐시 삭제(`rm -rf ~/.cache/matplotlib`).

## 실행

```bash
# 수동 실행 (최신 런 자동 탐지)
python3 fetch_ecmwf.py
python3 fetch_gfs.py
python3 plot_charts.py

# 런 지정
python3 fetch_ecmwf.py --time 12          # 12UTC 런
python3 fetch_gfs.py --run 20260813 00    # 특정 런

# 일일 자동화 (crontab)
10 6 * * * /경로/kpx-model-charts/run_daily.sh >> /경로/kpx-model-charts/cron.log 2>&1
```

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
