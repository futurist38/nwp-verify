# -*- coding: utf-8 -*-
"""사이트용 배경 지도 1회 생성 — site/basemap.json (커밋 대상).

관측 지도를 이미지가 아니라 데이터로 그리기 위한 밑그림(2026-08-27).
해안선·시도 경계를 plot_obsmap과 같은 람베르트 투영으로 변환해 SVG 경로로 굳혀 둔다.
한 번 만들면 바뀌지 않으므로 매 배포마다 다시 만들 필요가 없다.

사용: python make_basemap.py
"""
import json
import os

import numpy as np
from pyproj import CRS, Transformer

import sslfix  # noqa: F401  (Natural Earth 내려받기 — AVG TLS 대응)
import cartopy.feature as cfeature
from shapely.geometry import box
from shapely.ops import transform as shp_transform

import mapviz
from config import BASE_DIR

OUT = os.path.join(BASE_DIR, "site", "basemap.json")
SIMPLIFY_M = 700          # 단순화 허용오차(m) — 화면 1px보다 작게 유지
VIEW = 1000               # viewBox 한 변


def main():
    lcc = CRS.from_proj4("+proj=lcc +lat_1=30 +lat_2=60 +lat_0=36 +lon_0=127.5 "
                         "+x_0=0 +y_0=0 +ellps=WGS84")
    to_lcc = Transformer.from_crs(CRS.from_epsg(4326), lcc, always_xy=True).transform
    clip = box(*[mapviz.EXT[0], mapviz.EXT[2], mapviz.EXT[1], mapviz.EXT[3]])

    layers = {}
    for name, feat in (("coast", cfeature.COASTLINE.with_scale("10m")),
                       ("admin", cfeature.NaturalEarthFeature(
                           "cultural", "admin_1_states_provinces_lines", "10m",
                           facecolor="none"))):
        segs = []
        for geom in feat.geometries():
            g = geom.intersection(clip)
            if g.is_empty:
                continue
            g = shp_transform(to_lcc, g).simplify(SIMPLIFY_M)
            for part in (g.geoms if hasattr(g, "geoms") else [g]):
                xy = np.asarray(part.coords) if part.geom_type == "LineString" \
                    else np.asarray(part.exterior.coords)
                if len(xy) >= 2:
                    segs.append(xy)
        layers[name] = segs
        print(f"[basemap] {name}: {len(segs)}선분")

    allxy = np.vstack([s for segs in layers.values() for s in segs])
    x0, y0 = allxy[:, 0].min(), allxy[:, 1].min()
    x1, y1 = allxy[:, 0].max(), allxy[:, 1].max()
    span = max(x1 - x0, y1 - y0)
    # 화면 좌표(0~VIEW, y 아래로 증가)로 정규화 — 지점 좌표도 같은 식을 쓴다
    def to_view(x, y):
        return ((x - x0) / span * VIEW, (y1 - y) / span * VIEW)

    paths = {}
    for name, segs in layers.items():
        out = []
        for xy in segs:
            vx, vy = to_view(xy[:, 0], xy[:, 1])
            out.append("M" + "L".join(f"{a:.1f} {b:.1f}" for a, b in zip(vx, vy)))
        paths[name] = " ".join(out)

    data = {"view": VIEW,
            "w": round((x1 - x0) / span * VIEW, 1),
            "h": round((y1 - y0) / span * VIEW, 1),
            "proj": {"x0": x0, "y1": y1, "span": span},
            "paths": paths}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"[basemap] 저장: {OUT} ({os.path.getsize(OUT) / 1024:.0f}KB)")


if __name__ == "__main__":
    main()
