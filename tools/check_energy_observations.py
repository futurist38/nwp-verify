import os, urllib.request, urllib.parse
for tm,obs in [('202610290700','ta_min'),('20261028','ta_min'),('20261028','ta_max')]:
    q=urllib.parse.urlencode({'tm1':tm,'tm2':tm,'obs':obs,'stn':'108:112:119:114:133:143:156:159','disp':0,'help':0,'authKey':os.environ['KMA_AUTH_KEY']})
    try:
        with urllib.request.urlopen('https://apihub-pub.kma.go.kr/api/typ01/url/sfc_aws_day.php?'+q,timeout=60) as r:
            body=r.read().decode('cp949',errors='replace')
    except Exception:
        raise SystemExit('Observation API unavailable; request URL omitted')
    print(tm,obs,body[:6000])
