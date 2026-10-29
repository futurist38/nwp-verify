"""Publish dated energy-weather reports; retain exactly 30 KST calendar days."""
import datetime as dt
import json
from pathlib import Path
import re
import shutil
from zoneinfo import ZoneInfo

RETENTION_DAYS = 30

def publish_energy(site_dir, source_dir=None, today=None):
    today = today or dt.datetime.now(ZoneInfo('Asia/Seoul')).date()
    source = Path(source_dir) if source_dir else Path(__file__).parent / 'energy_reports'
    target = Path(site_dir) / 'energy'
    target.mkdir(parents=True, exist_ok=True)
    cutoff = today - dt.timedelta(days=RETENTION_DAYS - 1)
    def date_of(path):
        if not re.fullmatch(r'\d{8}', path.name):
            return None
        try:
            return dt.datetime.strptime(path.name, '%Y%m%d').date()
        except ValueError:
            return None
    if source.exists():
        for folder in source.iterdir():
            day = date_of(folder)
            if folder.is_dir() and day and cutoff <= day <= today:
                if all((folder / name).is_file() for name in ('01.webp', '02.webp', 'report.json')):
                    current=target / folder.name / 'report.json'
                    previous=json.loads(current.read_text(encoding='utf-8')) if current.exists() else {}
                    seed=json.loads((folder/'report.json').read_text(encoding='utf-8'))
                    # Seeds bootstrap missing reports or advance an older issue.
                    # A same-issue seed must not undo published layout/editor repairs.
                    if not current.exists() or previous.get('publication_kst','') < seed.get('publication_kst',''):
                        shutil.copytree(folder, target / folder.name, dirs_exist_ok=True)
    reports = []
    for folder in target.iterdir():
        day = date_of(folder)
        if not folder.is_dir() or day is None:
            continue
        if day < cutoff:
            shutil.rmtree(folder)
        elif day <= today and all((folder / name).is_file() for name in ('01.webp', '02.webp', 'report.json')):
            reports.append(folder.name)
    reports.sort(reverse=True)
    enabled=(Path(__file__).parent/'energy_runtime'/'build_energy.py').is_file()
    data = {'dates': reports, 'retention_days': RETENTION_DAYS,
            'target_time_kst': '07:00', 'automatic_generation': enabled,
            'status': 'enabled' if enabled else 'source_connection_pending',
            'updated_kst': dt.datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds')}
    tmp = target / 'index.json.tmp'
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(target / 'index.json')
    return data
