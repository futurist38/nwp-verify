"""Digital medium-range forecasts: explicit NetCDF profile, shadow/active gate.

No endpoint, variable names, time semantics or weather codes are inferred.
Raw downloads live only in a temporary directory; validated city revisions persist.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import urllib.parse
import urllib.request

KST = dt.timezone(dt.timedelta(hours=9))
CORE = ('TMP', 'TMN', 'TMX', 'SKY', 'PTY', 'RPOS', 'RVAR')
QUANTILES = ('10P', '25P', '75P', '90P')
ROOT = Path(__file__).resolve().parent


class InvalidData(ValueError):
    pass


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    value = json.dumps(obj, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':')) + '\n'
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as f:
        f.write(value)
        temp = Path(f.name)
    temp.replace(path)


def config(path):
    cfg = read(path)
    if cfg.get('mode') not in ('off', 'shadow', 'active'):
        raise InvalidData('mode must be off/shadow/active')
    return cfg


def profile_check(cfg):
    p = cfg.get('profile', {})
    if not p.get('verified') or not p.get('id'):
        raise InvalidData('an explicitly verified sample profile is required')
    if p.get('timezone') not in ('UTC', 'Asia/Seoul'):
        raise InvalidData('explicit source timezone required')
    fields = p.get('fields', {})
    if not set(CORE) <= fields.keys():
        raise InvalidData('all seven core elements required')
    for base in ('TMP', 'TMN', 'TMX'):
        present = [base + q in fields for q in QUANTILES]
        if any(present) and not all(present):
            raise InvalidData('quantiles must be supplied as a complete group')
    for key, spec in fields.items():
        if key not in CORE and key not in {b+q for b in ('TMP','TMN','TMX') for q in QUANTILES}:
            raise InvalidData('unknown element')
        if not all(spec.get(k) for k in ('variable', 'time', 'latitude', 'longitude', 'units')):
            raise InvalidData('explicit variable/coordinate/units mapping required')
        if not spec.get('issue_attribute') and not spec.get('issue_variable'):
            raise InvalidData('source issue metadata mapping required')
        if key.startswith(('TMN','TMX')) and 'date_offset_hours' not in spec:
            raise InvalidData('daily target date mapping required')
    for key in ('SKY', 'PTY', 'RPOS', 'RVAR'):
        if not p.get('codes', {}).get(key):
            raise InvalidData('explicit category code mapping required')
    if not p.get('cities') or not 0 < p.get('max_distance_km', 0) <= 50:
        raise InvalidData('city coordinates and sampling distance limit required')
    if not isinstance(p.get('daily_leads'), list) or not p['daily_leads']:
        raise InvalidData('expected target day offsets required')
    if not isinstance(p.get('hourly_leads'), list) or len(p['hourly_leads']) < 2:
        raise InvalidData('expected hourly lead times required')
    if any(b-a not in (3,6) for a,b in zip(p['hourly_leads'], p['hourly_leads'][1:])):
        raise InvalidData('hourly leads must increase by 3 or 6 hours')
    return p


def stamp(value, timezone):
    # NetCDF must expose decoded CF datetimes; numeric lead axes need an adapter.
    s = str(value).strip().replace('Z', '+00:00')
    if re.fullmatch(r'\d{10}(?:\d{2})?', s):
        out = dt.datetime.strptime(s, '%Y%m%d%H%M' if len(s)==12 else '%Y%m%d%H')
    else:
        try:
            out = dt.datetime.fromisoformat(s)
        except ValueError as e:
            raise InvalidData('unrecognized datetime') from e
    if out.tzinfo is None:
        out = out.replace(tzinfo=dt.timezone.utc if timezone=='UTC' else KST)
    return out.astimezone(KST)


def extract(path, key, spec, p, issued):
    import numpy as np
    import xarray as xr
    with xr.open_dataset(path, decode_times=True, mask_and_scale=True) as ds:
        raw_issue = ds.attrs.get(spec.get('issue_attribute')) if spec.get('issue_attribute') else ds[spec['issue_variable']].values
        if np.asarray(raw_issue).size != 1:
            raise InvalidData('source issue must be scalar')
        raw_issue = np.asarray(raw_issue).reshape(-1)[0]
        if stamp(raw_issue, p['timezone']) != issued:
            raise InvalidData('source issue does not match requested issue')
        da = ds[spec['variable']]
        if da.attrs.get('units') != spec['units']:
            raise InvalidData('units changed: ' + key)
        lat, lon = xr.broadcast(ds[spec['latitude']], ds[spec['longitude']])
        if lat.ndim != 2 or set(lat.dims) - set(da.dims):
            raise InvalidData('expected 2-D geolocated grid (1-D lat/lon also supported)')
        if set(da.dims) != {spec['time'], *lat.dims}:
            raise InvalidData('unexpected variable dimensions')
        times = [stamp(v, p['timezone']) for v in ds[spec['time']].values]
        if any(t.minute or t.second or t.microsecond for t in times):
            raise InvalidData('valid times must be on exact hours')
        daily = key.startswith(('TMN', 'TMX'))
        keys = [(t + dt.timedelta(hours=spec.get('date_offset_hours',0))).strftime('%Y%m%d') if daily else t.strftime('%Y%m%d%H') for t in times]
        if len(set(keys)) != len(keys) or keys != sorted(keys):
            raise InvalidData('duplicate or unordered valid times')
        expected = [(issued.date() + dt.timedelta(days=n)).strftime('%Y%m%d') for n in p['daily_leads']] if daily else [(issued + dt.timedelta(hours=h)).strftime('%Y%m%d%H') for h in p['hourly_leads']]
        if keys != expected:
            raise InvalidData('incomplete or changed time coverage: ' + key)
        result, points = {}, {}
        for city, pos in p['cities'].items():
            y, x = float(pos[0]), float(pos[1])
            a, b = np.deg2rad(lat.values), np.deg2rad(lon.values)
            hav = np.sin((a-np.deg2rad(y))/2)**2 + np.cos(a)*math.cos(math.radians(y))*np.sin((b-np.deg2rad(x))/2)**2
            distance = 6371 * 2 * np.arcsin(np.sqrt(np.clip(hav,0,1)))
            distance = np.where(np.isfinite(distance), distance, np.inf)
            idx = np.unravel_index(np.argmin(distance), distance.shape)
            if distance[idx] > p['max_distance_km']:
                raise InvalidData('city outside supported grid: ' + city)
            selected = da.isel(dict(zip(lat.dims, idx))).transpose(spec['time']).values
            vals = []
            for raw in selected:
                v = float(raw)
                if not math.isfinite(v):
                    raise InvalidData('missing city value: ' + key)
                if key.startswith(('TMP','TMN','TMX')):
                    v = v * spec.get('scale',1) + spec.get('offset',0)
                    if not -60 <= v <= 60:
                        raise InvalidData('temperature outside validated range')
                    vals.append(round(v,3))
                else:
                    code = str(int(v)) if v.is_integer() else str(v)
                    label = p['codes'][key].get(code)
                    if not isinstance(label, str) or not label:
                        raise InvalidData('unmapped categorical value: ' + key)
                    vals.append({'raw': v, 'label': label})
            result[city] = dict(zip(keys, vals))
            points[city] = {'lat': float(lat.values[idx]), 'lon': float(lon.values[idx]), 'distance_km': round(float(distance[idx]),3)}
        return result, points


def normalize(paths, cfg, issue):
    p = profile_check(cfg)
    issued = stamp(issue, 'Asia/Seoul')
    if issued.hour != 18 or issued.minute or issued.second:
        raise InvalidData('digital medium issue must be 18:00 KST')
    fields, points = {}, {}
    for key, spec in p['fields'].items():
        fields[key], points[key] = extract(paths[key], key, spec, p, issued)
    # All elements must sample the same spatial points.
    if any(v != points['TMP'] for v in points.values()):
        raise InvalidData('element grids do not share sampling locations')
    cities = {}
    for city in p['cities']:
        daily, hourly = {}, {}
        for target in fields['TMN'][city]:
            lo, hi = fields['TMN'][city][target], fields['TMX'][city][target]
            if lo > hi:
                raise InvalidData('daily minimum exceeds maximum')
            daily[target] = {'TMN':lo, 'TMX':hi}
        for target in fields['TMP'][city]:
            hourly[target] = {k: fields[k][city][target] for k in ('TMP','SKY','PTY','RPOS','RVAR')}
        for base in ('TMP','TMN','TMX'):
            if base+'10P' not in fields:
                continue
            records = hourly if base=='TMP' else daily
            for target, rec in records.items():
                vals = [fields[base+q][city][target] for q in QUANTILES]
                if vals != sorted(vals):
                    raise InvalidData('crossing quantiles')
                rec[base+'_quantiles'] = dict(zip(('p10','p25','p75','p90'), vals))
        cities[city] = {'sample':points['TMP'][city], 'daily':daily, 'hourly':hourly}
    doc = {'schema':1, 'source':'kma_digital_mid', 'issue':issued.strftime('%Y%m%d%H'),
           'timezone':'Asia/Seoul', 'profile_id':p['id'], 'profile_hash':hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest(),
           'cities':cities}
    doc['revision'] = hashlib.sha256(json.dumps(doc,sort_keys=True).encode()).hexdigest()[:16]
    return doc


def download(url, path, cfg):
    u = urllib.parse.urlsplit(url)
    if u.scheme != 'https' or u.hostname not in cfg.get('allowed_hosts', []) or u.username or u.password:
        raise InvalidData('download endpoint must use HTTPS and an allowed host')
    # Block redirects rather than leaking an auth query to another host.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    limit = int(cfg.get('max_file_mb',128))*1024*1024
    with urllib.request.build_opener(NoRedirect()).open(url, timeout=30) as response, open(path,'wb') as out:
        size = 0
        while chunk := response.read(1024*1024):
            size += len(chunk)
            if size > limit:
                raise InvalidData('download exceeds size limit')
            out.write(chunk)
    if size == 0:
        raise InvalidData('empty download')


def collect(cfg, cache, issue=None, input_dir=None, now=None):
    now = now or dt.datetime.now(KST)
    if cfg['mode']=='off':
        return None
    p = profile_check(cfg)
    if issue is None:
        candidate = now.replace(hour=18,minute=0,second=0,microsecond=0)
        if now < candidate + dt.timedelta(minutes=cfg.get('delay_minutes',30)):
            candidate -= dt.timedelta(days=1)
        issue = candidate.strftime('%Y%m%d%H')
    if stamp(issue,'Asia/Seoul') > now:
        raise InvalidData('future issue')
    existing = []
    for file in (Path(cache)/'revisions').glob(issue+'-*.json'):
        d = read(file)
        if d.get('profile_hash') == hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest():
            existing.append((d.get('received_at',''), file))
    checked_path = Path(cache)/'checked'/f"{issue}-{hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest()[:16]}.json"
    if not input_dir and existing and checked_path.exists():
        checked = read(checked_path)['checked_at']
        if now - dt.datetime.fromisoformat(checked) < dt.timedelta(minutes=cfg.get('recheck_minutes',180)):
            return max(existing)[1]
    with tempfile.TemporaryDirectory(prefix='digital-mid-') as temp:
        paths = {}
        for key in p['fields']:
            filename = f'DFS_MEDM_GRD_GEMD_HR36_{key}.{issue}00.nc'
            if input_dir:
                paths[key] = Path(input_dir)/filename
            else:
                template = os.environ.get('KMA_DIGITAL_MID_URL_TEMPLATE','')
                if not template:
                    raise InvalidData('download URL template is not configured')
                paths[key] = Path(temp)/filename
                url = template.format(filename=filename, element=key, issue=issue+'00',
                    auth_key=urllib.parse.quote(os.environ.get('KMA_DIGITAL_MID_AUTH_KEY',''),safe=''))
                download(url,paths[key],cfg)
        doc = normalize(paths,cfg,issue)
    dest = Path(cache)/'revisions'/f"{doc['issue']}-{doc['revision']}.json"
    if not dest.exists() or (existing and max(existing)[1] != dest):
        doc['received_at'] = now.isoformat()
        write(dest, doc)
    write(checked_path, {'checked_at':now.isoformat()})
    return dest


def export(site_dir, cfg_path=ROOT/'digital_mid_config.json', cache=ROOT/'verification/digital_mid'):
    cfg = config(cfg_path)
    dest = Path(site_dir)/'digital_mid/index.json'
    payload = {'schema':1,'mode':cfg['mode'],'issues':[]}
    if cfg['mode']=='active':
        p = profile_check(cfg)
        fingerprint = hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest()
        cutoff = dt.datetime.now(KST)-dt.timedelta(days=cfg.get('display_days',21))
        by_issue = {}
        for file in sorted((Path(cache)/'revisions').glob('*.json')):
            d = read(file)
            if d.get('schema')!=1 or d.get('source')!='kma_digital_mid' or d.get('profile_hash')!=fingerprint:
                continue
            if not cutoff <= stamp(d['issue'],'Asia/Seoul') <= dt.datetime.now(KST):
                continue
            prev = by_issue.get(d['issue'])
            if not prev or d['received_at'] > prev['received_at']:
                by_issue[d['issue']] = d
        payload['issues'] = [by_issue[k] for k in sorted(by_issue)]
    write(dest,payload)  # off/shadow explicitly clears previously exported active data
    return payload


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--config',default=str(ROOT/'digital_mid_config.json'))
    ap.add_argument('--cache',default=str(ROOT/'verification/digital_mid'))
    ap.add_argument('--input-dir')
    ap.add_argument('--issue')
    ap.add_argument('--export-site')
    args=ap.parse_args()
    try:
        cfg=config(args.config)
        if args.export_site:
            export(args.export_site,args.config,args.cache)
        else:
            result=collect(cfg,args.cache,args.issue,args.input_dir)
            print('[digital-mid] '+('off: no request' if cfg['mode']=='off' else 'validated revision saved'))
    except Exception as error:
        # Never print exception text, request URL or auth keys.
        print('[digital-mid] rejected: '+type(error).__name__+'; existing forecasts retained')
        raise SystemExit(1)


if __name__=='__main__':
    main()
