# -*- coding: utf-8 -*-
"""
M4: FMI CloudCast 파인튜닝 모델 추론 (겨울 보완 게이트용).

규격은 코랩 노트북(dl/finetune_cloudcast_gk2a.ipynb)과 동일해야 함:
  · 입력 512², 운량 0..1, 채널 = [hist4(10분 간격) | 태양고도 | leadtime onehot]
  · onehot k → +10*(k+1)분 예측. +120분 초과는 창 재귀(k=8..11 예측 4장이 새 hist)
  · 출력은 벤치 격자(N_PIX, 기본 450)로 리사이즈해 반환 — 채점 조건 동일화

사용: nowcast_bench.py --dl (dl/gk2a_finetuned SavedModel 필요)
"""
import datetime as dt
import math
import os

import numpy as np
import cv2

from dl_dataset import load_ca_native
from nowcast_bench import CLA_DIR, N_PIX

MODEL_DIR = os.path.join("dl", "gk2a_finetuned")
SIZE = 512
STEP = 10  # 분

# 노트북 3)과 동일한 근사 위경도 (태양고도 채널)
_LATS = np.linspace(46.0, 29.7, SIZE)[:, None] * np.ones((1, SIZE))
_LONS = np.ones((SIZE, 1)) * np.linspace(113.0, 139.5, SIZE)[None, :]


def _sun(t: dt.datetime) -> np.ndarray:
    doy = t.timetuple().tm_yday
    decl = -23.44 * math.cos(math.radians(360 / 365 * (doy + 10)))
    hour = t.hour + t.minute / 60
    ha = (hour * 15 - 180) + _LONS
    s = (np.sin(np.radians(_LATS)) * math.sin(math.radians(decl)) +
         np.cos(np.radians(_LATS)) * math.cos(math.radians(decl)) * np.cos(np.radians(ha)))
    return ((s + 1) / 2).astype(np.float32)


class DLNowcaster:
    def __init__(self):
        import tensorflow as tf  # 지연 임포트 (--dl 시에만)
        self.model = tf.keras.models.load_model(MODEL_DIR, compile=False)
        self.n_ch = int(self.model.inputs[0].shape[-1])
        self.n_lc = max(0, self.n_ch - 5)
        print(f"[M4] 모델 로드: 채널 {self.n_ch} (leadtime {self.n_lc})")

    def _frame(self, stamp: str) -> np.ndarray | None:
        path = os.path.join(CLA_DIR, f"{stamp}.nc")
        if not os.path.exists(path):
            return None
        ca = load_ca_native(path)
        if ca is None:
            return None
        small = cv2.resize(ca, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
        return np.nan_to_num(small, nan=50.0).astype(np.float32) / 100.0

    def _step(self, hist: list[np.ndarray], base_t: dt.datetime, k: int) -> np.ndarray:
        tgt = base_t + dt.timedelta(minutes=STEP * (k + 1))
        ch = hist + [_sun(tgt)]
        if self.n_lc:
            oh = np.zeros((SIZE, SIZE, self.n_lc), np.float32)
            oh[..., min(k, self.n_lc - 1)] = 1.0
            x = np.concatenate([np.stack(ch, -1), oh], -1)
        else:
            x = np.stack(ch, -1)
        y = self.model.predict(x[None], verbose=0)[0, ..., 0]
        return np.clip(y.astype(np.float32), 0, 1)

    def predict(self, issue: dt.datetime, leads_min: list[int]) -> dict[int, np.ndarray] | None:
        """발령시각(UTC naive) → {lead: 벤치격자 %장}. hist 결측 시 None."""
        hist = []
        for i in range(3, -1, -1):
            f = self._frame((issue - dt.timedelta(minutes=STEP * i)).strftime("%Y%m%d%H%M"))
            if f is None:
                return None
            hist.append(f)

        span = STEP * self.n_lc if self.n_lc else 120  # 창 하나가 커버하는 리드(분)
        out: dict[int, np.ndarray] = {}
        base_t, base_off = issue, 0
        while base_off < max(leads_min):
            in_win = [m for m in leads_min if base_off < m <= base_off + span]
            for m in in_win:
                k = (m - base_off) // STEP - 1
                out[m] = self._step(hist, base_t, k)
            if base_off + span < max(leads_min):     # 창 전진: 마지막 4스텝 예측이 새 hist
                hist = [self._step(hist, base_t, k)
                        for k in range(self.n_lc - 4, self.n_lc)]
                base_t += dt.timedelta(minutes=span)
                base_off += span
            else:
                break
        return {m: cv2.resize(f * 100.0, (N_PIX, N_PIX), interpolation=cv2.INTER_AREA)
                for m, f in out.items()}
