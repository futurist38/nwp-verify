"""Collect official optional images for the energy editor, independently of forecasts.

Each catalog belongs to a report date and carries each source's actual timestamp.
Run at report generation or editor release; never substitute a different day's image.
No browser-side external requests or additional API keys are required.
"""
import argparse
import base64
import datetime as dt
import html
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

KST = ZoneInfo('Asia/Seoul')
KMA = 'https://www.weather.go.kr'
WARNING_PAGE = KMA + '/w/special-report/overall.do'
PM10_PAGE = KMA + '/w/hazard/dust/dust-obs/values.do'
META = {
    'warning': {'label': '특보현황', 'title': '특보현황', 'provider': '기상청', 'page_url': WARNING_PAGE},
    'pm10': {'label': '미세먼지(PM10)', 'title': '미세먼지(PM10)', 'provider': '기상청 황사 관측망', 'page_url': PM10_PAGE},
    'fog': {'label': '안개(위성)', 'title': '안개(위성)', 'provider': '기상청 천리안2A호', 'page_url': KMA + '/w/weather/satellite/gk2a.do'},
}


def read(url):
    if urlparse(url).hostname != 'www.weather.go.kr':
        raise ValueError('Unexpected source host')
    req = Request(url, headers={'User-Agent': 'KPX-energy-weather/1.0', 'Referer': url.split('/w/')[0]})
    with urlopen(req, timeout=18) as response:
        body = response.read(12_000_001)
    if len(body) > 12_000_000:
        raise ValueError('Oversized source')
    return body


def text(url):
    return read(url).decode('utf-8')


def decoded_image(body):
    im = Image.open(io.BytesIO(body))
    if min(im.size) < 200 or im.width * im.height > 30_000_000:
        raise ValueError('Unexpected source image dimensions')
    im.load()
    rgba = im.convert('RGBA')
    background = Image.new('RGBA', rgba.size, 'white')
    background.alpha_composite(rgba)
    return background.convert('RGB')


def data_uri(im):
    im = im.copy()
    im.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    im.save(out, 'PNG', optimize=True)
    return 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode('ascii')


def parse_warning(markup):
    # KTKO50 is the current warning graphic; KTKO52 is preliminary and must not replace it.
    match = re.search(r'src=["\']([^"\']*KTKO50_(\d{12})_\d+_\d+\.png)[^"\']*["\']', markup)
    if not match:
        raise ValueError('Current warning graphic missing')
    return urljoin(KMA, html.unescape(match[1])), dt.datetime.strptime(match[2], '%Y%m%d%H%M').replace(tzinfo=KST)


def warning(now):
    url, stamp = parse_warning(text(KMA + '/w/wnuri-fct2021/weather/warning.do'))
    # An unchanged warning can remain effective for several days. Retain its issue date.
    if stamp > now:
        raise ValueError('Future warning issue')
    return {'src': data_uri(decoded_image(read(url))), 'time': stamp.isoformat(), 'timeKind': '발표', 'source_url': url}


def parse_pm10(markup):
    stamp = re.search(r'PM10\s*:\s*1시간 평균값.*?<span>(\d{4})년\s*(\d+)월\s*(\d+)일.*?(\d+)시</span>', markup, re.S)
    if not stamp:
        raise ValueError('PM10 observation timestamp missing')
    when = dt.datetime(*map(int, stamp.groups()), tzinfo=KST)
    rows = re.findall(r'<li class="pm10_(\d+)">\s*<a[^>]*>([^<]+)</a><span class="val">([^<]+)</span>', markup)
    if len(rows) < 10 or not any(v.isdigit() for _, _, v in rows):
        raise ValueError('PM10 observation values missing')
    return when, rows


def korean_font(size):
    candidates = [Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
                  Path('/usr/share/fonts/truetype/nanum/NanumGothic.ttf')]
    for file in candidates:
        if file.exists():
            return ImageFont.truetype(str(file), size)
    raise ValueError('Korean font missing')


def pm10(now):
    stamp, rows = parse_pm10(text(PM10_PAGE))
    if not dt.timedelta(0) <= now - stamp <= dt.timedelta(hours=3):
        raise ValueError('PM10 observations are stale or future')
    # Preserve KMA's displayed station placement and basemap, with legible raster labels.
    css = text(KMA + '/w/resources/css-2021/common-ui.css')
    positions = {stn: (int(x), int(y)) for stn, x, y in re.findall(r'li\.pm10_(\d+)\{left:\s*(\d+)px;top:\s*(\d+)px;', css)}
    if any(stn not in positions for stn, _, _ in rows):
        raise ValueError('PM10 station layout changed')
    raw = decoded_image(read(KMA + '/w/resources/images/korea_map3.png'))
    im = Image.new('RGB', (760, 940), 'white')
    im.paste(raw.resize((756, 780), Image.Resampling.LANCZOS), (-36, 54))
    draw = ImageDraw.Draw(im)
    draw.text((380, 20), '미세먼지(PM10) 1시간 평균', font=korean_font(30), fill='#172431', anchor='mt')
    name_font, value_font = korean_font(21), korean_font(23)
    for stn, name, value in rows:
        x, y = positions[stn];x, y = 40 + x * 2, 90 + y * 2
        width = draw.textlength(name, font=name_font) + draw.textlength(value, font=value_font) + 16
        draw.rounded_rectangle((x, y, x + width, y + 34), radius=4, fill='white', outline='#cbd5e1')
        draw.text((x + 4, y + 5), name, font=name_font, fill='#172431', anchor='lt')
        draw.text((x + width - 4, y + 4), value, font=value_font, fill='#b42318' if value.isdigit() else '#64748b', anchor='rt')
    draw.rectangle((0, 878, 760, 940), fill='white')
    draw.text((380, 879), stamp.strftime('%Y.%m.%d. %H:00 KST') + ' · 단위: ㎍/㎥', font=korean_font(24), fill='#334155', anchor='mt')
    draw.text((380, 913), '기상청 황사 관측망 · 미관측: –', font=korean_font(20), fill='#64748b', anchor='mt')
    return {'src': data_uri(im), 'time': stamp.isoformat(), 'source_url': PM10_PAGE}


def fog(now):
    at = now.replace(minute=now.minute // 10 * 10, second=0, microsecond=0)
    query = urlencode({'mapType': 'img', 'tm': at.strftime('%Y.%m.%d.%H:%M'), 'itv': '0.5',
                       'leaflet': '0', 'kmap': '0', 'area': 'ko020lc', 'data': 'fog'})
    rows = json.loads(text(KMA + '/w/wnuri-img/rest/sat/images/gk2a.do?' + query))
    candidates = []
    for row in rows:
        stamp = dt.datetime.strptime(row['tm'], '%Y%m%d%H%M').replace(tzinfo=KST)
        url = urljoin(KMA, row['url'])
        parsed = urlparse(url)
        if (parsed.scheme == 'https' and parsed.hostname == 'www.weather.go.kr' and not parsed.query and not parsed.fragment
                and re.fullmatch(r'/w/repositary/image/sat/gk2a/KO/gk2a_ami_le2_fog_ko020lc_\d{12}\.png', parsed.path)
                and stamp.date() == now.date() and dt.timedelta(0) <= at - stamp <= dt.timedelta(minutes=30)):
            candidates.append((stamp, url))
    if not candidates:
        raise ValueError('Fog image unavailable')
    stamp, url = max(candidates)
    return {'src': data_uri(decoded_image(read(url))), 'time': stamp.isoformat(), 'source_url': url}


def collect(day, now=None):
    now = now or dt.datetime.now(KST)
    def one(kind):
        result = {'id': kind, **META[kind], 'available': False}
        if day != now.strftime('%Y%m%d'):
            return {**result, 'reason': '이 날짜에 저장된 자료가 없습니다.'}
        try:
            result.update(globals()[kind](now), available=True)
        except Exception as exc:
            result.update(reason='공식 자료 수신 지연 · 직접 업로드 가능')
            print(kind + ': unavailable (' + type(exc).__name__ + ')')
        return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        sources = list(pool.map(one, META))
    return {'schema': 1, 'day': day, 'collected_kst': now.isoformat(timespec='seconds'), 'sources': sources}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='energy_generated')
    args = parser.parse_args()
    for folder in Path(args.out).iterdir():
        if folder.is_dir() and re.fullmatch(r'\d{8}', folder.name) and (folder/'report.json').exists():
            dest = folder/'sources.json'
            if folder.name != dt.datetime.now(KST).strftime('%Y%m%d') and dest.exists():
                continue
            catalog = collect(folder.name)
            dest.write_text(json.dumps(catalog, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
            print('Editor sources:', folder.name, [(s['id'], s['available']) for s in catalog['sources']])


if __name__ == '__main__':
    main()

