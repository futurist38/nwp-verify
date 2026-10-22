"""Shared contract for comparable, native-grid solar radiation maps."""

SOLAR_WINDOW_H = 3
SOLAR_MAX_STEP_H = 120
SOLAR_DPI = 150
SOLAR_LEVELS = tuple(range(0, 1001, 10))
SOLAR_COLORS = ("#f1f4f6", "#b7dce0", "#5db8c0", "#e9df88",
                "#f8b74e", "#ee7736", "#c5352d")


def is_solar_step(step_h):
    return 0 < step_h <= SOLAR_MAX_STEP_H and step_h % SOLAR_WINDOW_H == 0


def solar_field(field, step_h):
    """Keep native samples; reject non-3h means and wholly missing frames."""
    import numpy as np

    if not is_solar_step(step_h) or "win_h" not in field.coords:
        return None
    if float(field.win_h) != SOLAR_WINDOW_H:
        return None
    values = np.ma.masked_invalid(field.values)
    if values.ndim != 2 or min(values.shape) < 2 or values.count() == 0:
        return None
    # Clamp finite negative deaccumulation noise, preserving missing cells and night zeroes.
    return np.ma.maximum(values, 0)


def draw_solar(fig, ax, longitude, latitude, values):
    from matplotlib.colors import LinearSegmentedColormap

    cmap = LinearSegmentedColormap.from_list("solar", SOLAR_COLORS, N=256)
    cmap.set_over("#8f1d25")
    ax.set_facecolor("#dedede")  # Missing areas are distinct from near-white night zeroes.
    filled = ax.contourf(longitude, latitude, values, levels=SOLAR_LEVELS,
                         cmap=cmap, vmin=0, vmax=1000, extend="max")
    fig.colorbar(filled, ax=ax, shrink=0.8, ticks=range(0, 1001, 100),
                 label="일사량 · 하향 단파복사 3시간 평균 (W/m²)")
    return filled
