from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
import json,zipfile,io,math
import numpy as np
from scipy.interpolate import PchipInterpolator
ROOT=Path(__file__).resolve().parent; BASE=ROOT

ASSETS=BASE/'energy_assets'
import os
FONT=Path(os.environ.get('ENERGY_FONT','/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'))
FONTS={}
def font(n):
 if n not in FONTS:FONTS[n]=ImageFont.truetype(str(FONT),n)
 return FONTS[n]
NAVY='#00235b';RED='#e60012';BLUE='#0074bf';GOLD='#ffc400';GRAY='#858585'
def text(im,xy,s,size=28,color='black',anchor='mm',bold=False):
 ImageDraw.Draw(im).text(xy,s,font=font(size),fill=color,anchor=anchor,stroke_width=1 if bold else 0)
def paste(im,path,box):
 src=Image.open(path).convert('RGBA');src=src.resize((int(box[2]),int(box[3])),Image.Resampling.LANCZOS);im.paste(src,(int(box[0]),int(box[1])),src)
def smoothline(im,points,color,width):
 layer=Image.new('RGBA',(3840,2160));ld=ImageDraw.Draw(layer);ld.line([(int(x*2),int(y*2)) for x,y in points],fill=color,width=width*2,joint='curve');layer=layer.resize(im.size,Image.Resampling.LANCZOS);im.paste(layer,(0,0),layer)
def base():
 im=Image.new('RGB',(1920,1080),'white');d=ImageDraw.Draw(im);d.rectangle((0,0,1920,87),fill=GOLD)
 text(im,(960,44),'KPX 에너지기상예보',49,bold=True)
 text(im,(38,44),'배치 시안',24,anchor='lm')
 text(im,(1860,57),'예시 기준 : 2026.10.28.(수)',24,anchor='rm')
 return im
# Each state is a simultaneous sky/precipitation condition. Sequence means time change.
def state(sky='clear',precip=None,frequency=None):return {'sky':sky,'precip':precip,'frequency':frequency}
def tokens(states):
 out=[]
 for i,s in enumerate(states):
  if i:out.append({'kind':'arrow'})
  occasional=bool(s['precip'] and s['frequency'] in ['가끔','때때로'])
  out.append({'kind':'weather','icon':s['sky'] if occasional else (s['precip'] or s['sky']),'parentheses':occasional,'auxiliary':s['precip'] if occasional else None})
 return out
clear=[state()];rain=[state('cloudy','rain')];occasion=[state('cloudy','rain','가끔')]
partly=[state('sun_cloud_b')]
change_rain=[state('sun_cloud_b'),state('cloudy','rain','가끔')]
change_cloud=[state(),state('sun_cloud_b')]
after_rain=[state('cloudy','rain','때때로'),state()]
week=[{'north':clear,'south':clear},{'north':change_rain,'south':change_cloud},{'north':after_rain,'south':after_rain},{'north':clear,'south':clear},{'north':rain,'south':rain},{'north':[state('cloudy'),state()],'south':[state('cloudy','rain'),state()]},{'north':clear,'south':clear},{'north':clear,'south':clear},{'north':clear,'south':clear}]
placed=[]
def icon(im,name,cx,cy,size):
 src=Image.open(ASSETS/'icons'/f'{name}.png').convert('RGBA')
 bbox=src.getchannel('A').getbbox()
 if bbox:src=src.crop(bbox)
 factor=size/max(src.size);src=src.resize((max(1,round(src.width*factor)),max(1,round(src.height*factor))),Image.Resampling.LANCZOS)
 im.paste(src,(round(cx-src.width/2),round(cy-src.height/2)),src)
 return src.height
def parenthesis(im,ch,cx,cy,height):
 glyph=Image.new('RGBA',(240,280));ImageDraw.Draw(glyph).text((20,0),ch,font=font(180),fill='black')
 glyph=glyph.crop(glyph.getchannel('A').getbbox());ratio=height/glyph.height
 glyph=glyph.resize((max(2,round(glyph.width*ratio)),max(2,round(height))),Image.Resampling.LANCZOS)
 im.paste(glyph,(round(cx-glyph.width/2),round(cy-glyph.height/2)),glyph)
def group(im,states,cx,cy,maxwidth=500,size=100,tag=''):
 ts=tokens(states)
 def widths(sz):return [(sz*.38 if t['kind']=='arrow' else sz*(1.86 if t['parentheses'] else 1)) for t in ts]
 ws=widths(size);gap=size*.06
 scale=min(1,maxwidth/(sum(ws)+gap*max(0,len(ws)-1)));size*=scale;gap*=scale;ws=widths(size)
 x=cx-(sum(ws)+gap*max(0,len(ws)-1))/2;draw=ImageDraw.Draw(im)
 for t,w in zip(ts,ws):
  if t['kind']=='arrow':
   y=cy;h=size*.25
   draw.polygon([(x,y-h*.5),(x+w*.62,y-h*.5),(x+w*.62,y-h),(x+w,y),(x+w*.62,y+h),(x+w*.62,y+h*.5),(x,y+h*.5)],fill='#ffd1c9',outline='#c74848',width=2)
  else:
   icon(im,t['icon'],x+size*.5,cy,size)
   if t['parentheses']:
    rain_height=icon(im,t['auxiliary'],x+size*1.43,cy,size*.52)
    parenthesis(im,'(',x+size*1.09,cy,rain_height*1.03)
    parenthesis(im,')',x+size*1.77,cy,rain_height*1.03)
  x+=w+gap
 placed.append({'tag':tag,'center':[cx,cy],'max_width':maxwidth,'visible_icon_size':size,'auxiliary_ratio':.52,'tokens':ts})
