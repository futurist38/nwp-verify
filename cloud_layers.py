"""Readable cloud-layer colours; this is a visual composite, not total cloud cover."""
import numpy as np

# Preserve the established brown / magenta / cyan layer identities.
LAYER_COLORS = np.array([[0.75, 0.53, 0.33],
                         [0.71, 0.36, 0.65],
                         [0.24, 0.61, 0.67]])
MISSING_COLOR = np.array([0.90, 0.90, 0.90])
LEGEND_LAYERS = [
    ("맑음", (0, 0, 0)), ("저층", (100, 0, 0)),
    ("중층", (0, 100, 0)), ("상층", (0, 0, 100)),
    ("저+중", (100, 100, 0)), ("저+상", (100, 0, 100)),
    ("중+상", (0, 100, 100)), ("저+중+상", (100, 100, 100)),
]


def cloud_composite(lcc, mcc, hcc):
    """Percentages -> RGB, with bounded brightness even at three-layer overcast.

    Hue is a cloud-fraction-weighted mean of layer colours. Colour strength
    follows the largest layer fraction, NOT their sum or a total-cloud estimate.
    Missing input in any layer is grey rather than being mistaken for clear sky.
    """
    layers = np.stack(np.broadcast_arrays(lcc, mcc, hcc), axis=-1).astype(float)
    valid = np.isfinite(layers).all(axis=-1)
    cover = np.clip(np.nan_to_num(layers, nan=0, posinf=0, neginf=0) / 100, 0, 1)
    total = cover.sum(axis=-1, keepdims=True)
    weights = np.divide(cover, total, out=np.zeros_like(cover), where=total > 0)
    mixed = weights @ LAYER_COLORS
    strength = 0.8 * cover.max(axis=-1, keepdims=True)
    rgb = 1 - strength * (1 - mixed)
    return np.where(valid[..., None], rgb, MISSING_COLOR)
