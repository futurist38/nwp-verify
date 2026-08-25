# -*- coding: utf-8 -*-
"""
GK2A(천리안2A) L2 산출물 수신 — 기상청 API허브 typ05.

실측 확정 (2026-08-23):
  · 호스트 apihub-pub만 일반키 허용 (typ01/05/06 공통 함정)
  · URL: /api/typ05/api/GK2A/LE2/{산출물}/{영역}/data?date=yyyymmddHHMM(UTC)
    목록: .../dataList?sDate=&eDate=&format=json  (KO 2분, EA 10분 간격)
  · CLA(구름분석) KO: NetCDF4, 900×900, 2km, LCC(30/60, 원점 38N/126E,
    upper_left = (-899000, +899000) m, pixel 2000m)
  · 변수 CA(cloud amount): uint16, scale 0.01, _FillValue 65535,
    **units 빈값이지만 실값은 0~1 비율** (×100 → %) — KIM 운량과 같은 함정
  · CF(cloud fraction)는 units=% (scale 0.01 → 0~100). CT(운형)는 야간 미산출
  · 제공 지연 ~8분. 파일 ~0.8MB/시각
  · netCDF4 C 라이브러리는 한글 경로 불가 → 판독은 h5netcdf 엔진 사용

저장: data/gk2a/cla_ko/{yyyymmddHHMM}.nc  (gitignore)
사용:
    python fetch_gk2a.py --probe
    python fetch_gk2a.py --from 2026-08-15 --to 2026-08-21 --step 10
"""
import argparse
import datetime as dt
import os
import re
import time

import requests

import sslfix  # noqa: F401
from config import BASE_DIR, DATA_DIR

HOST = "https://apihub-pub.kma.go.kr/api/typ05/api/GK2A"
GK2A_DIR = os.path.join(DATA_DIR, "gk2a")


def _key() -> str:
    k = os.environ.get("KMA_AUTH_KEY")
    if k:
        return k.strip()
    m = re.search(r"KMA_AUTH_KEY\s*=\s*(\S+)",
                  open(os.path.join(BASE_DIR, ".env"), encoding="utf-8").read())
    return m.group(1)


def data_list(prod: str, area: str, s: dt.datetime, e: dt.datetime) -> list[str]:
    for attempt in range(3):   # 타임아웃 1회로 전체 수집이 죽지 않도록 재시도
        try:
            r = requests.get(f"{HOST}/LE2/{prod}/{area}/dataList",
                             params={"sDate": s.strftime("%Y%m%d%H%M"),
                                     "eDate": e.strftime("%Y%m%d%H%M"),
                                     "format": "json", "authKey": _key()}, timeout=120)
            return sorted(i["item"] for i in r.json().get("list", []))
        except Exception as ex:
            print(f"[GK2A] dataList 실패({attempt + 1}/3): {ex}")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("dataList 3회 실패")


def fetch_one(prod: str, area: str, stamp: str, out_dir: str) -> bool:
    os.makedirs(out_dir, exist_ok=True)   # 단독 호출(Actions 러너 빈 체크아웃) 대비
    path = os.path.join(out_dir, f"{stamp}.nc")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return True
    for attempt in range(3):
        try:
            r = requests.get(f"{HOST}/LE2/{prod}/{area}/data",
                             params={"date": stamp, "authKey": _key()},
                             timeout=300)
            if r.content[:4] != b"\x89HDF":
                raise ValueError(f"NetCDF 아님: {r.content[:60]!r}")
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(r.content)
            os.replace(tmp, path)
            return True
        except Exception as ex:
            print(f"[GK2A] {stamp} 실패({attempt + 1}/3): {ex}")
            time.sleep(3 * (attempt + 1))
    return False


def fetch_range(prod: str, area: str, t0: dt.datetime, t1: dt.datetime,
                step_min: int, minutes: list[str] | None = None):
    """기간 수신 (UTC 기준). 실패 시각은 누락으로 목록화 (추정 보충 금지).
    minutes 지정 시(예: ['00','30','50']) 해당 분의 스탬프만 수집 —
    매시 발령 벤치마크에는 t-10(:50)·t(:00)·반시간 리드(:30)만 필요."""
    out_dir = os.path.join(GK2A_DIR, f"{prod.lower()}_{area.lower()}")
    os.makedirs(out_dir, exist_ok=True)
    want = []
    t = t0
    while t <= t1:
        if minutes is None or t.strftime("%M") in minutes:
            want.append(t.strftime("%Y%m%d%H%M"))
        t += dt.timedelta(minutes=step_min if minutes is None else 2)

    # 실제 제공 목록과 교차 (2분 제품에서 10분 샘플 등)
    avail = set()
    day = t0
    while day <= t1:
        avail |= set(data_list(prod, area, day,
                               min(day + dt.timedelta(days=1), t1)))
        day += dt.timedelta(days=1)
        time.sleep(0.2)

    missing_src = [w for w in want if w not in avail]
    targets = [w for w in want if w in avail]
    print(f"[GK2A] {prod}/{area} 대상 {len(want)}시각 중 제공 {len(targets)}, "
          f"원천 결측 {len(missing_src)}")

    n_ok = n_fail = 0
    failed = []
    for i, stamp in enumerate(targets, 1):
        if fetch_one(prod, area, stamp, out_dir):
            n_ok += 1
        else:
            n_fail += 1
            failed.append(stamp)
        if i % 50 == 0:
            print(f"[GK2A] {i}/{len(targets)} (성공 {n_ok})")
        time.sleep(0.15)

    miss_path = os.path.join(out_dir, "_missing.txt")
    with open(miss_path, "w", encoding="utf-8") as f:
        f.write("# 원천 미제공\n" + "\n".join(missing_src)
                + "\n# 수신 실패\n" + "\n".join(failed) + "\n")
    print(f"[GK2A] 완료: 수신 {n_ok}, 실패 {n_fail} — 누락 목록 {miss_path}")


def probe():
    now = dt.datetime.now(dt.timezone.utc)
    items = data_list("CLA", "KO", now - dt.timedelta(hours=1), now)
    latest = max(items)
    lag = (now - dt.datetime.strptime(latest, "%Y%m%d%H%M")
           .replace(tzinfo=dt.timezone.utc)).total_seconds() / 60
    print(f"[GK2A] CLA/KO 최근 1시간 {len(items)}건, 최신 {latest} (지연 {lag:.0f}분)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    p.add_argument("--from", dest="t0", help="YYYY-MM-DD (KST 자정 기준)")
    p.add_argument("--to", dest="t1", help="YYYY-MM-DD (KST, 해당일 끝까지)")
    p.add_argument("--prod", default="CLA")
    p.add_argument("--area", default="KO")
    p.add_argument("--step", type=int, default=10, help="샘플 간격(분)")
    p.add_argument("--minutes", default=None,
                   help="수집할 분 목록 (예: 00,30,50) — 벤치마크 절약 모드")
    args = p.parse_args()

    if args.probe:
        probe()
        return
    # KST 일자 경계 → UTC
    t0 = dt.datetime.fromisoformat(args.t0) - dt.timedelta(hours=9)
    t1 = dt.datetime.fromisoformat(args.t1) + dt.timedelta(hours=24 - 9, minutes=-args.step)
    minutes = args.minutes.split(",") if args.minutes else None
    fetch_range(args.prod, args.area, t0, t1, args.step, minutes)


if __name__ == "__main__":
    main()
