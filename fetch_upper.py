# -*- coding: utf-8 -*-
"""
고도별 기압장(지상·925·850·700·500·300·200 hPa) 수신 — ECMWF 오픈데이터 + GFS NOMADS (2026-09-07).

  · ECMWF: levtype=pl 의 gh·t (지오퍼텐셜 고도·기온) + sfc 의 msl·2t. 전구 파일이라 영역 절단 불가 —
    6시간 간격 0~120h(21스텝) 만 받는다 (6층×2변수×21 ≈ 250필드 ≈ 170MB + sfc 42필드 ≈ 30MB).
  · GFS: NOMADS 필터에 층·변수·**동아시아 영역**을 지정 → 스텝당 0.2MB 수준.
  · KIM: 상층은 pres 파일이 층 필터 없이 스텝당 302MB 라 제외(실측). 지상 해면기압(prmsl)은 unis 파일에
    있어 fetch_kim.py 가 함께 추출한다 → plot_upper.py 가 kim_*.grib2 에서 지상장만 그린다.

원본은 그림을 만든 뒤 지운다(plot_upper.py --delete-raw) — 그림만 보존한다는 사용자 결정.
산출: data/upper_ecmwf_pl_{run}.grib2, data/upper_ecmwf_sfc_{run}.grib2, data/upper_gfs_{run}.grib2
사용: python fetch_upper.py [--ecmwf-only|--gfs-only] [--source ecmwf|azure|aws]
"""
import argparse
import os
import sys
import time

import requests

import sslfix  # noqa: F401
from config import DATA_DIR

LEVELS = [925, 850, 700, 500, 300, 200]
STEPS = list(range(0, 121, 6))
# 상층 패널 영역(동아시아) — 500hPa 골·능이 보이게 한반도 지도보다 넓다
UP_LON_MIN, UP_LON_MAX, UP_LAT_MIN, UP_LAT_MAX = 100.0, 150.0, 20.0, 55.0

GFS_BASE = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"


def fetch_ecmwf(source: str) -> list[str]:
    from ecmwf.opendata import Client
    c = Client(source=source, model="ifs", resol="0p25")
    req_pl = {"type": "fc", "stream": "oper", "levtype": "pl", "levelist": LEVELS,
              "param": ["gh", "t"], "step": STEPS}
    latest = c.latest(**req_pl)
    tag = latest.strftime("%Y%m%d%H")
    print(f"[UPPER] ECMWF 런 {latest:%Y-%m-%d %H}UTC")
    out = []
    for name, req in (("pl", req_pl),
                      ("sfc", {"type": "fc", "stream": "oper", "levtype": "sfc",
                               "param": ["msl", "2t"], "step": STEPS})):
        target = os.path.join(DATA_DIR, f"upper_ecmwf_{name}_{tag}.grib2")
        if os.path.exists(target) and os.path.getsize(target) > 0:
            print(f"[UPPER] 이미 수신됨: {target}")
        else:
            tmp = target + ".part"
            c.retrieve(target=tmp, **{**req, "time": latest.hour})
            os.replace(tmp, target)
            print(f"[UPPER] ECMWF {name} 수신: {os.path.getsize(target) / 1e6:.0f}MB")
        out.append(target)
    return out


def gfs_url(ymd: str, hh: str, step: int) -> str:
    p = [f"dir=%2Fgfs.{ymd}%2F{hh}%2Fatmos", f"file=gfs.t{hh}z.pgrb2.0p25.f{step:03d}",
         "var_HGT=on", "var_TMP=on", "var_PRMSL=on"]
    p += [f"lev_{lv}_mb=on" for lv in LEVELS]
    p += ["lev_mean_sea_level=on", "lev_2_m_above_ground=on", "subregion=",
          f"leftlon={UP_LON_MIN}", f"rightlon={UP_LON_MAX}", f"toplat={UP_LAT_MAX}", f"bottomlat={UP_LAT_MIN}"]
    return GFS_BASE + "?" + "&".join(p)


def fetch_gfs() -> str:
    from fetch_gfs import find_latest_run
    s = requests.Session()
    ymd, hh, _ = find_latest_run(s)
    target = os.path.join(DATA_DIR, f"upper_gfs_{ymd}{hh}.grib2")
    if os.path.exists(target) and os.path.getsize(target) > 0:
        print(f"[UPPER] 이미 수신됨: {target}")
        return target
    print(f"[UPPER] GFS 런 {ymd} {hh}Z")
    tmp = target + ".part"
    n_ok = 0
    with open(tmp, "wb") as dst:
        for step in STEPS:
            ok = False
            for attempt in range(3):
                try:
                    r = s.get(gfs_url(ymd, hh, step), timeout=120)
                    if r.status_code == 200 and r.content[:4] == b"GRIB":
                        dst.write(r.content); ok = True; break
                    print(f"[UPPER] GFS f{step:03d} 응답 {r.status_code} ({attempt + 1}/3)")
                except requests.RequestException as e:
                    print(f"[UPPER] GFS f{step:03d} 실패 ({attempt + 1}/3): {e}")
                time.sleep(2 * (attempt + 1))
            n_ok += ok
    os.replace(tmp, target)
    print(f"[UPPER] GFS 수신: {n_ok}/{len(STEPS)}스텝, {os.path.getsize(target) / 1e6:.1f}MB")
    return target


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ecmwf-only", action="store_true")
    p.add_argument("--gfs-only", action="store_true")
    p.add_argument("--source", default="ecmwf", choices=["ecmwf", "azure", "aws"])
    a = p.parse_args()
    os.makedirs(DATA_DIR, exist_ok=True)
    rc = 0
    if not a.gfs_only:
        try:
            fetch_ecmwf(a.source)
        except Exception as e:
            print(f"[UPPER] ECMWF 실패: {e}", file=sys.stderr); rc = 1
    if not a.ecmwf_only:
        try:
            fetch_gfs()
        except Exception as e:
            print(f"[UPPER] GFS 실패: {e}", file=sys.stderr); rc = 1
    sys.exit(rc)


if __name__ == "__main__":
    main()
