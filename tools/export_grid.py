# -*- coding: utf-8 -*-
"""
브라우저 렌더링 시제품용 격자 자료 추출 (2026-09-08). 동아시아(100~150E, 20~55N) 0.25° 격자를 정수(×10)로 JSON.

  입력: fetch_upper.py 산출(upper_ecmwf_sfc/pl/pl2_{run}.grib2, upper_gfs_{run}.grib2)
  출력: <out>/grid/{model}_{run}.json
        {model, run, lat0, lat1, lon0, lon1, ny, nx, steps:[...],
         fields:{"msl":{step:[int×10 hPa]}, "t2m":{...℃×10}, "gh500":{...m}, "t850":{...℃×10}, "gh850":{...m}}}
        + <out>/grid/coast.json  (Natural Earth 50m 해안선, 영역 절단, [[lon,lat],...] 폴리라인 목록)
사용: python tools/export_grid.py --run 2026090706 --out <site_dir>
"""
import argparse
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATA_DIR  # noqa: E402
from plot_upper import read_fields  # noqa: E402
from fetch_upper import UP_LON_MIN, UP_LON_MAX, UP_LAT_MIN, UP_LAT_MAX  # noqa: E402

WANT = {("msl", "meanSea", 0), ("prmsl", "meanSea", 0), ("2t", "heightAboveGround", 2),
        ("gh", "isobaricInhPa", 500), ("t", "isobaricInhPa", 850), ("gh", "isobaricInhPa", 850)}


def q(a: np.ndarray, scale: float) -> list:
    return [int(round(v * scale)) for v in a.flatten()]


def export_model(model: str, paths: list[str], out_dir: str) -> str | None:
    merged, lats, lons, run = {}, None, None, None
    for p in paths:
        f, la, lo, r = read_fields(p, WANT)
        if f:
            merged.update(f); lats, lons, run = la, lo, r
    if not merged:
        return None
    fields = {}
    def put(name, key, scale, conv=lambda a: a):
        if key in merged:
            fields[name] = {str(st): q(conv(a), scale) for st, a in sorted(merged[key].items())}
    put("msl", ("msl", "meanSea", 0), 10, lambda a: a / 100.0)
    put("msl", ("prmsl", "meanSea", 0), 10, lambda a: a / 100.0)
    put("t2m", ("2t", "heightAboveGround", 2), 10, lambda a: a - 273.15)
    put("gh500", ("gh", "isobaricInhPa", 500), 1)
    put("gh850", ("gh", "isobaricInhPa", 850), 1)
    put("t850", ("t", "isobaricInhPa", 850), 10, lambda a: a - 273.15)
    steps = sorted({int(s) for f in fields.values() for s in f}, key=int)
    out = {"model": model, "run": run.strftime("%Y%m%d%H"), "lat0": float(lats[0]), "lat1": float(lats[-1]),
           "lon0": float(lons[0]), "lon1": float(lons[-1]), "ny": len(lats), "nx": len(lons), "steps": steps, "fields": fields}
    os.makedirs(os.path.join(out_dir, "grid"), exist_ok=True)
    fp = os.path.join(out_dir, "grid", f"{model.lower()}_{out['run']}.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"[grid] {model} {out['run']}: {len(steps)}스텝 {list(fields)} → {os.path.getsize(fp) / 1e6:.1f}MB")
    return fp


def export_coast(out_dir: str) -> None:
    from cartopy.io import shapereader
    from shapely.geometry import box
    dom = box(UP_LON_MIN, UP_LAT_MIN, UP_LON_MAX, UP_LAT_MAX)
    lines = []
    for src, tol in (("coastline", 0.02), ("admin_0_boundary_lines_land", 0.03)):
        cat = "physical" if src == "coastline" else "cultural"
        for g in shapereader.Reader(shapereader.natural_earth("50m", cat, src)).geometries():
            gi = g.intersection(dom)
            if gi.is_empty:
                continue
            gi = gi.simplify(tol)
            parts = gi.geoms if hasattr(gi, "geoms") else [gi]
            for ln in parts:
                if ln.geom_type == "LineString":
                    lines.append({"k": src[:5], "pts": [[round(x, 3), round(y, 3)] for x, y in ln.coords]})
    with open(os.path.join(out_dir, "grid", "coast.json"), "w") as f:
        json.dump(lines, f, separators=(",", ":"))
    print(f"[grid] 해안선·국경 {len(lines)}개 폴리라인")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    os.makedirs(os.path.join(a.out, "grid"), exist_ok=True)
    ec = [f for f in (os.path.join(DATA_DIR, f"upper_ecmwf_{k}_{a.run}.grib2") for k in ("sfc", "pl", "pl2")) if os.path.exists(f)]
    if ec:
        export_model("ECMWF", ec, a.out)
    gf = os.path.join(DATA_DIR, f"upper_gfs_{a.run}.grib2")
    if os.path.exists(gf):
        export_model("GFS", [gf], a.out)
    export_coast(a.out)


if __name__ == "__main__":
    main()
