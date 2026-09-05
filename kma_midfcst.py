# -*- coding: utf-8 -*-
"""
기상청 중기예보 기온(D+3~D+10 일 최저·최고) 수집 — API허브 typ01 fct_afs_wc.php.

실측 확정 (2026-09-06):
  · 호스트는 apihub-pub (apihub 는 일반키 403). 예보구역 코드로 도시별 조회.
  · 응답: REG_ID TM_FC TM_EF MOD STN C MIN MAX MIN_L MIN_H MAX_L MAX_H  (disp=0, 공백 구분)
    MOD A01=24시간 구간, A02=12시간 구간(가까운 날에 오전/오후로 쪼개지기도 함).
    MIN_L/MIN_H/MAX_L/MAX_H 는 예보 범위 폭(±℃).
  · 발표 하루 2회(06·18시). tmfc1~tmfc2 범위 조회가 되므로 백필은 도시당 1회 호출.

캐시: verification/midfcst/{발표YYYYMMDDHH}.json  {city: {YYYYMMDD: {min,max,min_l,min_h,max_l,max_h}}}
      발표분은 불변 → 있으면 재호출하지 않는다 (커밋 대상).
사용: python kma_midfcst.py                 # 최근 3일 발표분 채움
      python kma_midfcst.py --days 14       # 백필
"""
import argparse
import datetime as dt
import json
import os

import requests

import sslfix  # noqa: F401
from kma_vilage import auth_key
from config import VERIF_DIR

URL = "https://apihub-pub.kma.go.kr/api/typ01/url/fct_afs_wc.php"
CACHE_DIR = os.path.join(VERIF_DIR, "midfcst")
# 중기예보 기온 예보구역 코드 (2026-09-06 실측: 10도시 전부 200·자료 있음)
REGS = {"서울": "11B10101", "인천": "11B20201", "수원": "11B20601", "대전": "11C20401",
        "대구": "11H10701", "부산": "11H20201", "광주": "11F20501", "전주": "11F10201",
        "강릉": "11D20501", "제주": "11G00201"}


def fetch_city(reg: str, tmfc1: str, tmfc2: str, key: str) -> list[list[str]]:
    for attempt in range(3):
        try:
            r = requests.get(URL, params={"reg": reg, "tmfc1": tmfc1, "tmfc2": tmfc2,
                                          "disp": 0, "help": 0, "authKey": key}, timeout=60)
            r.raise_for_status()
            return [l.split() for l in r.text.splitlines() if l and not l.startswith("#")]
        except Exception as e:
            print(f"[중기예보] {reg} 수신 실패({attempt + 1}/3): {e}")
    return []


def _num(s: str):
    try:
        v = float(s)
        return None if v <= -99 else v
    except ValueError:
        return None


def collect(days: int) -> dict:
    """{tmfc: {city: {ymd: {...}}}} — 범위 안 전 발표분."""
    key = auth_key()
    now = dt.datetime.now()
    tmfc1 = f"{now - dt.timedelta(days=days):%Y%m%d}0600"
    tmfc2 = f"{now:%Y%m%d%H}00"
    out: dict = {}
    for city, reg in REGS.items():
        for f in fetch_city(reg, tmfc1, tmfc2, key):
            if len(f) < 12:
                continue
            tmfc, tmef, mod = f[1][:10], f[2][:8], f[3]
            rec = {"min": _num(f[6]), "max": _num(f[7]), "min_l": _num(f[8]),
                   "min_h": _num(f[9]), "max_l": _num(f[10]), "max_h": _num(f[11]), "mod": mod}
            slot = out.setdefault(tmfc, {}).setdefault(city, {})
            prev = slot.get(tmef)
            if prev is None or (prev["mod"] == "A02" and mod == "A01"):
                slot[tmef] = rec            # 24시간 구간(A01) 우선
            elif prev["mod"] == "A02" and mod == "A02":
                # 오전/오후 12시간 구간 둘이면 최저는 낮은 쪽, 최고는 높은 쪽
                for k, fn in (("min", min), ("max", max)):
                    vals = [v for v in (prev[k], rec[k]) if v is not None]
                    prev[k] = fn(vals) if vals else None
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=3, help="이 일수 전 발표부터 채움")
    args = p.parse_args()
    os.makedirs(CACHE_DIR, exist_ok=True)
    have = {f[:-5] for f in os.listdir(CACHE_DIR) if f.endswith(".json")}
    data = collect(args.days)
    n_new = 0
    for tmfc, cities in sorted(data.items()):
        if tmfc in have:
            continue
        # 발표 직후엔 일부 구역만 먼저 올라올 수 있다 — 10도시가 다 있을 때만 확정 저장
        if len(cities) < len(REGS):
            print(f"[중기예보] {tmfc}: {len(cities)}/{len(REGS)}도시 — 아직 미완, 다음 실행에")
            continue
        with open(os.path.join(CACHE_DIR, f"{tmfc}.json"), "w", encoding="utf-8") as fp:
            json.dump(cities, fp, ensure_ascii=False, separators=(",", ":"))
        n_new += 1
    print(f"[중기예보] 발표 {len(data)}건 조회, 신규 저장 {n_new}건 → {CACHE_DIR}")


if __name__ == "__main__":
    main()
