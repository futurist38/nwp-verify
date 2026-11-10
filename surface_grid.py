"""Native surface fields for browser maps; upper-air images are independent.

Frames are gzip-compressed little-endian float32, north-to-south rows. NaN is
missing (never zero). Content-addressed filenames make browser caches safe.
Only the newest successfully exported run per model is published.
"""
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import time

PANELS = ('t2m', 'tcc', 'cloud3', 'dswrf', 'tp')
MODELS = ('ECMWF', 'GFS', 'KIM')
FRAME_NAME = re.compile(r'f\d{3}_(?:t2m|tcc|cloud3|dswrf|tp)_[0-9a-f]{12}\.f32\.gz')


def export_surface_grid(model, data, output_dir, panels=None):
    import numpy as np
    from config import map_steps
    from solar_radiation import solar_field

    start = time.monotonic()
    run = data['run'].strftime('%Y%m%d%H')
    directory = Path(output_dir) / 'grids' / f'{model.lower()}_{run}'
    directory.mkdir(parents=True, exist_ok=True)
    index = {'version': 1, 'model': model, 'run': run, 'panels': {}}
    total = 0

    def select(key, step):
        da = data.get(key)
        if da is None or np.timedelta64(step, 'h') not in da.step.values:
            return None
        return da.sel(step=np.timedelta64(step, 'h')).transpose('latitude', 'longitude').sortby(
            'latitude', ascending=False).sortby('longitude')

    for step in map_steps(data['run'].hour):
        for panel in panels or PANELS:
            keys = ('lcc', 'mcc', 'hcc') if panel == 'cloud3' else (panel,)
            fields = [select(key, step) for key in keys]
            if any(f is None for f in fields):
                continue
            first = fields[0]
            values = np.stack([f.values for f in fields]).astype('<f4')
            values[~np.isfinite(values)] = np.nan
            if not all(np.isfinite(v).any() for v in values):
                continue
            lat, lon = first.latitude.values, first.longitude.values
            if len(lat) < 2 or len(lon) < 2:
                raise ValueError('Surface maps require a two-dimensional grid')
            if not (np.allclose(np.diff(lat), np.diff(lat)[0], atol=1e-5) and
                    np.allclose(np.diff(lon), np.diff(lon)[0], atol=1e-5)):
                raise ValueError('Surface grid is not regular')
            if any(not np.array_equal(f.latitude, lat) or not np.array_equal(f.longitude, lon)
                   for f in fields[1:]):
                raise ValueError('Cloud layer coordinates differ')
            if panel == 'dswrf':
                solar = solar_field(first, step)
                if solar is None:
                    continue
                values[0] = solar.filled(np.nan)
            window = float(first.win_h) if 'win_h' in first.coords else None
            if panel == 'tp' and (window is None or not np.isfinite(window) or window <= 0):
                continue
            raw = values.tobytes(order='C')
            name = f'f{step:03d}_{panel}_{hashlib.sha256(raw).hexdigest()[:12]}.f32.gz'
            payload = gzip.compress(raw, compresslevel=6, mtime=0)
            (directory / name).write_bytes(payload)
            total += len(payload)
            descriptor = {'file': name, 'nx': len(lon), 'ny': len(lat), 'channels': len(keys),
                          'lon0': float(lon[0]), 'lon1': float(lon[-1]),
                          'lat0': float(lat[0]), 'lat1': float(lat[-1]),
                          'valid_cells': int(np.isfinite(values).sum()), 'bytes': len(payload)}
            if window is not None and np.isfinite(window):
                descriptor['window_h'] = window
            index['panels'].setdefault(panel, {})[str(step)] = descriptor
    if not index['panels']:
        raise ValueError(f'{model}: no valid surface frames')
    # Write the index last: a partial export must never advertise missing payloads.
    path = directory / 'index.json'
    path.write_text(json.dumps(index, separators=(',', ':')), encoding='utf-8')
    print(f'[surface-grid] {model} {run}: {sum(map(len, index["panels"].values()))} frames, '
          f'{total / 1e6:.2f} MB, {time.monotonic() - start:.2f}s')
    return path


def read_index(path):
    """Accept complete, local, bounded frame references only."""
    try:
        path = Path(path)
        index = json.loads(path.read_text(encoding='utf-8'))
        if index['version'] != 1 or index['model'] not in MODELS or not re.fullmatch(r'\d{10}', index['run']):
            return None
        if path.parent.name != f'{index["model"].lower()}_{index["run"]}':
            return None
        if not index['panels']:
            return None
        for panel, frames in index['panels'].items():
            if panel not in PANELS or not frames:
                return None
            for step, frame in frames.items():
                if not step.isdigit() or not FRAME_NAME.fullmatch(frame['file']):
                    return None
                if not frame['file'].startswith(f'f{int(step):03d}_{panel}_'):
                    return None
                if frame['nx'] < 2 or frame['ny'] < 2 or frame['nx'] * frame['ny'] > 1000000:
                    return None
                if frame['channels'] != (3 if panel == 'cloud3' else 1):
                    return None
                if not (path.parent / frame['file']).is_file():
                    return None
        return index
    except (KeyError, TypeError, ValueError, OSError):
        return None


def surface_entries(site_dir):
    result = []
    for path in sorted((Path(site_dir) / 'grids').glob('????????/*/index.json')):
        index = read_index(path)
        if index and path.parents[1].name.isdigit():
            result.append((path.parents[1].name, index, path))
    return result


def publish_surface_grids(site_dir, output_dir):
    """Merge with the restored deployment; stale jobs cannot revert a newer run.

    Same-run partial retries preserve previously received frames. Legacy images
    expire under their existing policy; they are not requested for migrated models.
    """
    site = Path(site_dir)
    candidates = list(surface_entries(site))
    for path in sorted(Path(output_dir).glob('????????/grids/*/index.json')):
        index = read_index(path)
        if index:
            candidates.append((path.parents[2].name, index, path))
    for model in MODELS:
        items = [item for item in candidates if item[1]['model'] == model]
        if not items:
            continue
        run = max(item[1]['run'] for item in items)
        items = [item for item in items if item[1]['run'] == run]
        day = max(item[0] for item in items)
        target = site / 'grids' / day / f'{model.lower()}_{run}'
        target.mkdir(parents=True, exist_ok=True)
        merged = {'version': 1, 'model': model, 'run': run, 'panels': {}}
        for _, index, path in items:
            for panel, frames in index['panels'].items():
                dest = merged['panels'].setdefault(panel, {})
                for step, frame in frames.items():
                    if step in dest and dest[step]['valid_cells'] > frame['valid_cells']:
                        continue
                    source, destination = path.parent / frame['file'], target / frame['file']
                    if source.resolve() != destination.resolve() and not destination.exists():
                        shutil.copy2(source, destination)
                    dest[step] = frame
        (target / 'index.json').write_text(json.dumps(merged, separators=(',', ':')), encoding='utf-8')
        wanted = {f['file'] for frames in merged['panels'].values() for f in frames.values()} | {'index.json'}
        for path in target.iterdir():
            if path.is_file() and path.name not in wanted:
                path.unlink()
        for old in (site / 'grids').glob(f'????????/{model.lower()}_*'):
            if old != target and old.is_dir():
                shutil.rmtree(old)


def merge_surface_manifest(manifest, site_dir):
    entries = surface_entries(site_dir)
    models = {index['model'] for _, index, _ in entries}
    if not models:
        return
    for day in manifest['dates'].values():
        for model in models & day['models'].keys():
            entry = day['models'][model]
            for run in list(entry['runs']):
                record = entry['runs'][run]
                record['panels'] = [p for p in record['panels'] if p not in PANELS]
                record['psteps'] = {p: s for p, s in record['psteps'].items() if p not in PANELS}
                record['steps'] = sorted({s for steps in record['psteps'].values() for s in steps})
                if not record['panels']:
                    del entry['runs'][run]
            if not entry['runs']:
                del day['models'][model]
            else:
                entry['latest'] = max(entry['runs'])
    for day, index, path in entries:
        entry = manifest['dates'].setdefault(day, {'models': {}, 'meteograms': [], 'daily_json': None, 'obs': {}})
        model = entry['models'].setdefault(index['model'], {'runs': {}, 'latest': None})
        record = model['runs'].setdefault(index['run'], {'steps': [], 'panels': [], 'psteps': {}})
        record['grids'] = {}
        for panel, frames in index['panels'].items():
            record['panels'].append(panel)
            record['psteps'][panel] = sorted(map(int, frames))
            record['grids'][panel] = {step: {**frame, 'path': (path.parent / frame['file']).relative_to(site_dir).as_posix()}
                                      for step, frame in frames.items()}
        record['steps'] = sorted({s for steps in record['psteps'].values() for s in steps})
        model['latest'] = max(model['runs'])
    manifest['surface_grid'] = {'version': 1, 'render': 'smooth', 'retention': 'latest_per_model'}
