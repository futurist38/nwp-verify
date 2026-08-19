# -*- coding: utf-8 -*-
"""
KPX 수요예측용 ECMWF/GFS 모델 표출 파이프라인 — 공통 설정
"""

# ── 표출 영역 (한반도) ─────────────────────────────────────
# GRIB 서브셋 및 지도 범위
LON_MIN, LON_MAX = 120.0, 135.0
LAT_MIN, LAT_MAX = 31.0, 44.0

# ── 지점 목록 ─────────────────────────────────────────────
# (이름, 위도, 경도, 대표지점 여부)
# 대표지점 5개: 브리핑 5-2 기온→총수요 판단용
CITIES = [
    ("서울", 37.571, 126.966, True),
    ("대전", 36.372, 127.372, True),
    ("대구", 35.878, 128.653, True),
    ("광주", 35.173, 126.891, True),
    ("부산", 35.105, 129.032, True),
    ("인천", 37.478, 126.625, False),
    ("수원", 37.257, 126.983, False),
    ("전주", 35.841, 127.117, False),
    ("강릉", 37.751, 128.891, False),
    ("제주", 33.514, 126.530, False),
    ("나주", 35.026, 126.717, False),
]

# ── 예측 시간 설정 ─────────────────────────────────────────
# ECMWF 오픈데이터: 0~144h는 3h 간격, 150~240h는 6h 간격
ECMWF_STEPS = list(range(0, 145, 3)) + list(range(150, 241, 6))
# GFS: 0~120h 3h 간격 (필요하면 384h까지 연장 가능)
GFS_STEPS = list(range(0, 121, 3))

# 지도 그림을 그릴 리드타임(시간). CSV/미티오그램은 전체 스텝 사용.
MAP_STEPS = list(range(0, 73, 6))

# KST = UTC + 9
KST_OFFSET_H = 9

# ── 변수 설정 ─────────────────────────────────────────────
# ECMWF 오픈데이터 요청 파라미터
#   2t  : 2m 기온
#   tcc : 전운량 (2025-11-20부터 오픈데이터 제공, 런 제한 있을 수 있음 → 실패 시 자동 제외)
ECMWF_PARAMS = ["2t", "tcc"]

# GFS NOMADS grib filter 변수/레벨
# 실측 확정(2026-08-14, gfs.t18z idx 대조): 층별 운량 변수명은 TCDC가 아니라
# LCDC/MCDC/HCDC. TCDC(entire atmosphere)·층별은 instant와 avg 두 계열이 오고,
# DSWRF는 avg(구간 평균)만 존재한다.
GFS_VARS = ["TMP", "TCDC", "LCDC", "MCDC", "HCDC", "DSWRF"]
GFS_LEVELS = [
    "2_m_above_ground",     # TMP
    "entire_atmosphere",    # TCDC 전운량
    "low_cloud_layer",      # LCDC 하층운
    "middle_cloud_layer",   # MCDC 중층운
    "high_cloud_layer",     # HCDC 상층운
    "surface",              # DSWRF 하향단파복사
]

# ── 오답노트(예측 vs 실황) 설정 ────────────────────────────
# 도시 → ASOS 지점번호. 2026-08-14 API허브 stn_inf(inf=SFC) 실측 확정.
# 나주는 ASOS 지점이 없어 실황 검증 제외(None) — 추정 대체 금지.
CITY_OBS_STN = {
    "서울": 108, "인천": 112, "수원": 119, "강릉": 105,
    "대전": 133, "대구": 143, "전주": 146, "광주": 156,
    "부산": 159, "제주": 184, "나주": None,
}

# 사례 파일 자동 생성 임계값 (일 단위 집계 기준)
CASE_THRESHOLDS = {
    "t2m_abs_me": 3.0,    # 기온 |ME| > 3.0 ℃
    "tcc_abs_err": 40.0,  # 운량 |오차| > 40 %p
}

# 리드타임 버킷 (ME/MAE 집계용, 시간)
LEAD_BUCKETS = [(0, 24), (24, 48), (48, 72), (72, 120), (120, 240)]

# 모델 발산 플래그 임계 (일일 요약 메일용) — 발산은 중재하지 않고 그대로 표시
DIVERGENCE_THRESHOLDS = {
    "t2m": 2.0,   # |T_EC - T_GFS| ≥ 2.0 ℃
    "tcc": 30.0,  # |C_EC - C_GFS| ≥ 30 %p
}

# 영향 번역 계수 — 발산 "폭"을 실무 단위(GW)로 환산하는 어림값.
# 단일값 추천이 아니라 리스크 폭의 단위 번역이다 (판단은 사람 소유).
# 출처: 공개 「일일 전력수급 동향」 보고서 역산 (수급요인분해 프로젝트, 2026-08).
IMPACT_COEF = {
    "pv_gw_per_util_pct": 0.283,     # 태양광 이용률 1%p ≈ 0.283GW (설비 28.3GW 기준, 공개 보고서 일치)
    "util_pct_per_cloud_pct": 0.6,   # 운량 1%p → 이용률 약 0.6%p (개인 어림값 — 검증 누적 후 조정)
    "demand_gw_per_degC": 1.47,      # 최고기온 1℃ ≈ 1.47GW (공개 보고서 역산 중앙값, 여름 냉방)
}
IMPACT_SOLAR_HOURS = [9, 12, 15]     # 태양광 창 (표 시각 기준)
IMPACT_TEMP_HOURS = [12, 15, 18]     # 냉방 민감 오후

# ── 출력 경로 ─────────────────────────────────────────────
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_DIR = os.path.join(BASE_DIR, "output")
VERIF_DIR = os.path.join(BASE_DIR, "verification")
