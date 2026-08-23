# -*- coding: utf-8 -*-
"""
DL(겨울 보완) 학습 데이터셋 빌더 — GK2A CLA(CA) → 일 단위 npz 샤드.

FMI CloudCast 파인튜닝용 (2026-08-23 게이트: 12월 학습 / 1월 검증):
  · 입력 규격: 512×512, 유효운량 0..1 (FMI gributils: data/100) → 우리 CA%도 /100
  · 저장은 uint8(0..100, 255=결측)로 압축 — 학습 시 /100
  · 900×900(2km) → cv2.INTER_AREA 512×512 (~3.5km)

산출: dl/dataset/YYYYMMDD.npz {stamps: [YYYYMMDDHHMM...], frames: uint8 (N,512,512)}
사용: python dl_dataset.py --from 2025-12-01 --to 2026-01-31
"""
import argparse
import datetime as dt
import glob
import os

import numpy as np
import cv2

from nowcast_bench import CLA_DIR  # 동일 로더 상수 재사용
import xarray as xr

OUT_DIR = os.path.join("dl", "dataset")
SIZE = 512


def load_ca_native(path: str) -> np.ndarray | None:
    try:
        ds = xr.open_dataset(path, engine="h5netcdf", decode_cf=False)
        raw = ds["CA"].values.astype(np.float32)
        ds.close()
    except Exception:
        return None
    raw[raw == 65535] = np.nan
    return np.clip(raw * 0.01 * 100.0, 0, 100)   # %


def build_day(ymd: str) -> int:
    files = sorted(glob.glob(os.path.join(CLA_DIR, f"{ymd}????.nc")))
    stamps, frames = [], []
    for f in files:
        ca = load_ca_native(f)
        if ca is None:
            continue
        small = cv2.resize(ca, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
        u8 = np.where(np.isnan(small), 255, np.round(small)).astype(np.uint8)
        stamps.append(os.path.basename(f)[:-3])
        frames.append(u8)
    if not frames:
        return 0
    os.makedirs(OUT_DIR, exist_ok=True)
    np.savez_compressed(os.path.join(OUT_DIR, f"{ymd}.npz"),
                        stamps=np.array(stamps), frames=np.stack(frames))
    return len(frames)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="d0", required=True)
    p.add_argument("--to", dest="d1", required=True)
    args = p.parse_args()
    d = dt.date.fromisoformat(args.d0)
    d1 = dt.date.fromisoformat(args.d1)
    total = 0
    while d <= d1:
        n = build_day(f"{d:%Y%m%d}")
        total += n
        if n:
            print(f"[DL셋] {d}: {n}프레임")
        d += dt.timedelta(days=1)
    print(f"[DL셋] 총 {total}프레임 → {OUT_DIR}")


if __name__ == "__main__":
    main()
