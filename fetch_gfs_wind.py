# -*- coding: utf-8 -*-
"""
GFS 스티어링 바람(U/V 850·700hPa) 수집 — 나우캐스트 벤치마크 M2(NWP 바람 이류)용.

KIM pres 통파일은 302MB/스텝(2026-08-23 실측)이라 주간 벤치마크에 과함 →
NOMADS grib filter의 변수·레벨 서브셋(스텝당 ~0.1MB)을 사용한다.
NOMADS 보관은 약 10일 — 벤치마크 주간(8/15~) 소급 수신 가능 시한에 주의.

저장: data/gfs_wind/gfswind_{runYYYYMMDDHH}_f{FFF}.grib2
사용: python fetch_gfs_wind.py --from 2026-08-15 --to 2026-08-21
      (각 6시간 런 × ef 0~5h — 임의 발령시각에 최근접 런의 해당 시각 바람 제공)
"""
import argparse
import datetime as dt
import os
import time

import requests

import sslfix  # noqa: F401
from config import DATA_DIR, LON_MIN, LON_MAX, LAT_MIN, LAT_MAX

BASE = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25_1hr.pl"
OUT_DIR = os.path.join(DATA_DIR, "gfs_wind")


def build_url(ymd: str, hh: str, step: int) -> str:
    params = [
        f"dir=%2Fgfs.{ymd}%2F{hh}%2Fatmos",
        f"file=gfs.t{hh}z.pgrb2.0p25.f{step:03d}",
        "var_UGRD=on", "var_VGRD=on",
        "lev_850_mb=on", "lev_700_mb=on",
        "subregion=",
        f"leftlon={LON_MIN}", f"rightlon={LON_MAX}",
        f"toplat={LAT_MAX}", f"bottomlat={LAT_MIN}",
    ]
    return BASE + "?" + "&".join(params)


def fetch_range(d0: dt.date, d1: dt.date):
    os.makedirs(OUT_DIR, exist_ok=True)
    session = requests.Session()
    n_ok = n_fail = 0
    failed = []
    day = d0
    while day <= d1:
        for hh in ("00", "06", "12", "18"):
            for step in range(6):
                run10 = f"{day:%Y%m%d}{hh}"
                path = os.path.join(OUT_DIR, f"gfswind_{run10}_f{step:03d}.grib2")
                if os.path.exists(path) and os.path.getsize(path) > 0:
                    n_ok += 1
                    continue
                ok = False
                for attempt in range(3):
                    try:
                        r = session.get(build_url(f"{day:%Y%m%d}", hh, step), timeout=120)
                        if r.status_code == 200 and len(r.content) > 1000:
                            with open(path + ".part", "wb") as f:
                                f.write(r.content)
                            os.replace(path + ".part", path)
                            ok = True
                            break
                    except requests.RequestException:
                        pass
                    time.sleep(2 * (attempt + 1))
                if ok:
                    n_ok += 1
                else:
                    n_fail += 1
                    failed.append(f"{run10}+{step}")
                time.sleep(0.4)
        day += dt.timedelta(days=1)
    print(f"[GFS풍] 완료: {n_ok} 확보, 실패 {n_fail}"
          + (f" — {failed[:8]}..." if failed else ""))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="d0", required=True)
    p.add_argument("--to", dest="d1", required=True)
    args = p.parse_args()
    fetch_range(dt.date.fromisoformat(args.d0), dt.date.fromisoformat(args.d1))


if __name__ == "__main__":
    main()
