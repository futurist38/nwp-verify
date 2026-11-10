"""One KST calendar policy for model image cleanup, R2 restore and manifest.

Today counts as day 1: days 1–5 keep every run; days 6–7 keep the latest
run per archive date/model. Pressure-level images keep their existing policy.
Numerical JSON/CSV and unrelated files are never model-image deletion targets.
"""
import datetime as dt
from pathlib import Path
import re

MODEL_IMAGE_DAYS = 7
ALL_RUN_DAYS = 5
MODEL_IMAGE_RE = re.compile(
    r"^(?P<day>\d{8})/(?P<model>[a-z]+)_(?P<run>\d{10})_f\d{3}_(?P<panel>\w+)\.(?:png|webp)$")
UPPER_PANEL_RE = re.compile(r"p\d{3}")


def today_kst():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()


def retained_model_keys(keys, today=None):
    """Filter only ordinary model maps (including SFC); leave upper/data alone."""
    today = today or today_kst()
    oldest = (today - dt.timedelta(days=MODEL_IMAGE_DAYS - 1)).strftime('%Y%m%d')
    full = (today - dt.timedelta(days=ALL_RUN_DAYS - 1)).strftime('%Y%m%d')
    keys = set(keys)
    matched = {}
    latest = {}
    for key in keys:
        m = MODEL_IMAGE_RE.fullmatch(key)
        if not m or UPPER_PANEL_RE.fullmatch(m['panel']):
            continue
        matched[key] = m
        group = (m['day'], m['model'])
        latest[group] = max(latest.get(group, ''), m['run'])
    return {key for key in keys if key not in matched or (
        matched[key]['day'] >= oldest and (
            matched[key]['day'] >= full or
            matched[key]['run'] == latest[(matched[key]['day'], matched[key]['model'])]))}


def archive_keys(site_dir):
    root = Path(site_dir) / 'archive'
    return {p.relative_to(root).as_posix() for p in root.glob('????????/*') if p.is_file()}


def prune_model_images(site_dir, remote_keys=(), today=None):
    local = archive_keys(site_dir)
    keep = retained_model_keys(local | set(remote_keys), today)
    removed = local - keep
    size = 0
    for key in removed:
        path = Path(site_dir) / 'archive' / key
        size += path.stat().st_size
        path.unlink()
    print(f'[retention] model maps removed: {len(removed)} files, {size} bytes')
    return len(removed), size
