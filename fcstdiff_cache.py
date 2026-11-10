"""Small, durable forecast-change inputs. No credentials or API responses stored."""
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import tempfile

CACHE_KEEP_DAYS = 4


def clean_series(series):
    """Keep valid hourly temperatures only; missing values are never zero-filled."""
    result = {}
    if not isinstance(series, dict):
        return result
    for stamp, value in series.items():
        if not isinstance(stamp, str) or not re.fullmatch(r'\d{10}', stamp):
            continue
        try:
            dt.datetime.strptime(stamp, '%Y%m%d%H')
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                continue
        except (ValueError, OverflowError):
            continue
        result[stamp] = float(value)
    return result


def complete(series, days):
    """A cache hit requires all 24 hours for every comparison target date."""
    return all((key := f'{day:%Y%m%d}{hour:02d}') in series
               and isinstance(series[key], (int, float))
               and not isinstance(series[key], bool) and math.isfinite(series[key])
               for day in days for hour in range(24))


def read_cache(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {station: clean_series(series) for station, series in data.items()
            if isinstance(station, str) and station.isdigit()}


def write_cache(path, data):
    """Checkpoint after each successful station; readers never see a partial JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.stem + '.', suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def expired_cache_path(path, today=None):
    """Only this disposable cache may be pruned by the verification publisher."""
    match = re.fullmatch(r'verification/fcstdiff/(\d{10})\.json', str(path))
    if not match:
        return False
    try:
        date = dt.datetime.strptime(match[1], '%Y%m%d%H').date()
    except ValueError:
        return False
    today = today or dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    return date < today - dt.timedelta(days=CACHE_KEEP_DAYS - 1)
