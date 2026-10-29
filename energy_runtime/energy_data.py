"""07 KST energy report inputs. Missing required temperatures stop publication."""
import csv, io, json, os, datetime as dt
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import urlopen
from zoneinfo import ZoneInfo

KST=ZoneInfo('Asia/Seoul')
WEIGHTS={'서울':.4376,'인천':.0558,'수원':.0448,'원주':.0306,'대전':.0633,'대구':.0838,'광주':.0647,'부산':.2194}
REGS=dict(zip(WEIGHTS,['11B10101','11B20201','11B20601','11D10401','11C20401','11H10701','11F20501','11H20201']))
STATIONS=dict(zip(WEIGHTS,[108,112,119,114,133,143,156,159]))
REGIONS=dict(zip(WEIGHTS,['11B00000','11B00000','11B00000','11D10000','11C20000','11H10000','11F20000','11H20000']))
HOST='https://apihub-pub.kma.go.kr'

def request(path,params):
    query=dict(params,authKey=os.environ['KMA_AUTH_KEY'])
    for attempt in range(3):
        try:
            with urlopen(HOST+path+'?'+urlencode(query),timeout=45) as r: body=r.read()
            return body.decode('utf-8' if body.lstrip().startswith((b'{',b'[')) else 'cp949')
        except Exception:
            if attempt==2: raise RuntimeError('KMA request failed: '+path) from None

def number(s):
    v=float(s)
    if not -80 <= v <= 65: raise ValueError('Missing or invalid temperature')
    return v

def weighted(values):
    if set(values)!=set(WEIGHTS): raise ValueError('All eight cities are required')
    return float(sum(Decimal(str(values[c]))*Decimal(str(w)) for c,w in WEIGHTS.items()).quantize(Decimal('.1'),rounding=ROUND_HALF_UP))

def minute_minimum(city,day):
    date=day.strftime('%Y%m%d'); cutoff=date+'0700'
    raw=request('/api/typ01/cgi-bin/url/nph-aws2_min',{'tm1':date+'0000','tm2':cutoff,'stn':STATIONS[city],'disp':0,'help':0})
    header=None; points={}
    for line in raw.splitlines():
        fields=line.lstrip('# ').split()
        if line.startswith('#'):
            if 'TA' in fields and 'STN' in fields: header=fields
            continue
        if not fields or not fields[0].isdigit():continue
        if header is None:raise ValueError('AWS temperature header missing')
        if len(fields)<=header.index('TA'):raise ValueError('AWS truncated row')
        tm=fields[0]
        if not date+'0000'<=tm<=cutoff or int(fields[header.index('STN')])!=STATIONS[city]:continue
        try:points[tm]=number(fields[header.index('TA')])
        except ValueError:continue
    # Allow a small reception delay at 07:00, never use later observations.
    if len(points)<400 or min(points)>date+'0005' or max(points)<date+'0650':
        raise ValueError('Incomplete 00–07 minute observations: '+city)
    return city,min(points.values()),{'first':min(points),'last':max(points),'count':len(points)}

def daily_extrema(day,kind):
    date=day.strftime('%Y%m%d')
    raw=request('/api/typ01/url/sfc_aws_day.php',{'tm1':date,'tm2':date,'obs':'ta_'+kind,'stn':':'.join(map(str,STATIONS.values())),'disp':0,'help':0})
    bystn={v:k for k,v in STATIONS.items()}; out={}
    for line in raw.splitlines():
        f=line.split()
        if len(f)>=6 and f[0]==date and f[1].isdigit() and int(f[1]) in bystn:
            out[bystn[int(f[1])]]=number(f[5])
    if set(out)!=set(WEIGHTS):raise ValueError('Prior-day daily extrema incomplete')
    return out

def parse_short(raw,issue):
    result={c:{} for c in WEIGHTS}; byreg={v:k for k,v in REGS.items()}
    for row in csv.reader(io.StringIO(raw)):
        f=[v.strip() for v in row]
        if len(f)<17 or f[0] not in byreg or not f[1].startswith(issue):continue
        valid=dt.datetime.strptime(f[2][:12],'%Y%m%d%H%M')
        period='am' if valid.hour<12 else 'pm'
        rec=result[byreg[f[0]]].setdefault(valid.date().isoformat(),{})
        rec[period]={'temperature':None if float(f[12])<=-99 else number(f[12]),'weather':f[16]}
    return result

def mid_temperatures(day):
    issue=day.strftime('%Y%m%d')+'06'
    raw=request('/api/typ01/url/fct_afs_wc.php',{'reg':'','tmfc1':issue,'tmfc2':issue,'disp':0,'help':0})
    result={c:{} for c in WEIGHTS};byreg={v:k for k,v in REGS.items()}
    for line in raw.splitlines():
        f=line.split()
        if len(f)<12 or f[0] not in byreg or not f[1].startswith(issue):continue
        date=dt.datetime.strptime(f[2][:8],'%Y%m%d').date().isoformat()
        rec={'min':number(f[6]),'max':number(f[7]),'mod':f[3]}
        old=result[byreg[f[0]]].get(date)
        if not old or f[3]=='A01':result[byreg[f[0]]][date]=rec
        elif old['mod']=='A02':
            old['min']=min(old['min'],rec['min']);old['max']=max(old['max'],rec['max'])
    return result

def mid_weather(region,day):
    raw=request('/api/typ02/openApi/MidFcstInfoService/getMidLandFcst',{'regId':region,'tmFc':day.strftime('%Y%m%d')+'0600','pageNo':1,'numOfRows':10,'dataType':'JSON'})
    data=json.loads(raw)['response']
    if str(data['header']['resultCode'])!='00':raise ValueError('Mid weather unavailable')
    return region,data['body']['items']['item'][0]

def collect(day):
    issue=day.strftime('%Y%m%d')+'05'
    short=parse_short(request('/api/typ01/url/fct_afs_dl.php',{'reg':'','tmfc1':issue,'tmfc2':issue,'disp':1,'help':0}),issue)
    mid=mid_temperatures(day)
    with ThreadPoolExecutor(max_workers=4) as pool:
        obs=list(pool.map(lambda c:minute_minimum(c,day),WEIGHTS))
        weather=dict(pool.map(lambda r:mid_weather(r,day),sorted(set(REGIONS.values()))))
    todaymin={c:v for c,v,_ in obs}
    previous_cities={k:daily_extrema(day-dt.timedelta(days=1),k) for k in ('min','max')}
    previous={k:weighted(v) for k,v in previous_cities.items()}
    rows=[]
    for n in range(9):
        date=(day+dt.timedelta(days=n)).isoformat();cities={}
        # 05:00 city land forecasts cover D through D+3. All cities must agree.
        use_short=n<=3
        for c in WEIGHTS:
            if use_short:
                rec=short[c].get(date,{})
                lo=todaymin[c] if n==0 else rec.get('am',{}).get('temperature')
                hi=rec.get('pm',{}).get('temperature')
                texts=[rec.get(p,{}).get('weather') for p in ('am','pm')]
            else:
                rec=mid[c].get(date,{})
                lo,hi=rec.get('min'),rec.get('max')
                w=weather[REGIONS[c]]
                texts=[w.get(f'wf{n}{p}',w.get(f'wf{n}')) for p in ('Am','Pm')]
            if lo is None or hi is None or not all(texts):raise ValueError('Incomplete forecast: '+c+' '+date)
            if lo>hi:raise ValueError('Min above max: '+c+' '+date)
            cities[c]={'min':lo,'max':hi,'weather':texts,'source':'short' if use_short else 'mid'}
        rows.append({'date':date,'cities':cities,**{k:weighted({c:v[k] for c,v in cities.items()}) for k in ('min','max')}})
    return {'date':day.isoformat(),'publication_kst':dt.datetime.combine(day,dt.time(7),KST).isoformat(),
            'forecast':rows,'previous_weighted':previous,'previous_observations':previous_cities,
            'morning_observation_coverage':{c:meta for c,v,meta in obs},'weights':WEIGHTS,
            'short_issue_kst':issue,'mid_issue_kst':day.strftime('%Y%m%d')+'06',
            'status':'automatic','automatic_generation':True}

def fetch_image(kind,cutoff,destination):
    origin='https://www.weather.go.kr'
    params={'mapType':'img','tm':cutoff.strftime('%Y.%m.%d.%H:%M'),'itv':'0.5','leaflet':'0','kmap':'0'}
    if kind=='satellite':
        path='/w/wnuri-img/rest/sat/images/gk2a.do';params.update(area='ko020lc',data='rgb-s-daynight')
    else:
        path='/w/wnuri-img/rest/radar/cmp/images.do';params.update(area='KWK',data='pop',itv='5')
    try:
        with urlopen(origin+path+'?'+urlencode(params),timeout=25) as response:rows=json.load(response)
        candidates=[]
        for row in rows:
            tm=dt.datetime.strptime(row['tm'],'%Y%m%d%H%M').replace(tzinfo=KST)
            url=urljoin(origin,row['url'])
            if cutoff-dt.timedelta(hours=1)<=tm<=cutoff and urlparse(url).netloc=='www.weather.go.kr':candidates.append((tm,url))
        if not candidates:raise ValueError('No image at report cutoff')
        tm,url=max(candidates)
        with urlopen(url,timeout=30) as response:body=response.read(12_000_001)
        if len(body)>12_000_000:raise ValueError('Image too large')
        from PIL import Image
        image=Image.open(io.BytesIO(body));image.load();image.convert('RGB').save(destination)
        return {'time':tm.isoformat(),'url':url,'available':True}
    except Exception:
        return {'available':False,'reason':'Image unavailable at 07 KST cutoff'}
