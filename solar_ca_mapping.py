"""Issue-time CA -> GK2A DSR lookup experiment; no M4 weight changes.

The lookup transports a *statistical relationship* through M4's predicted CA.
It does not track individual cloud parcels or infer COT from CA.
"""
from dataclasses import dataclass
import calendar
import datetime as dt
import numpy as np


@dataclass
class CloudLookup:
    centers: np.ndarray
    means: np.ndarray
    counts: np.ndarray
    p10: np.ndarray
    p90: np.ndarray
    width: float

    def apply(self, cloud_percent):
        ca = np.asarray(cloud_percent, dtype=float)
        out = np.full(ca.shape, np.nan)
        valid = np.isfinite(ca) & (ca >= 0) & (ca <= 100)
        # Only populated bins and the intervals between adjacent populated bins
        # are supported. Large unobserved cloud ranges remain missing.
        for i, center in enumerate(self.centers):
            in_bin = valid & (np.abs(ca - center) <= self.width / 2)
            out[in_bin] = self.means[i]
            if i and center - self.centers[i - 1] <= self.width * 1.01:
                between = valid & (ca >= self.centers[i - 1]) & (ca <= center)
                out[between] = np.interp(ca[between], self.centers[i-1:i+1],
                                         self.means[i-1:i+1])
        return out.astype(np.float32)

    def records(self):
        return [dict(ca_percent=float(c), mean=float(m), count=int(n),
                     p10=float(lo), p90=float(hi))
                for c, m, n, lo, hi in zip(self.centers, self.means, self.counts,
                                           self.p10, self.p90)]


def fit_lookup(cloud_percent, target, mask=None, width=5.0, min_count=64):
    """Fit only issue-time pairs. NaNs are missing; zero DSR remains valid.

    An unconstrained bin mean avoids assuming a monotone relation before it is
    observed. Counts and p10/p90 expose ambiguity of DSR at the same cloud amount.
    """
    ca, y = np.asarray(cloud_percent), np.asarray(target)
    if ca.shape != y.shape or (mask is not None and np.shape(mask) != ca.shape):
        raise ValueError("CA, target and mask must share the same grid")
    if width <= 0 or 100 % width != 0 or min_count < 1:
        raise ValueError("width must divide 100; min_count must be positive")
    valid = np.isfinite(ca) & np.isfinite(y) & (ca >= 0) & (ca <= 100) & (y >= 0)
    if mask is not None:
        valid &= mask
    bins = np.floor(ca[valid] / width + 0.5).astype(int)
    vals = y[valid]
    rows = []
    for b in range(int(100 / width) + 1):
        v = vals[bins == b]
        if v.size >= min_count:
            rows.append((b * width, v.mean(), v.size, *np.quantile(v, [.1, .9])))
    if not rows:
        raise ValueError("No sufficiently populated issue-time CA/DSR bins")
    a = np.asarray(rows)
    return CloudLookup(a[:, 0], a[:, 1], a[:, 2].astype(int), a[:, 3], a[:, 4], width)


def solar_reference(when, lon, lat):
    """NOAA approximate solar geometry + Haurwitz reference GHI, W/m2.

    UTC required (naive timestamps mean UTC). Geometric rather than refracted
    zenith is used; experiment fitting/scoring excludes elevations <15 degrees.
    This simple reference is NOT an aerosol/water-vapor corrected clear-sky truth.
    NOAA: https://gml.noaa.gov/grad/solcalc/solareqns.PDF
    Haurwitz: https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.clearsky.haurwitz.html
    """
    if when.tzinfo is not None:
        when = when.astimezone(dt.timezone.utc)
    hour = when.hour + when.minute / 60 + when.second / 3600
    g = 2 * np.pi / (366 if calendar.isleap(when.year) else 365) * (
        when.timetuple().tm_yday - 1 + (hour - 12) / 24)
    eq = 229.18 * (.000075 + .001868 * np.cos(g) - .032077 * np.sin(g)
                   - .014615 * np.cos(2*g) - .040849 * np.sin(2*g))
    dec = (.006918 - .399912*np.cos(g) + .070257*np.sin(g)
           - .006758*np.cos(2*g) + .000907*np.sin(2*g)
           - .002697*np.cos(3*g) + .00148*np.sin(3*g))
    ha = np.radians((hour*60 + eq + 4*np.asarray(lon)) / 4 - 180)
    la = np.radians(lat)
    mu = np.clip(np.sin(la)*np.sin(dec) + np.cos(la)*np.cos(dec)*np.cos(ha), -1, 1)
    positive = np.maximum(mu, 1e-6)
    ghi = np.where(mu > 0, 1098 * positive * np.exp(-.059/positive), 0)
    return ghi.astype(np.float32), np.degrees(np.arcsin(mu)).astype(np.float32)


def irradiance_ratio(dsr, reference, min_reference=150):
    dsr, ref = np.asarray(dsr), np.asarray(reference)
    if dsr.shape != ref.shape:
        raise ValueError("DSR and reference must share the same grid")
    valid = np.isfinite(dsr) & (dsr >= 0) & np.isfinite(ref) & (ref >= min_reference)
    out = np.full(dsr.shape, np.nan, dtype=np.float32)
    np.divide(dsr, ref, out=out, where=valid)
    # Cloud enhancement is possible: do not force the ratio to <=1.
    return out


def score_common(actual, predictions, domain):
    """All forecast methods get exactly the same target pixels; report coverage."""
    target = domain & np.isfinite(actual)
    common = target.copy()
    for field in predictions.values():
        common &= np.isfinite(field)
    n, eligible = int(common.sum()), int(target.sum())
    if not n:
        return {}, common
    rows = {}
    for name, field in predictions.items():
        error = field[common].astype(float) - actual[common]
        rows[name] = dict(n=n, eligible=eligible, coverage=n / max(eligible, 1),
                          mae=float(np.abs(error).mean()),
                          rmse=float(np.sqrt(np.mean(error**2))),
                          bias=float(error.mean()))
    return rows, common
