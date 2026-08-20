# -*- coding: utf-8 -*-
"""
KMA API허브 ASOS 시간자료 클라이언트.
태풍푄분석/KmaApi.ps1 의 실측 노하우를 이식한 것 — 아래 특성은 전부 실측 확인 사항.

  · 호스트는 apihub-pub.kma.go.kr 이어야 한다. apihub.kma.go.kr 은 일반사용자 키에 403.
  · 시간자료(kma_sfctm3)는 31일을 넘기면 오류가 아니라 "조용한 절단"이 일어나
    뒤쪽 31일만 돌아온다. 한도는 기간에 걸리므로 지점 수는 얼마든지 묶어도 된다.
    → 30일 청크 분할 + 청크마다 응답 최소시각 검증이 핵심 안전장치.
  · 응답 인코딩은 CP949. 오류는 JSON('{'로 시작), 정상은 '#START7777' 포함.
  · 결측 토큰은 "문자열 정확 비교"로 판정한다. 숫자로 -9 이하를 전부 결측 처리하면
    겨울철 기온 -9.0℃를 결측으로 날려버린다.
  · 시간자료 46필드 중 WW/CT(문자열 필드) 뒤쪽의 CA_TOT/SS/SI 는
    토큰 수가 정확히 46일 때만 신뢰한다.

인증키: 환경변수 KMA_AUTH_KEY → .env 파일(KMA_AUTH_KEY=...) 순으로 읽는다.

사용:
    python kma_asos.py --stations 108 133 --from 2026-08-10 --to 2026-08-12
    (verification/obs/YYYY-MM.csv 에 병합 저장)
"""
import argparse
import datetime as dt
import os
import re
import sys
import time

import pandas as pd
import requests

import sslfix  # noqa: F401  (AVG TLS 검사 대응)
from config import BASE_DIR, VERIF_DIR, CITY_OBS_STN

HOST = "https://apihub-pub.kma.go.kr"   # apihub.kma.go.kr 은 일반키 403
API_HOURLY = "/api/typ01/url/kma_sfctm3.php"
CACHE_DIR = os.path.join(VERIF_DIR, "obs", "cache", "asos_hourly")
OBS_DIR = os.path.join(VERIF_DIR, "obs")

REQUEST_DELAY_S = 0.3
RETRY = 3

# 결측 토큰 — 문자열 정확 비교 (KmaApi.ps1 실측)
MISSING_TOKENS = {"-", "-9", "-9.0", "-9.00", "-99", "-99.0",
                  "-999", "-999.0", "-99.00"}

# 시간자료 46필드 중 사용 필드 (0-base 인덱스)
# WS(3)·HM(13)은 WW(24) 앞이라 토큰 수와 무관하게 항상 안전 (KmaApi.ps1 실측)
H_IDX = {"TM": 0, "STN": 1, "WS": 3, "TA": 11, "HM": 13,
         "CA_TOT": 25, "SS": 33, "SI": 34}

_last_req = 0.0


def _auth_key() -> str:
    key = os.environ.get("KMA_AUTH_KEY")
    if key:
        return key.strip()
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        for line in open(env_path, encoding="utf-8"):
            m = re.match(r"\s*KMA_AUTH_KEY\s*=\s*(\S+)", line)
            if m:
                return m.group(1)
    raise RuntimeError("KMA_AUTH_KEY가 없습니다. 환경변수 또는 .env에 설정하세요.")


def _num(token: str):
    """결측 토큰이면 None, 아니면 float. 문자열 정확 비교."""
    if token in MISSING_TOKENS:
        return None
    try:
        return float(token)
    except ValueError:
        return None


def _request_text(query: dict, cache_name: str, no_cache: bool = False) -> str:
    """CP949 텍스트 응답 수신 + 디스크 캐시. 오류(JSON)는 캐시 없이 즉시 예외."""
    global _last_req
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(CACHE_DIR, cache_name + ".txt")

    if not no_cache and os.path.exists(cache_file):
        cached = open(cache_file, encoding="utf-8").read()
        if cached and not cached.lstrip().startswith("{"):
            return cached

    url = HOST + API_HOURLY
    params = dict(query)
    params["authKey"] = _auth_key()

    last_err = None
    for attempt in range(1, RETRY + 1):
        wait = REQUEST_DELAY_S - (time.monotonic() - _last_req)
        if wait > 0:
            time.sleep(wait)
        _last_req = time.monotonic()
        try:
            r = requests.get(url, params=params, timeout=180)
            text = r.content.decode("cp949")
        except requests.RequestException as e:
            last_err = str(e)
            print(f"[ASOS] 요청 실패 ({attempt}/{RETRY}) {cache_name}: {last_err}")
            time.sleep(attempt * 2)
            continue

        if text.lstrip().startswith("{"):
            # API허브 오류는 JSON으로 온다. 재시도해도 소용없으므로 즉시 중단.
            raise RuntimeError(f"API 오류 응답 [{cache_name}]: {text.strip()[:300]}")
        if "#START7777" not in text:
            last_err = "정상 마커(#START7777) 없음: " + text[:200]
            print(f"[ASOS] 응답 형식 이상 ({attempt}/{RETRY}) {cache_name}")
            time.sleep(attempt * 2)
            continue

        if not no_cache:
            tmp = cache_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, cache_file)
        return text

    raise RuntimeError(f"요청 최종 실패 [{cache_name}]: {last_err}")


def _parse_hourly(text: str) -> list[dict]:
    rows, short = [], 0
    for line in text.splitlines():
        l = line.strip()
        if not l or l.startswith("#"):
            continue
        f = l.split()
        if len(f) < 16:
            short += 1
            continue
        # WW/CT 문자열 필드 뒤쪽은 토큰 수 46일 때만 신뢰
        tail = (len(f) == 46)
        try:
            tm = dt.datetime.strptime(f[H_IDX["TM"]], "%Y%m%d%H%M")
        except ValueError:
            continue
        rows.append({
            "TM": tm,
            "STN": int(f[H_IDX["STN"]]),
            "TA": _num(f[H_IDX["TA"]]),
            "WS": _num(f[H_IDX["WS"]]),
            "HM": _num(f[H_IDX["HM"]]),
            "CA_TOT": _num(f[H_IDX["CA_TOT"]]) if tail else None,
            "SS": _num(f[H_IDX["SS"]]) if tail else None,
            "SI": _num(f[H_IDX["SI"]]) if tail else None,
        })
    if short:
        print(f"[ASOS] 토큰 부족 행 {short}개 건너뜀")
    return rows


def get_hourly(stations: list[int], t_from: dt.datetime, t_to: dt.datetime,
               no_cache: bool = False) -> pd.DataFrame:
    """30일 청크 분할 수신. 청크마다 절단 검증(핵심 안전장치)."""
    if t_to.hour == 0 and t_to.minute == 0:
        t_to = t_to.replace(hour=23)

    stations = sorted(stations)
    stn_param = ":".join(map(str, stations))
    stn_tag = "-".join(map(str, stations))
    if len(stn_tag) > 60:  # 전 지점 등 긴 목록은 해시 축약 (Windows 경로 한계)
        import hashlib
        stn_tag = f"n{len(stations)}_{hashlib.md5(stn_tag.encode()).hexdigest()[:8]}"
    all_rows = []

    chunk_start = t_from
    while chunk_start <= t_to:
        chunk_end = min(chunk_start + dt.timedelta(days=30, hours=-1), t_to)
        tm1 = chunk_start.strftime("%Y%m%d%H%M")
        tm2 = chunk_end.strftime("%Y%m%d%H%M")
        name = f"h_{stn_tag}_{tm1}_{tm2}"

        text = _request_text({"tm1": tm1, "tm2": tm2, "stn": stn_param, "help": 0},
                             name, no_cache)
        rows = _parse_hourly(text)

        if not rows:
            print(f"[ASOS] 빈 응답: {name}")
        else:
            min_tm = min(r["TM"] for r in rows)
            max_tm = max(r["TM"] for r in rows)
            if min_tm > chunk_start + dt.timedelta(hours=1):
                raise RuntimeError(
                    f"기간 절단 감지! 요청 {chunk_start}~{chunk_end} 인데 "
                    f"응답은 {min_tm}부터입니다. 청크 크기를 줄이세요.")
            if max_tm < chunk_end - dt.timedelta(hours=1):
                print(f"[ASOS] 응답 끝이 요청보다 이릅니다 ({max_tm} < {chunk_end}) — 미관측 구간일 수 있음")
            all_rows.extend(rows)

        chunk_start = chunk_end + dt.timedelta(hours=1)

    df = pd.DataFrame(all_rows)
    if not df.empty:
        df = df.sort_values(["TM", "STN"]).reset_index(drop=True)
    return df


def save_monthly(df: pd.DataFrame):
    """verification/obs/YYYY-MM.csv 에 병합 저장 (키: TM+STN, 새 값 우선)."""
    if df.empty:
        print("[ASOS] 저장할 행 없음")
        return
    os.makedirs(OBS_DIR, exist_ok=True)
    df = df.copy()
    df["TM"] = pd.to_datetime(df["TM"])
    for ym, g in df.groupby(df["TM"].dt.strftime("%Y-%m")):
        path = os.path.join(OBS_DIR, f"{ym}.csv")
        if os.path.exists(path):
            old = pd.read_csv(path, parse_dates=["TM"])
            merged = pd.concat([old, g], ignore_index=True)
            merged = merged.drop_duplicates(subset=["TM", "STN"], keep="last")
        else:
            merged = g
        merged = merged.sort_values(["TM", "STN"])
        merged.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"[ASOS] 저장: {path} ({len(merged)}행)")


def default_stations() -> list[int]:
    return sorted(s for s in CITY_OBS_STN.values() if s is not None)


def all_stations() -> list[int]:
    """전 ASOS 지점 (관측 실황 지도 보간용). stations.csv 없으면 검증 지점으로 폴백."""
    path = os.path.join(OBS_DIR, "stations.csv")
    if os.path.exists(path):
        return sorted(pd.read_csv(path)["STN"].astype(int))
    return default_stations()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stations", nargs="+", type=int, default=None,
                   help="지점번호 목록. 생략 시 config의 도시 매핑 전체")
    p.add_argument("--all", action="store_true", help="전 ASOS 지점 (stations.csv)")
    p.add_argument("--from", dest="t_from", required=True, help="YYYY-MM-DD")
    p.add_argument("--to", dest="t_to", required=True, help="YYYY-MM-DD")
    p.add_argument("--no-cache", action="store_true")
    args = p.parse_args()

    stations = args.stations or (all_stations() if args.all else default_stations())
    t_from = dt.datetime.strptime(args.t_from, "%Y-%m-%d")
    t_to = dt.datetime.strptime(args.t_to, "%Y-%m-%d")

    df = get_hourly(stations, t_from, t_to, args.no_cache)
    print(f"[ASOS] 수신 {len(df)}행 / 지점 {stations}")
    save_monthly(df)


if __name__ == "__main__":
    main()
