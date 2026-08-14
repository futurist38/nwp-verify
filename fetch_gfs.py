# -*- coding: utf-8 -*-
"""
GFS 0.25° 수신 (NOAA NOMADS grib filter)
- 변수(TMP/TCDC/DSWRF)·레벨·한반도 영역만 서브셋해서 받으므로 파일이 작음
- 최신 가용 런(00/06/12/18Z)을 자동 탐지
- 스텝별 개별 GRIB을 받아 하나의 파일로 이어붙임

사용:
    python fetch_gfs.py                 # 최신 런
    python fetch_gfs.py --run 20260813 00
"""
import argparse
import os
import sys
import datetime as dt
import time

import requests

import sslfix  # noqa: F401  (AVG TLS 검사 대응 — 모듈 주석 참조)
from config import (GFS_STEPS, GFS_VARS, GFS_LEVELS,
                    LON_MIN, LON_MAX, LAT_MIN, LAT_MAX, DATA_DIR)

BASE = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"


def build_url(ymd: str, hh: str, step: int) -> str:
    params = [
        f"dir=%2Fgfs.{ymd}%2F{hh}%2Fatmos",
        f"file=gfs.t{hh}z.pgrb2.0p25.f{step:03d}",
    ]
    params += [f"var_{v}=on" for v in GFS_VARS]
    params += [f"lev_{lv}=on" for lv in GFS_LEVELS]
    params += [
        "subregion=",
        f"leftlon={LON_MIN}", f"rightlon={LON_MAX}",
        f"toplat={LAT_MAX}", f"bottomlat={LAT_MIN}",
    ]
    return BASE + "?" + "&".join(params)


def probe_f000(ymd: str, hh: str, session: requests.Session) -> bytes | None:
    """해당 런의 f000을 받아 가용 여부 판정. 받은 내용을 반환해 본 수신에서 재사용."""
    try:
        r = session.get(build_url(ymd, hh, 0), timeout=60)
        if r.status_code == 200 and len(r.content) > 1000:
            return r.content
    except requests.RequestException:
        pass
    return None


def find_latest_run(session: requests.Session) -> tuple[str, str, bytes]:
    """지금 시각 기준으로 최근 런부터 역순 탐색. (ymd, hh, f000 내용) 반환."""
    now = dt.datetime.now(dt.timezone.utc)
    candidates = []
    for back_h in range(0, 48, 6):
        t = now - dt.timedelta(hours=back_h)
        hh = f"{(t.hour // 6) * 6:02d}"
        candidates.append((t.strftime("%Y%m%d"), hh))
    seen = set()
    for ymd, hh in candidates:
        if (ymd, hh) in seen:
            continue
        seen.add((ymd, hh))
        f000 = probe_f000(ymd, hh, session)
        if f000 is not None:
            return ymd, hh, f000
        time.sleep(0.5)
    raise RuntimeError("최근 48시간 내 가용 GFS 런을 찾지 못했습니다")


def fetch(ymd: str | None = None, hh: str | None = None) -> str:
    session = requests.Session()
    f000_cache = None
    if ymd is None or hh is None:
        ymd, hh, f000_cache = find_latest_run(session)
    print(f"[GFS] 수신 대상 런: {ymd} {hh}Z")

    os.makedirs(DATA_DIR, exist_ok=True)
    target = os.path.join(DATA_DIR, f"gfs_0p25_{ymd}{hh}.grib2")
    if os.path.exists(target) and os.path.getsize(target) > 0:
        print(f"[GFS] 이미 수신됨: {target}")
        return target

    tmp = target + ".part"
    n_ok, n_fail = 0, 0
    with open(tmp, "wb") as f:
        for step in GFS_STEPS:
            if step == 0 and f000_cache is not None:
                f.write(f000_cache)
                n_ok += 1
                continue
            url = build_url(ymd, hh, step)
            ok = False
            for attempt in range(3):
                try:
                    r = session.get(url, timeout=120)
                    if r.status_code == 200 and len(r.content) > 1000:
                        f.write(r.content)
                        ok = True
                        break
                except requests.RequestException:
                    pass
                time.sleep(2 * (attempt + 1))
            if ok:
                n_ok += 1
            else:
                n_fail += 1
                print(f"[GFS]  f{step:03d} 수신 실패 (건너뜀)")
            # NOMADS 접속 제한(분당 요청 수) 회피
            time.sleep(0.5)

    if n_ok == 0:
        os.remove(tmp)
        raise RuntimeError("GFS 스텝을 하나도 받지 못했습니다")
    os.replace(tmp, target)
    size_mb = os.path.getsize(target) / 1e6
    print(f"[GFS] 수신 완료: {target} ({size_mb:.1f} MB, 성공 {n_ok} / 실패 {n_fail} 스텝)")
    return target


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", nargs=2, metavar=("YYYYMMDD", "HH"), default=None,
                   help="런 지정 (예: --run 20260813 00). 생략 시 최신 런 자동 탐지")
    args = p.parse_args()
    ymd, hh = (args.run if args.run else (None, None))
    try:
        path = fetch(ymd, hh)
        print(path)
    except Exception as e:
        print(f"[GFS] 수신 실패: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
