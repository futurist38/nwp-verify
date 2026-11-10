"""Compare PNG→WebP directly; never recompress an existing WebP.

Select one original map for each of 3 models × 5 panels, record SSIM against
PNG, encoder time and byte sizes. Save originals/candidates plus native pixel
crops for contour-number, wind-barb, title and legend readability review.
"""
import argparse
from io import BytesIO
import json
from pathlib import Path
import time
import numpy as np
from PIL import Image, ImageDraw
from skimage.metrics import structural_similarity

SETTINGS = [(82,4),(82,6),(78,6)]


def benchmark(source, output):
    output.mkdir(parents=True, exist_ok=True)
    rows=[]
    for model in ['ecmwf','gfs','kim']:
        for panel in ['sfc','p500','t2m','dswrf','tcc']:
            matches=sorted(source.glob(f'????????/*/{model}_*_f024_{panel}.png'))
            if not matches:
                print(f'[webp] missing original: {model}/{panel}');continue
            path=matches[-1]
            with Image.open(path) as src:
                original=src.convert('RGB')
            folder=output/f'{model}-{panel}';folder.mkdir(exist_ok=True)
            original.save(folder/'original.png')
            source_pixels=np.asarray(original)
            variants=[('PNG original',original)]
            for quality,method in SETTINGS:
                start=time.perf_counter();buf=BytesIO()
                original.save(buf,format='WEBP',quality=quality,method=method)
                elapsed=time.perf_counter()-start
                data=buf.getvalue();(folder/f'q{quality}-m{method}.webp').write_bytes(data)
                candidate=Image.open(BytesIO(data)).convert('RGB')
                score=structural_similarity(source_pixels,np.asarray(candidate),channel_axis=2,data_range=255)
                rows.append({'source':str(path),'model':model,'panel':panel,'quality':quality,'method':method,
                             'bytes':len(data),'seconds':round(elapsed,4),'ssim_png':round(float(score),6)})
                if quality==78 or method==4:
                    variants.append((f'q{quality} m{method}',candidate))
            width,height=original.size
            boxes=[(max(0,width//2-160),max(0,height//2-100),min(width,width//2+160),min(height,height//2+100)),
                   (0,0,min(320,width),min(200,height)),
                   (max(0,width-320),max(0,height-200),width,height)]
            sheet=Image.new('RGB',(960,230*len(variants)), 'white');draw=ImageDraw.Draw(sheet)
            for row,(label,im) in enumerate(variants):
                draw.text((8,row*230+6),label,fill='black')
                for col,box in enumerate(boxes):
                    sheet.paste(im.crop(box),(col*320,row*230+25))
            sheet.save(folder/'readability.png')
    summary=[]
    base=sum(r['bytes'] for r in rows if (r['quality'],r['method'])==(82,4))
    for q,m in SETTINGS:
        group=[r for r in rows if (r['quality'],r['method'])==(q,m)]
        total=sum(r['bytes'] for r in group)
        summary.append({'quality':q,'method':m,'images':len(group),'bytes':total,
                        'saving_vs_82_4_pct':round(100*(1-total/base),2) if base else None,
                        'ssim_png_mean':round(float(np.mean([r['ssim_png'] for r in group])),6) if group else None,
                        'ssim_png_min':min((r['ssim_png'] for r in group),default=None),
                        'encode_seconds':round(sum(r['seconds'] for r in group),3)})
    report={'comparison':'direct original PNG to WebP; SSIM reference is PNG', 'summary':summary,'images':rows}
    (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('[webp] '+json.dumps(summary))
    if len(rows)!=45:
        print('::warning::Incomplete sample set; do not extrapolate across all three models')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,default=Path('output'))
    parser.add_argument('--output',type=Path,default=Path('webp-benchmark'))
    args=parser.parse_args();benchmark(args.source,args.output)
