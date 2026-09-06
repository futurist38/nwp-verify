# -*- coding: utf-8 -*-
"""
GK2A 위성 일사(SWRAD, 하향 단파복사 DSR) — 하루 적산 지도 (2026-09-06).

실측 확정: typ05 GK2A/LE2/SWRAD/KO, NetCDF4 900×900 2km(CLA 와 같은 LCC 격자),
  변수 DSR(uint16, scale 0.1, W/m², _FillValue 65535), 10분 간격, 파일 1.5MB.
방법: 정시 파일(24장)만 받아 W/m² × 3600s 를 더한 뒤 MJ/m² 로. 정시 순간값의 시간 적분이므로
  10분 자료 전부를 쓴 값보다 거칠다(표출에 명시). 결측 시각은 건너뛰고 유효 시간 수를 제목에 적는다.
  아직 오지 않은 시각(당일)은 '지금까지의 적산'.
산출: output/YYYYMMDD/satsw/satsw_dsr_YYYYMMDD.png  (사이트 관측 탭 하단)
사용: python gk2a_swrad_daily.py [--date 2026-09-05]   (기본: 오늘 KST, 어제도 함께)
"""
import argparse
import datetime as dt
import os

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import sslfix  # noqa: F401
from config import OUT_DIR, DATA_DIR
from fetch_gk2a import fetch_one, data_list

SW_DIR = os.path.join(DATA_DIR, "gk2a", "swrad")
CITIES = [("서울", 37.571, 126.966), ("대전", 36.372, 127.372), ("대구", 35.878, 128.653),
          ("부산", 35.105, 129.032), ("광주", 35.173, 126.891), ("강릉", 37.751, 128.891)]

from matplotlib import font_manager as _fm
_inst = {f.name for f in _fm.fontManager.ttflist}
for _font in ["Malgun Gothic", "NanumGothic", "Noto Sans CJK KR"]:
    if _font in _inst:
        matplotlib.rc("font", family=_font)
        break


def load_dsr(path: str) -> np.ndarray | None:
    import netCDF4
    try:
        # netCDF4 는 윈도우에서 한글 경로를 못 연다(실측: Errno 22) → 바이트로 읽어 메모리 모드
        with open(path, "rb") as fh:
            ds = netCDF4.Dataset("mem.nc", mode="r", memory=fh.read())
        v = ds.variables["DSR"]
        v.set_auto_maskandscale(False)
        raw = v[:].astype(np.float32)
        fill = float(getattr(v, "_FillValue", 65535))
        sc = float(getattr(v, "scale_factor", 0.1))
        out = np.where(raw == fill, np.nan, raw * sc)
        ds.close()
        return out
    except Exception as e:
        print(f"[SWRAD] 판독 실패 {os.path.basename(path)}: {e}")
        return None


def daily_sum(day: dt.date) -> tuple[np.ndarray | None, int, list[str]]:
    """KST 일자의 정시 파일들을 받아 MJ/m² 적산. (합, 유효시간수, 사용 스탬프)"""
    t0 = dt.datetime.combine(day, dt.time(0)) - dt.timedelta(hours=9)      # KST 00 → UTC
    t1 = min(t0 + dt.timedelta(hours=23), dt.datetime.utcnow())
    if t1 < t0:
        return None, 0, []
    stamps = [s for s in data_list("SWRAD", "KO", t0, t1) if s.endswith("00")]
    total, n, used = None, 0, []
    for s in stamps:
        if not fetch_one("SWRAD", "KO", s, SW_DIR):
            continue
        f = load_dsr(os.path.join(SW_DIR, f"{s}.nc"))
        if f is None:
            continue
        f = np.nan_to_num(f, nan=0.0) * 3600.0 / 1e6       # W/m² × 1h → MJ/m²
        total = f if total is None else total + f
        n += 1; used.append(s)
    return total, n, used


def render(day: dt.date, total: np.ndarray, n: int, out_dir: str) -> str:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    proj = ccrs.LambertConformal(central_longitude=126, central_latitude=38, standard_parallels=(30, 60))
    fig = plt.figure(figsize=(7.4, 6.4))
    ax = fig.add_axes([0.04, 0.05, 0.86, 0.86], projection=proj)
    im = ax.imshow(total, transform=proj, origin="upper", extent=[-899000, 899000, -899000, 899000],
                   cmap="YlOrRd", vmin=0, vmax=30, interpolation="bilinear")
    ax.coastlines(resolution="10m", color="#333", linewidth=0.8)
    ax.add_feature(cfeature.STATES.with_scale("10m"), edgecolor="#333", linewidth=0.3, facecolor="none")
    # 대표 도시 값 (해당 격자점)
    import pyproj
    tr = pyproj.Transformer.from_crs("EPSG:4326", proj.proj4_init, always_xy=True)
    for name, lat, lon in CITIES:
        x, y = tr.transform(lon, lat)
        j = int(round((899000 - y) / 2000)); i = int(round((x + 899000) / 2000))
        if 0 <= j < total.shape[0] and 0 <= i < total.shape[1]:
            ax.text(x, y, f"{name} {total[j, i]:.1f}", transform=proj, fontsize=9, weight="bold",
                    path_effects=[matplotlib.patheffects.withStroke(linewidth=3, foreground="white")])
    cb = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
    cb.set_label("하향 단파복사 일 적산 (MJ/m²)")
    ax.set_title(f"GK2A 위성 일사(DSR) 하루 적산  {day:%m-%d} KST  — 정시 {n}시간 합산", fontsize=11)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"satsw_dsr_{day:%Y%m%d}.png")
    fig.savefig(out, dpi=100)
    plt.close(fig)
    return out


def make_day(day: dt.date) -> bool:
    total, n, used = daily_sum(day)
    if total is None or n == 0:
        print(f"[SWRAD] {day}: 자료 없음")
        return False
    out = render(day, total, n, os.path.join(OUT_DIR, f"{day:%Y%m%d}", "satsw"))
    print(f"[SWRAD] {day}: {n}시간 적산 → {out}")
    return True


def main():
    import matplotlib.patheffects  # noqa: F401  (render 에서 사용)
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=None, help="KST 일자 YYYY-MM-DD (생략: 어제+오늘)")
    args = p.parse_args()
    if args.date:
        make_day(dt.date.fromisoformat(args.date))
        return
    today = (dt.datetime.utcnow() + dt.timedelta(hours=9)).date()
    make_day(today - dt.timedelta(days=1))
    make_day(today)


if __name__ == "__main__":
    main()
