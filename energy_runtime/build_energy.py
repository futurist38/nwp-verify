import argparse, datetime as dt, json, os, subprocess, sys, zipfile
from collections import Counter
from pathlib import Path
from energy_data import collect, fetch_image, KST

ROOT=Path(__file__).resolve().parent

def state_from(text):
    sky='cloudy' if '흐' in text else 'sun_cloud_b' if '구름' in text else 'clear'
    precip='snow_rain_a' if '눈' in text and '비' in text else 'snow' if '눈' in text else 'shower' if '소나기' in text else 'rain' if '비' in text else None
    freq='가끔' if '가끔' in text or '때때로' in text else None
    return {'sky':sky,'precip':precip,'frequency':freq}

def weather_groups(record):
    out={};notes=[]
    for region,cities in [('north',['서울','인천','수원','원주','대전']),('south',['대구','광주','부산'])]:
        seq=[]
        for p in range(2):
            texts={c:' '.join(record['cities'][c]['weather'][p].split()) for c in cities}
            common=Counter(texts.values()).most_common(1)[0][0]
            value=state_from(common)
            if not seq or seq[-1]!=value:seq.append(value)
            exceptions=[c for c,t in texts.items() if state_from(t)!=value]
            if exceptions:notes.append(','.join(exceptions)+' 상이')
        out[region]=seq
    return out,' / '.join(dict.fromkeys(notes))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--date');parser.add_argument('--out',default='energy_generated');args=parser.parse_args()
    now=dt.datetime.now(KST);day=dt.date.fromisoformat(args.date) if args.date else now.date()
    cutoff=dt.datetime.combine(day,dt.time(7),KST)
    if now<cutoff:raise SystemExit('07 KST observation cutoff has not arrived')
    dest=Path(args.out)/day.strftime('%Y%m%d');dest.mkdir(parents=True,exist_ok=True)
    data=collect(day)
    normals=json.loads((ROOT/'energy_normals.json').read_text())
    data['normals']=[normals[dt.date.fromisoformat(r['date']).strftime('%m-%d')] for r in data['forecast']]
    groups=[weather_groups(r) for r in data['forecast']]
    data['icon_summary']=[g for g,n in groups];data['weather_notes']=[n for g,n in groups]
    data['imagery']={name:fetch_image(name,cutoff,dest/(name+'.png')) for name in ['satellite','radar']}
    data['generated_kst']=now.isoformat(timespec='seconds')
    data['publication_label_format']='발표시점: YYYY. MM. DD.(요일) HH시 기준'
    data['retention_days']=30;data['show_provisional_label']=False
    (dest/'report.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    if not (ROOT/'energy_assets').exists():
        with zipfile.ZipFile(ROOT/'energy_assets.zip') as z:z.extractall(ROOT/'energy_assets')
    subprocess.run([sys.executable,str(ROOT/'energy_render.py'),str(dest/'report.json'),str(dest)],check=True)
    from PIL import Image
    for file in ['01.webp','02.webp','background.webp']:
        with Image.open(dest/file) as im:
            im.load();assert im.size==(1920,1080)
    # Original input panels are already embedded in the outputs, don't retain duplicate images.
    for file in ['satellite.png','radar.png']:(dest/file).unlink(missing_ok=True)
    print('ENERGY_REPORT_JSON='+json.dumps(data,ensure_ascii=False,separators=(',',':')))
    print('Generated and validated:',dest)

if __name__=='__main__':main()
