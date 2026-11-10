"""Exact image-only R2 deletion/restore plans; no wildcard data deletion."""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_site as b
from model_image_retention import archive_keys, retained_model_keys, today_kst, MODEL_IMAGE_RE, UPPER_PANEL_RE


def plan(site_dir, listing, prefix):
    remote = set(Path(listing).read_text(encoding='utf-8').splitlines())
    local = archive_keys(site_dir)
    today = today_kst()
    keep = retained_model_keys(remote | local, today)
    cutoff = (today - dt.timedelta(days=b.MAX_DAYS)).strftime('%Y%m%d')
    upper_cut = (today - dt.timedelta(days=b.UPPER_MAX_DAYS)).strftime('%Y%m%d')
    for key in list(keep):
        if not re.fullmatch(r'\d{8}/[^/]+\.(?:png|webp)', key):
            continue
        m = MODEL_IMAGE_RE.fullmatch(key)
        if (key[:8] < cutoff or b.is_disabled_upper_key(key) or
            (m and UPPER_PANEL_RE.fullmatch(m['panel']) and key[:8] < upper_cut)):
            keep.discard(key)
    cm, cu = b.local_cuts()
    restore = set()
    for key in remote & keep:
        if not re.fullmatch(r'\d{8}/[^/]+\.(?:png|webp)', key) or key[:8] < cm:
            continue
        m = MODEL_IMAGE_RE.fullmatch(key)
        if m and UPPER_PANEL_RE.fullmatch(m['panel']) and key[:8] < cu:
            continue
        restore.add(key)
    for suffix, keys in [('delete', remote - keep), ('keep', remote & keep), ('restore', restore)]:
        Path(f'{prefix}.{suffix}').write_text(''.join(k+'\n' for k in sorted(keys)), encoding='utf-8')
    print(f'[storage] R2 plan: remove {len(remote-keep)}, restore at most {len(restore)} image keys')


def trim_local(site_dir):
    cm, cu = b.local_cuts()
    removed = size = 0
    for key in archive_keys(site_dir):
        if not re.fullmatch(r'\d{8}/[^/]+\.(?:png|webp)', key):
            continue
        m = MODEL_IMAGE_RE.fullmatch(key)
        if key[:8] < cm or (m and UPPER_PANEL_RE.fullmatch(m['panel']) and key[:8] < cu):
            path = Path(site_dir) / 'archive' / key
            size += path.stat().st_size
            path.unlink()
            removed += 1
    print(f'[storage] local window trimmed: {removed} images, {size} bytes; numerical files preserved')


def measure(site_dir, label):
    root = Path(site_dir)
    def size(path):
        return sum(p.stat().st_size for p in path.rglob('*') if p.is_file()) if path.exists() else 0
    stats = {'label': label, 'site_bytes': size(root), 'archive_bytes': size(root/'archive'),
             'nowcast_bytes': size(root/'nowcast')}
    print('[storage] '+json.dumps(stats))
    import os
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(f"\n{label}: site {stats['site_bytes']/1e6:.1f} MB; archive {stats['archive_bytes']/1e6:.1f} MB; nowcast {stats['nowcast_bytes']/1e6:.1f} MB\n")
    return stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['plan', 'trim-local', 'measure'])
    parser.add_argument('--site-dir', required=True)
    parser.add_argument('--listing', default='.r2_listing')
    parser.add_argument('--prefix', default='.r2_plan')
    parser.add_argument('--label', default='site')
    args = parser.parse_args()
    if args.mode == 'plan':
        plan(args.site_dir, args.listing, args.prefix)
    elif args.mode == 'trim-local':
        trim_local(args.site_dir)
    else:
        measure(args.site_dir, args.label)
