"""Compare city-based KMA short forecasts; never log credentials/request URLs."""
import csv
import io
import json
import os
import urllib.parse
import urllib.request

REGS = {'서울':'11B10101','인천':'11B20201','수원':'11B20601','원주':'11D10401',
        '대전':'11C20401','대구':'11H10701','광주':'11F20501','부산':'11H20201'}
query=urllib.parse.urlencode({'reg':'','tmfc1':'2026102905','tmfc2':'2026102905',
                             'disp':1,'help':0,'authKey':os.environ['KMA_AUTH_KEY']})
url='https://apihub-pub.kma.go.kr/api/typ01/url/fct_afs_dl.php?'+query
try:
    with urllib.request.urlopen(url,timeout=90) as response:
        raw=response.read().decode('euc-kr',errors='replace')
except Exception:
    raise SystemExit('City short forecast request failed (credential and URL omitted).')
out=[]
for row in csv.reader(io.StringIO(raw)):
    row=[s.strip() for s in row]
    if not row or row[0] not in REGS.values():continue
    # Whitelist public meteorological fields, excluding forecaster identifiers.
    if len(row)>=16:
        out.append({'reg':row[0],'issue':row[1],'valid':row[2],'mod':row[3],
                    'ne':row[4],'temperature':row[12],'probability':row[13],
                    'sky':row[14],'precipitation':row[15],
                    'weather':row[16] if len(row)>16 else ''})
print(json.dumps({'rows':out,'count':len(out)},ensure_ascii=False))
if not out:raise SystemExit('No matching city rows returned; do not substitute gridded forecast.')
