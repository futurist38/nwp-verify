"""Small, opt-in retrospective test of issue-time CA/DSR matching.

Reads real GK2A SWRAD DSR and unmodified M4 outputs. No site publication,
no training, no NWP multiplication. Future DSR/CA is evaluation-only.
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
from solar_ca_mapping import fit_lookup, irradiance_ratio, score_common, solar_reference

LEADS = [30, 60, 120, 180]
SIZE = 512
METHODS = ['dsr_persistence', 'ratio_persistence', 'm4_ca_dsr', 'm4_ca_ratio']


def fetch_product(prod, stamp, directory):
    """Use existing API route/key, with bounded retries and sanitized errors."""
    import requests
    import sslfix  # noqa: F401
    from fetch_gk2a import HOST, _key
    path = Path(directory) / f'{stamp}.nc'
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(2):
        try:
            r = requests.get(f'{HOST}/LE2/{prod}/KO/data',
                             params={'date': stamp, 'authKey': _key()}, timeout=(15, 60))
            r.raise_for_status()
            if r.content[:4] != b'\x89HDF':
                raise ValueError('not NetCDF/HDF5')
            temp = path.with_suffix('.part')
            temp.write_bytes(r.content)
            temp.replace(path)
            return path
        except Exception as ex:
            # Never log requests' exception text: it can contain authKey URLs.
            print(f'[DSR trial] {prod} {stamp}: attempt {attempt+1} failed ({type(ex).__name__})', flush=True)
    return None


def load_field(path, name):
    import cv2
    import xarray as xr
    with xr.open_dataset(path, engine='h5netcdf', decode_cf=False) as ds:
        v = ds[name]
        raw = v.values.astype(np.float32)
        if raw.shape != (900, 900):
            raise ValueError(f'Unexpected KO grid: {raw.shape}')
        valid = np.isfinite(raw)
        for key in ('_FillValue', 'missing_value'):
            if key in v.attrs:
                valid &= ~np.isin(raw, np.atleast_1d(v.attrs[key]))
        valid &= raw != 65535
        scale = float(v.attrs.get('scale_factor', .01 if name == 'CA' else .1))
        offset = float(v.attrs.get('add_offset', 0))
        field = raw * scale + offset
        if name == 'CA':
            # Same CA contract as dl_dataset.py: the scaled value is 0..1.
            field *= 100
        valid &= (field >= 0) & (field <= (100 if name == 'CA' else 1500))
        metadata = dict(variable=name, units=str(v.attrs.get('units', '')),
                        scale=scale, offset=offset, source_shape=list(raw.shape),
                        other_variables=list(ds.data_vars))
    weight = cv2.resize(valid.astype(np.float32), (SIZE, SIZE), interpolation=cv2.INTER_AREA)
    total = cv2.resize(np.where(valid, field, 0), (SIZE, SIZE), interpolation=cv2.INTER_AREA)
    # Do not fill missing pixels as zero or spread them into valid cloud values.
    out = np.full((SIZE, SIZE), np.nan, np.float32)
    np.divide(total, weight, out=out, where=weight > .999)
    return out, metadata


def grid():
    from pyproj import CRS, Transformer
    crs = CRS.from_proj4('+proj=lcc +lat_1=30 +lat_2=60 +lat_0=38 +lon_0=126 +ellps=WGS84')
    # Original 900 pixel centers: -899km..899km, outer edges +/-900km.
    # Match INTER_AREA's 900->512 pixel centers, not the original endpoints.
    x = -900000 + (np.arange(SIZE) + .5) * 1800000 / SIZE
    y = 900000 - (np.arange(SIZE) + .5) * 1800000 / SIZE
    xx, yy = np.meshgrid(x, y)
    lon, lat = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True).transform(xx, yy)
    return lon, lat


def land_masks(lon, lat):
    import cartopy.io.shapereader as shp
    from shapely import contains_xy, union_all
    records = list(shp.Reader(shp.natural_earth('110m', 'cultural', 'admin_0_countries')).records())
    korea = union_all([r.geometry for r in records if r.attributes['ADM0_A3'] in ('KOR', 'PRK')])
    south = union_all([r.geometry for r in records if r.attributes['ADM0_A3'] == 'KOR'])
    return contains_xy(korea, lon, lat), contains_xy(south, lon, lat)


def write_csv(path, rows):
    if not rows:
        return
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def render_case(issue, frames, lon, lat, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs
    from matplotlib.colors import LinearSegmentedColormap
    from solar_radiation import SOLAR_COLORS, SOLAR_LEVELS
    cmap = LinearSegmentedColormap.from_list('solar', SOLAR_COLORS)
    cmap.set_over('#8f1d25')
    fig, axes = plt.subplots(2, 3, figsize=(11, 10), subplot_kw={'projection': ccrs.PlateCarree()})
    image = None
    for row, lead in enumerate([60, 180]):
        record = frames.get(lead)
        for col, key in enumerate(['actual', 'm4_ca_dsr', 'm4_ca_ratio']):
            ax = axes[row, col]
            ax.set_extent([124, 132, 32, 40])
            ax.set_facecolor('#d7d7d7')
            ax.coastlines(resolution='110m', linewidth=.6)
            if record is not None:
                image = ax.contourf(lon, lat, np.ma.masked_invalid(record[key]),
                                    levels=SOLAR_LEVELS, cmap=cmap, vmin=0, vmax=1000,
                                    extend='max', transform=ccrs.PlateCarree())
            vt = issue + dt.timedelta(hours=9, minutes=lead)
            labels = {'actual': 'GK2A DSR verification', 'm4_ca_dsr': 'M4 CA -> DSR lookup',
                      'm4_ca_ratio': 'M4 CA -> sun-adjusted DSR'}
            ax.set_title(f'{labels[key]}\n+{lead} min | {vt:%m-%d %H:%M} KST', fontsize=10)
    if image is not None:
        fig.colorbar(image, ax=list(axes.flat), location='bottom', fraction=.035, pad=.035,
                     ticks=range(0, 1001, 100), label='Instantaneous surface irradiance (W/m2)')
    kst = issue + dt.timedelta(hours=9)
    fig.suptitle(f'EXPERIMENT | Issue {kst:%Y-%m-%d %H:%M} KST\n'
                 'Lookup fitted only at issue time; grey = unavailable / unsupported CA', fontsize=12)
    fig.savefig(output, dpi=120, bbox_inches='tight')
    plt.close(fig)


def render_lookup(issue, ca, dsr, mask, raw_lut, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    v = mask & np.isfinite(ca) & np.isfinite(dsr)
    fig, ax = plt.subplots(figsize=(8, 5))
    h = ax.hexbin(ca[v], dsr[v], gridsize=(40, 35), mincnt=1, bins='log', cmap='Blues')
    ax.plot(raw_lut.centers, raw_lut.means, 'o-', c='#d54a25', label='Issue-time bin mean')
    ax.fill_between(raw_lut.centers, raw_lut.p10, raw_lut.p90, color='#d54a25', alpha=.15,
                    label='Within-bin 10-90% (spread, not confidence interval)')
    ax.set(xlabel='Observed CA (%)', ylabel='GK2A DSR (W/m2)', xlim=(-1, 101), ylim=(0, 1100))
    ax.set_title(f'Initial CA-DSR relationship | {(issue+dt.timedelta(hours=9)):%Y-%m-%d %H:%M} KST')
    ax.legend(fontsize=8)
    fig.colorbar(h, ax=ax, label='Pixel count (log scale)')
    fig.tight_layout()
    fig.savefig(output, dpi=120)
    plt.close(fig)


def run_case(issue, model, output, lon, lat, korea, south):
    from config import DATA_DIR
    stamp = issue.strftime('%Y%m%d%H%M')
    cla_dir = Path(DATA_DIR) / 'gk2a' / 'cla_ko'
    dsr_dir = Path(DATA_DIR) / 'gk2a' / 'dsr_experiment'
    started = time.perf_counter()
    for minutes in [-30, -20, -10, 0]:
        when = (issue + dt.timedelta(minutes=minutes)).strftime('%Y%m%d%H%M')
        if fetch_product('CLA', when, cla_dir) is None:
            raise RuntimeError(f'Missing M4 input: {when}')
    initial_path = fetch_product('SWRAD', stamp, dsr_dir)
    if initial_path is None:
        raise RuntimeError('No simultaneous initial SWRAD/CLA pair')
    ca0, _ = load_field(cla_dir / f'{stamp}.nc', 'CA')
    dsr0, meta = load_field(initial_path, 'DSR')
    ref0, el0 = solar_reference(issue, lon, lat)
    ratio0 = irradiance_ratio(dsr0, ref0)
    # Land+sea around Korea for fitting; terrestrial scores reported separately.
    fit_domain = ((lon >= 123) & (lon <= 133) & (lat >= 31) & (lat <= 41)
                  & (el0 >= 15) & np.isfinite(ratio0))
    tfit = time.perf_counter()
    raw_lut = fit_lookup(ca0, dsr0, fit_domain)
    ratio_lut = fit_lookup(ca0, ratio0, fit_domain)
    fitting_seconds = time.perf_counter() - tfit
    # Freeze the fitted mappings before fetching any future verification data.
    (output / f'lookup_{stamp}.json').write_text(json.dumps(
        dict(issue_utc=stamp, raw_dsr=raw_lut.records(), normalized=ratio_lut.records(),
             fit_pixels=int(fit_domain.sum()), dsr_metadata=meta), ensure_ascii=False, indent=2))
    tinfer = time.perf_counter()
    fields = model.predict(issue, LEADS, native=True)
    inference_seconds = time.perf_counter() - tinfer
    if not fields or set(fields) != set(LEADS):
        raise RuntimeError('M4 did not produce all requested leads')
    rows, oracle_rows, frames, missing = [], [], {}, []
    conversion_seconds = 0.
    for lead in LEADS:
        valid_time = issue + dt.timedelta(minutes=lead)
        ref, elevation = solar_reference(valid_time, lon, lat)
        tc = time.perf_counter()
        predicted = dict(dsr_persistence=dsr0, ratio_persistence=ratio0*ref,
                         m4_ca_dsr=raw_lut.apply(fields[lead]),
                         m4_ca_ratio=ratio_lut.apply(fields[lead])*ref)
        conversion_seconds += time.perf_counter() - tc
        valid_stamp = valid_time.strftime('%Y%m%d%H%M')
        path = fetch_product('SWRAD', valid_stamp, dsr_dir)
        if path is None:
            missing.append(valid_stamp)
            continue
        actual, _ = load_field(path, 'DSR')
        for region, land in [('south_korea', south), ('korean_peninsula', korea)]:
            day = land & (el0 >= 15) & (elevation >= 15)
            scores, common = score_common(actual, predicted, day)
            for method, values in scores.items():
                rows.append(dict(issue_utc=stamp, lead_min=lead, region=region,
                                 method=method, **values))
        # Actual future CA is diagnostic-only, never used for forecasting.
        ca_path = fetch_product('CLA', valid_stamp, cla_dir)
        if ca_path is not None:
            actual_ca, _ = load_field(ca_path, 'CA')
            diagnostic = dict(predicted)
            diagnostic['actual_CA_diagnostic_NOT_FORECAST'] = ratio_lut.apply(actual_ca)*ref
            scores, _ = score_common(actual, diagnostic, south & (el0 >= 15) & (elevation >= 15))
            for method, values in scores.items():
                oracle_rows.append(dict(issue_utc=stamp, lead_min=lead, method=method, **values))
        if lead in (60, 180):
            frames[lead] = dict(actual=actual, **predicted)
        print(f'[DSR trial] {stamp} +{lead}m: scored', flush=True)
    render_case(issue, frames, lon, lat, output / f'case_{stamp}.png')
    render_lookup(issue, ca0, dsr0, fit_domain, raw_lut, output / f'lookup_{stamp}.png')
    return rows, oracle_rows, dict(issue_utc=stamp, fit_seconds=fitting_seconds,
                                   m4_seconds=inference_seconds,
                                   conversion_seconds=conversion_seconds,
                                   total_seconds=time.perf_counter()-started,
                                   missing_verification=missing)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--issues', nargs='+', required=True, help='UTC YYYYMMDDHHMM')
    parser.add_argument('--out', default='output/solar_dsr_experiment')
    args = parser.parse_args()
    issues = [dt.datetime.strptime(s, '%Y%m%d%H%M') for s in args.issues]
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    if any(t.minute % 10 or t + dt.timedelta(minutes=max(LEADS)+30) > now for t in issues):
        parser.error('Use 10-minute UTC timestamps with verification already available')
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    from dl_infer import DLNowcaster, MODEL_H5
    lon, lat = grid()
    korea, south = land_masks(lon, lat)
    model = DLNowcaster()
    rows, diagnostics, timings, failed = [], [], [], []
    for issue in issues:
        try:
            result, oracle, timing = run_case(issue, model, output, lon, lat, korea, south)
            rows.extend(result)
            diagnostics.extend(oracle)
            timings.append(timing)
        except Exception as ex:
            # Product errors are sanitized in fetch_product; scientific errors need context.
            import traceback
            traceback.print_exc()
            failed.append(dict(issue_utc=issue.strftime('%Y%m%d%H%M'), error=type(ex).__name__))
        write_csv(output / 'scores.csv', rows)
        write_csv(output / 'diagnostic_actual_ca.csv', diagnostics)
    provenance = dict(method_version='ca-dsr-lookup-v1', issue_times=args.issues,
                      model_sha256=hashlib.sha256(Path(MODEL_H5).read_bytes()).hexdigest(),
                      source_commit=os.environ.get('GITHUB_SHA', 'local'),
                      fit='issue-time only, 5-percentage-point CA bins, min_count=64',
                      reference='NOAA approximate geometric sun + Haurwitz; elevation >=15 deg',
                      verification='GK2A satellite DSR; NOT independent ground truth',
                      timings=timings, failed=failed)
    (output / 'provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    summary = []
    for lead in LEADS:
        for method in METHODS:
            selected = [r for r in rows if r['region']=='south_korea' and r['lead_min']==lead and r['method']==method]
            n = sum(r['n'] for r in selected)
            if not n:
                continue
            summary.append(dict(lead_min=lead, method=method, cases=len(selected), n=n,
                                mae=sum(r['mae']*r['n'] for r in selected)/n,
                                rmse=(sum(r['rmse']**2*r['n'] for r in selected)/n)**.5,
                                bias=sum(r['bias']*r['n'] for r in selected)/n,
                                coverage=n/sum(r['eligible'] for r in selected)))
    write_csv(output / 'summary.csv', summary)
    print(json.dumps(dict(summary=summary, timings=timings, failed=failed), indent=2), flush=True)
    if failed or len(timings) != len(issues) or any(t['missing_verification'] for t in timings) or not summary:
        raise SystemExit('Incomplete experiment: see provenance; partial scores are not a complete trial')


if __name__ == '__main__':
    main()
