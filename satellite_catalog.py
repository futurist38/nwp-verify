"""Publish GK2A image URLs and timestamps only. Never retrieve image bytes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse
import json
import urllib.parse
import urllib.request

UTC = timezone.utc
KST = timezone(timedelta(hours=9))
ORIGIN = 'https://www.weather.go.kr'
API = ORIGIN + '/w/wnuri-img/rest/sat/images/gk2a.do'
CHANNELS = {
    'rgb-cs': ('RGB 구름강조', 'rgb-cs_ko005lc_', '.thn.jpg'),
    'rgb-s-daynight': ('RGB 주야간합성', 'rgb-s-daynight_ko020lc_', '.png'),
    'ir105': ('적외 10.5 μm', 'ir105_ko020lc_', '.thn.png'),
}


def normalize(rows, channel, now):
    _, prefix, suffix = CHANNELS[channel]
    frames = {}
    for row in rows:
        try:
            tm = datetime.strptime(row['tm'], '%Y%m%d%H%M').replace(tzinfo=KST).astimezone(UTC)
            path = '/w/repositary/image/sat/gk2a/KO/gk2a_ami_le1b_' + prefix + tm.strftime('%Y%m%d%H%M') + suffix
            if tm.minute % 2 or not now - timedelta(hours=6) <= tm <= now:
                continue
            if row['url'] not in (path, ORIGIN + path):
                continue
            frames[tm.isoformat()] = {'time': tm.isoformat(), 'url': ORIGIN + path}
        except (KeyError, TypeError, ValueError):
            continue
    return [frames[t] for t in sorted(frames)]


def fetch_channel(channel, now):
    query = urllib.parse.urlencode(dict(mapType='img', area='ko020lc', data=channel, tm='', itv='0.5', leaflet='0', kmap='0'))
    with urllib.request.urlopen(API + '?' + query, timeout=15) as response:
        if 'json' not in response.headers.get('Content-Type', ''):
            raise ValueError('Expected image metadata JSON')
        payload = response.read(256_001)
        if len(payload) > 256_000:
            raise ValueError('Unexpected metadata size')
    rows = json.loads(payload)
    if not isinstance(rows, list):
        raise ValueError('Expected frame list')
    frames = normalize(rows, channel, now)
    if not frames:
        raise ValueError('No recent valid image URLs')
    return frames


def export(site_dir, fetcher=fetch_channel, now=None):
    now = now or datetime.now(UTC)
    target = Path(site_dir) / 'satellite.json'
    try:
        previous = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        previous = {}
    result = {'version': 1, 'channels': {}}
    cutoff = (now - timedelta(hours=6)).isoformat()
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = {channel: pool.submit(fetcher, channel, now) for channel in CHANNELS}
        for channel, (label, _, _) in CHANNELS.items():
            old = previous.get('channels', {}).get(channel, {})
            frames = {r['time']: r for r in old.get('frames', []) if isinstance(r, dict) and isinstance(r.get('time'), str) and cutoff <= r['time'] <= now.isoformat()}
            checked = old.get('checked_at')
            try:
                incoming = pending[channel].result()
                frames.update({r['time']: r for r in incoming})
                checked = now.isoformat()
            except Exception as error:
                print(f'[satellite] {channel}: metadata unavailable ({type(error).__name__}); keeping prior URLs')
            result['channels'][channel] = dict(label=label, checked_at=checked, frames=[frames[t] for t in sorted(frames)][-181:])
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix('.json.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    temp.replace(target)
    print(f'[satellite] metadata only: {target.stat().st_size:,} bytes; no image downloads')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-dir', default='site_build')
    export(parser.parse_args().site_dir)
