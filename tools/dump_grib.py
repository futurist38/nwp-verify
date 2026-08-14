# -*- coding: utf-8 -*-
"""
GRIB 전 메시지 인벤토리 덤프 — 브리프 2-1절 "실측 확정"용.

pip eccodes 휠에는 grib_ls CLI가 없을 수 있어 Python API로 덤프한다.

사용:
    python tools/dump_grib.py data/gfs_0p25_XXXX.grib2
"""
import sys
from collections import Counter

import eccodes


KEYS = ["shortName", "name", "typeOfLevel", "level", "stepType",
        "startStep", "endStep", "units", "dataDate", "dataTime"]


def dump(path: str):
    combos = Counter()
    rows = []
    with open(path, "rb") as f:
        while True:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                break
            row = {}
            for k in KEYS:
                try:
                    row[k] = eccodes.codes_get(gid, k)
                except Exception:
                    row[k] = "?"
            rows.append(row)
            combos[(row["shortName"], row["typeOfLevel"], row["level"],
                    row["stepType"], row["units"])] += 1
            eccodes.codes_release(gid)

    print(f"총 {len(rows)}개 메시지\n")
    print(f"{'shortName':<10} {'typeOfLevel':<28} {'level':>6} {'stepType':<8} {'units':<12} {'개수':>4}")
    print("-" * 75)
    for (sn, tol, lv, st, un), n in sorted(combos.items()):
        print(f"{sn:<10} {tol:<28} {lv:>6} {st:<8} {un:<12} {n:>4}")

    # 스텝 구간 상세 (avg/accum 변수의 적분 구간 확인용)
    print("\n[stepType != instant 메시지의 구간]")
    for r in rows:
        if r["stepType"] not in ("instant", "?"):
            print(f"  {r['shortName']:<8} {r['typeOfLevel']:<24} "
                  f"step {r['startStep']}-{r['endStep']}  ({r['stepType']})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("사용법: python tools/dump_grib.py <grib파일> [...]")
    for p in sys.argv[1:]:
        print(f"\n===== {p} =====")
        dump(p)
