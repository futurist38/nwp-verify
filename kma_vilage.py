# -*- coding: utf-8 -*-
"""
기상청 단기예보(동네예보) 수신 공용 모듈.

plot_kmafcst.py 에만 있던 인증·발표시각·수신 로직을 공용화 (2026-08-26) —
예보 변화 지도(plot_fcstdiff.py)가 같은 API를 쓰게 되면서 중복을 막는다.

실측 확정 (2026-08-21):
  · apihub-pub 호스트만 일반키 허용 (typ02 공통)
  · 1시간 간격(TMP), 발표 하루 8회(02/05/08/11/14/17/20/23시, +15분께 가용)
  · 한 번 호출로 전 카테고리·전 시각이 오므로, 필요한 카테고리만 골라 쓰면 된다
"""
import datetime as dt
import math
import os
import re
import time

import requests

import sslfix  # noqa: F401
from config import BASE_DIR

API = ("https://apihub-pub.kma.go.kr/api/typ02/openApi/"
       "VilageFcstInfoService_2.0/getVilageFcst")
BASE_HOURS = [2, 5, 8, 11, 14, 17, 20, 23]


def auth_key() -> str:
    key = os.environ.get("KMA_AUTH_KEY")
    if key:
        return key.strip()
    m = re.search(r"KMA_AUTH_KEY\s*=\s*(\S+)",
                  open(os.path.join(BASE_DIR, ".env"), encoding="utf-8").read())
    return m.group(1)


def latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    """위경도 → 동네예보 격자(nx, ny). 기상청 공개 변환식(Lambert Conformal, 5km)."""
    RE, GRID = 6371.00877, 5.0
    SLAT1, SLAT2, OLON, OLAT, XO, YO = 30.0, 60.0, 126.0, 38.0, 43, 136
    DEGRAD = math.pi / 180.0
    re_ = RE / GRID
    sl1, sl2 = SLAT1 * DEGRAD, SLAT2 * DEGRAD
    olon, olat = OLON * DEGRAD, OLAT * DEGRAD
    sn = math.tan(math.pi * 0.25 + sl2 * 0.5) / math.tan(math.pi * 0.25 + sl1 * 0.5)
    sn = math.log(math.cos(sl1) / math.cos(sl2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + sl1 * 0.5)
    sf = sf ** sn * math.cos(sl1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re_ * sf / ro ** sn
    ra = math.tan(math.pi * 0.25 + lat * DEGRAD * 0.5)
    ra = re_ * sf / ra ** sn
    theta = lon * DEGRAD - olon
    theta = (theta + math.pi) % (2 * math.pi) - math.pi
    theta *= sn
    return (int(ra * math.sin(theta) + XO + 0.5),
            int(ro - ra * math.cos(theta) + YO + 0.5))


def issuances_for(day: dt.date, now: dt.datetime) -> list[str]:
    """대상일 D의 선택지: 전일 17/20/23시 + 당일 발표분(가용 시각까지). 'YYYYMMDDHH'"""
    y = day - dt.timedelta(days=1)
    out = [f"{y:%Y%m%d}{h:02d}" for h in (17, 20, 23)]
    avail = now - dt.timedelta(minutes=15)
    for h in BASE_HOURS:
        if dt.datetime.combine(day, dt.time(h)) <= avail:
            out.append(f"{day:%Y%m%d}{h:02d}")
    return out


def latest_issuance(now: dt.datetime) -> str:
    """지금 시점에서 가장 최근에 나온 발표시각 'YYYYMMDDHH'."""
    avail = now - dt.timedelta(minutes=15)
    for back in range(0, 2):
        d = (avail - dt.timedelta(days=back)).date()
        for h in sorted(BASE_HOURS, reverse=True):
            t = dt.datetime.combine(d, dt.time(h))
            if t <= avail:
                return f"{d:%Y%m%d}{h:02d}"
    raise RuntimeError("발표시각 산출 실패")


def fetch(nx: int, ny: int, bdt: str, key: str,
          cats: tuple[str, ...] = ("TMP",), retries: int = 3) -> dict:
    """발표 bdt의 예보 → {카테고리: {'YYYYMMDDHH': 값}}. 한 번 호출로 전 시각 확보."""
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(API, params={"pageNo": 1, "numOfRows": 1300,
                                          "dataType": "JSON", "base_date": bdt[:8],
                                          "base_time": bdt[8:] + "00",
                                          "nx": nx, "ny": ny, "authKey": key},
                             timeout=60)
            j = r.json()
            if j["response"]["header"]["resultCode"] != "00":
                raise RuntimeError(f"단기예보 오류: {j['response']['header']}")
            out: dict[str, dict[str, float]] = {c: {} for c in cats}
            for it in j["response"]["body"]["items"]["item"]:
                c = it["category"]
                if c in out:
                    out[c][it["fcstDate"] + it["fcstTime"][:2]] = float(it["fcstValue"])
            return out
        except Exception as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"단기예보 수신 실패({bdt} {nx},{ny}): {last}")
