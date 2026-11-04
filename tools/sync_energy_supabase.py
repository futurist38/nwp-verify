"""Mirror published report metadata and expire old cloud data; never overwrite edits.

Run after the existing GitHub report publication. SUPABASE_SECRET_KEY is read
only from the process environment. No privileged credential belongs in site/.
"""
import datetime as dt
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

URL = 'https://lfxajxconibunipejdjz.supabase.co'
BUCKET = 'energy-images'


class Cloud:
    def __init__(self, key):
        self.headers = {'apikey': key, 'Content-Type': 'application/json'}
        if not key.startswith('sb_secret_'):
            self.headers['Authorization'] = 'Bearer ' + key

    def request(self, path, method='GET', body=None, headers=None):
        req = urllib.request.Request(URL + path, method=method,
            headers={**self.headers, **(headers or {})},
            data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                data = response.read()
                return json.loads(data) if data else None
        except urllib.error.HTTPError as exc:
            # Do not echo credentials, request headers, or uploaded report data.
            raise RuntimeError(f'Supabase HTTP {exc.code} at {path.split("?")[0]}') from None

    def list_folder(self, prefix):
        result = []
        while True:
            batch = self.request('/storage/v1/object/list/' + BUCKET, 'POST',
                {'prefix': prefix, 'limit': 100, 'offset': len(result),
                 'sortBy': {'column': 'name', 'order': 'asc'}})
            if not isinstance(batch, list):
                raise RuntimeError('Invalid storage list response')
            result.extend(batch)
            if len(batch) < 100:
                return result


def sync(cloud, day, report, today):
    cutoff = today - dt.timedelta(days=29)
    if not cutoff <= dt.date.fromisoformat(day) <= today:
        raise ValueError('Report date outside retention window')
    cloud.request('/rest/v1/energy_reports?on_conflict=day', 'POST',
        {'day': day, 'report': report, 'updated_at': dt.datetime.now(dt.timezone.utc).isoformat()},
        {'Prefer': 'resolution=merge-duplicates,return=minimal'})
    rows = cloud.request('/rest/v1/energy_reports?day=eq.' + day + '&select=report')
    if not rows or rows[0]['report'] != report:
        raise RuntimeError('Cloud report verification failed')
    # Retained dates and both page edits are preserved. Only expired dates are deleted.
    for table in ['energy_reports', 'energy_edits']:
        cloud.request('/rest/v1/' + table + '?day=lt.' + cutoff.isoformat(), 'DELETE')
    deleted = 0
    for user in cloud.list_folder(''):
        owner = user.get('name', '')
        if not re.fullmatch(r'[0-9a-f-]{36}', owner):
            continue
        for folder in cloud.list_folder(owner):
            date = folder.get('name', '')
            if not re.fullmatch(r'\d{8}', date) or date >= cutoff.strftime('%Y%m%d'):
                continue
            prefix = owner + '/' + date
            paths = [prefix + '/' + obj['name'] for obj in cloud.list_folder(prefix)
                     if obj.get('id') and re.fullmatch(r'[0-9a-f]{64}\.(png|jpg|webp)', obj.get('name', ''))]
            for i in range(0, len(paths), 100):
                cloud.request('/storage/v1/object/' + BUCKET, 'DELETE', {'prefixes': paths[i:i+100]})
                deleted += len(paths[i:i+100])
    return deleted


def main():
    key = os.environ.get('SUPABASE_SECRET_KEY', '').strip()
    if not key:
        raise SystemExit('SUPABASE_SECRET_KEY is not configured in GitHub Actions secrets')
    today = dt.datetime.now(ZoneInfo('Asia/Seoul')).date()
    subprocess.run(['git', 'fetch', '--depth=1', 'origin', 'site-data'], check=True)
    # Read the published version, not an older generated file that publication rejected.
    raw = subprocess.check_output(['git', 'show', 'FETCH_HEAD:energy/' + today.strftime('%Y%m%d') + '/report.json'])
    report = json.loads(raw)
    count = sync(Cloud(key), today.isoformat(), report, today)
    print(f'Cloud report verified for {today}; removed {count} expired image files. Current edits preserved.')


if __name__ == '__main__':
    main()
