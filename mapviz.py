# -*- coding: utf-8 -*-
"""
지도 표출 공용 (관측 실황·예보 변화 등 지점 자료를 한반도 지도에 그릴 때).

plot_obsmap.py 에만 있던 투영·보간·바탕 그리기를 공용화 (2026-08-26).
지점 자료를 지도로 만드는 스크립트가 둘 이상이 되면서 같은 코드가 갈라지는 것을 막는다.

실측 확정 사항(그대로 유지):
  · 10m 해상도 OCEAN 마스크 — 50m은 부산 등 복잡 해안에서 육지를 침범
  · linear 보간 + 볼록껍질 밖은 nearest 로 메움(연안 미채색 해결)
  · 단, 최근접 지점 거리 > MASK_DEG 인 격자는 그리지 않음 (북한 등 근거 없는 추정 금지)
"""
import numpy as np
from scipy.interpolate import griddata
from scipy.spatial import cKDTree

EXT = [125.0, 130.0, 33.0, 38.8]     # 표출 영역 (lon0, lon1, lat0, lat1)
GRID_RES = 0.05                       # 보간 격자 간격(도)
MASK_DEG = 0.55                       # 이 거리를 넘으면 미채색(~55km)

try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    HAS_CARTOPY = True
    ADMIN1 = cfeature.NaturalEarthFeature(
        "cultural", "admin_1_states_provinces_lines", "10m", facecolor="none")
except Exception:                     # cartopy 없으면 경위도 평면으로 대체
    HAS_CARTOPY = False
    ADMIN1 = None


def proj():
    if not HAS_CARTOPY:
        return None
    return ccrs.LambertConformal(central_longitude=127.5, standard_parallels=(30, 60))


def interp(lons, lats, vals, ext=EXT, res=GRID_RES, mask_deg=MASK_DEG):
    """지점 → 격자. 반환 (gx, gy, gz), 근거 없는 외삽 구역은 NaN."""
    lons, lats, vals = np.asarray(lons), np.asarray(lats), np.asarray(vals)
    gx, gy = np.meshgrid(np.arange(ext[0], ext[1], res),
                         np.arange(ext[2], ext[3], res))
    gz = griddata((lons, lats), vals, (gx, gy), method="linear")
    gz_near = griddata((lons, lats), vals, (gx, gy), method="nearest")
    gz = np.where(np.isnan(gz), gz_near, gz)
    dist, _ = cKDTree(np.c_[lons, lats]).query(np.c_[gx.ravel(), gy.ravel()])
    return gx, gy, np.where(dist.reshape(gx.shape) > mask_deg, np.nan, gz)


def make_axes(fig, ext=EXT):
    """지도 축 생성 → (ax, transform_kwargs). cartopy 없으면 평면 축."""
    if HAS_CARTOPY:
        ax = fig.add_subplot(1, 1, 1, projection=proj())
        ax.set_extent(ext, crs=ccrs.PlateCarree())
        return ax, {"transform": ccrs.PlateCarree()}
    ax = fig.add_subplot(1, 1, 1)
    ax.set_xlim(ext[0], ext[1])
    ax.set_ylim(ext[2], ext[3])
    ax.set_aspect(1.0 / np.cos(np.deg2rad(36)))
    return ax, {}


def basemap(ax):
    """바다·해안선·시도 경계 (자료 위에 덮어 그린다)."""
    if not HAS_CARTOPY:
        return
    ax.add_feature(cfeature.OCEAN.with_scale("10m"), facecolor="#eef1f5", zorder=2)
    ax.coastlines(resolution="10m", linewidth=0.6, zorder=3)
    ax.add_feature(ADMIN1, edgecolor="#777", linewidth=0.5, zorder=3)


def label_point(ax, lon, lat, text, tf, fontsize=12):
    """흰 테두리 라벨 — 어떤 배경색 위에서도 읽히게."""
    import matplotlib.patheffects as pe
    ax.plot(lon, lat, "o", ms=5, mfc="white", mec="black", zorder=4, **tf)
    ax.text(lon + 0.06, lat - 0.06, text, fontsize=fontsize, weight="bold",
            va="top", zorder=4,
            path_effects=[pe.withStroke(linewidth=3, foreground="white")], **tf)
