"""Readable cloud-layer colours; this is a visual composite, not total cloud cover."""
import numpy as np

# Vivid orange-brown / magenta / cyan, retaining weighted mixing so overlaps
# cannot accumulate subtractive darkness. Percentage bars use this same mapping.
LAYER_COLORS = np.array([[0.88, 0.48, 0.06],
                         [0.84, 0.10, 0.67],
                         [0.00, 0.57, 0.76]])
# A distinct emerald hue separates three-layer cloud from the purple mid+high
# mixture and the muted olive low+high mixture.
THREE_LAYER_COLOR = np.array([0.08, 0.66, 0.20])
MISSING_COLOR = np.array([0.90, 0.90, 0.90])
LEGEND_LAYERS = [
    ("맑음", (0, 0, 0)), ("하층", (100, 0, 0)),
    ("중층", (0, 100, 0)), ("상층", (0, 0, 100)),
    ("하층+중층", (100, 100, 0)), ("하층+상층", (100, 0, 100)),
    ("중층+상층", (0, 100, 100)), ("하층+중층+상층", (100, 100, 100)),
]


def cloud_composite(lcc, mcc, hcc):
    """Percentages -> RGB, with bounded brightness even at three-layer overcast.

    One/two-layer hue is a cloud-fraction-weighted mean of layer colours.
    When all three contribute, a smooth minimum/maximum ratio shifts the hue
    toward emerald. A trace third layer does not abruptly recolour a cloud.
    Colour strength follows the largest layer fraction, NOT their sum or a
    total-cloud estimate; layer fractions do not determine physical overlap.
    Missing input in any layer is grey rather than being mistaken for clear sky.
    """
    layers = np.stack(np.broadcast_arrays(lcc, mcc, hcc), axis=-1).astype(float)
    valid = np.isfinite(layers).all(axis=-1)
    cover = np.clip(np.nan_to_num(layers, nan=0, posinf=0, neginf=0) / 100, 0, 1)
    total = cover.sum(axis=-1, keepdims=True)
    weights = np.divide(cover, total, out=np.zeros_like(cover), where=total > 0)
    mixed = weights @ LAYER_COLORS
    maximum = cover.max(axis=-1, keepdims=True)
    ratio = np.divide(cover.min(axis=-1, keepdims=True), maximum,
                      out=np.zeros_like(maximum), where=maximum > 0)
    triple_weight = ratio * ratio * (3 - 2 * ratio)
    mixed = (1 - triple_weight) * mixed + triple_weight * THREE_LAYER_COLOR
    strength = 0.96 * maximum
    rgb = 1 - strength * (1 - mixed)
    return np.where(valid[..., None], rgb, MISSING_COLOR)
