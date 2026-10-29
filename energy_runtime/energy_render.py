from energy_layout import *
from energy_publication import publication_label
import sys,base64,datetime as dt
data=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
OUT=Path(sys.argv[2]);OUT.mkdir(parents=True,exist_ok=True)
records=data['forecast'];previous=data['previous_weighted'];norm=data['normals']
dates=[dt.date.fromisoformat(r['date']) for r in records]
week=data['icon_summary'];notes=data.get('weather_notes',['']*9)
cloud=[state('cloudy')];raincloud=[state('cloudy','rain','가끔'),state()]
original_group=group
BACKGROUND=False
editor={}
def uri(path):
 return 'data:image/png;base64,'+base64.b64encode(Path(path).read_bytes()).decode()
def group(im,states,cx,cy,maxwidth=500,size=100,tag=''):
 if im.size!=(1920,1080):raise ValueError('Unexpected image size')
 layer=Image.new('RGBA',im.size)
 original_group(layer,states,cx,cy,maxwidth,size,tag)
 bbox=layer.getbbox()
 if bbox:
  b=io.BytesIO();layer.crop(bbox).save(b,format='PNG')
  # Only page 1 groups are captured, since editor.json is written before page 2.
  editor.setdefault('groups',[]).append({'id':tag,'x':bbox[0],'y':bbox[1],'w':bbox[2]-bbox[0],'h':bbox[3]-bbox[1],'src':'data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()})
 if not BACKGROUND:im.paste(layer,(0,0),layer)
def spaced_text(im,xy,s,size=24,color='black',anchor='mm',spacing=1.3):
 d=ImageDraw.Draw(im)
 widths=[d.textlength(ch,font=font(size)) for ch in s]
 total=sum(widths)+spacing*max(0,len(s)-1)
 x,y=xy
 if anchor[0]=='r':x-=total
 elif anchor[0]=='m':x-=total/2
 for ch,w in zip(s,widths):
  d.text((x,y),ch,font=font(size),fill=color,anchor='lm',stroke_width=1)
  x+=w+spacing
def base():
 im=Image.new('RGB',(1920,1080),'white');d=ImageDraw.Draw(im);d.rectangle((0,0,1920,87),fill=GOLD)
 text(im,(960,44),'KPX 에너지기상정보',49,bold=True)
 text(im,(1880,49),publication_label(data['publication_kst']),24,anchor='rm',bold=True)
 return im
def maplabel(im,xy,s,size=28,color='black',bold=False):
 box=ImageDraw.Draw(im).textbbox(xy,s,font=font(size),anchor='mm',stroke_width=1 if bold else 0)
 ImageDraw.Draw(im).rectangle((box[0]-6,box[1]-4,box[2]+6,box[3]+4),fill='white')
 text(im,xy,s,size,color,bold=bold)
def footer(im,left):
 text(im,(38,1053),left,19,'#555555',anchor='lm')
 spaced_text(im,(1880,1053),'※ 본 자료는 기상청 자료를 이용해 제작되었습니다.',23,anchor='rm',spacing=1.2)
def render_page1(background=False):
 global BACKGROUND,editor
 BACKGROUND=background
 editor={'groups':[],'boundaries':[],'panels':[]}
 im=base();d=ImageDraw.Draw(im)
 for name,y,title,width in [('satellite',151,'위성영상',150),('radar',622,'강수현황(레이더)',240)]:
  path=OUT/(name+'.png');src_uri=None
  meta=data.get('imagery',{}).get(name,{})
  timestamp=meta.get('time','') if meta.get('available',False) else ''
  if path.exists():
   src=Image.open(path).convert('RGBA')
   src.thumbnail((365,365),Image.Resampling.LANCZOS)
   im.paste(src,(round(282-src.width/2),round((202 if name=='satellite' else 659)+(365-src.height)/2)),src)
   raw=io.BytesIO();src.save(raw,format='PNG');src_uri='data:image/png;base64,'+base64.b64encode(raw.getvalue()).decode()
  else:text(im,(282,y+215),'자료 수신 지연',28,'#666666')
  d.rectangle((67,y,67+width,y+35),fill='#fff300',outline='black')
  spaced_text(im,(67+width/2,y+18),title,24,spacing=1.8)
  if timestamp:
   stamp=dt.datetime.fromisoformat(timestamp).astimezone(dt.timezone(dt.timedelta(hours=9)))
   text(im,(497,y+18),stamp.strftime('%H:%M')+' KST',21,'#333333',anchor='rm')
  editor['panels'].append(dict(id=name,title=title,time=timestamp,src=src_uri))
 def boundary(im,points):
  editor['boundaries'].append({'points':points,'color':'#3c6090','width':5})
  if background:return
  p0,p1,p2,p3=[np.array(p) for p in points]
  pts=[tuple((1-t)**3*p0+3*(1-t)**2*t*p1+3*(1-t)*t*t*p2+t**3*p3) for t in np.linspace(0,1,150)]
  smoothline(im,pts,'#3c6090',5)
 for idx,x in enumerate([550,1236]):
  day=dates[idx];title=f"{['오늘예보','내일예보'][idx]} ({day.month}/{day.day}, {'월화수목금토일'[day.weekday()]})"
  d.rounded_rectangle((x,174,x+660,1024),radius=40,outline=GRAY,width=5)
  d.rectangle((x+100,152,x+560,202),fill='white');text(im,(x+330,176),title,35,NAVY,bold=True)
  paste(im,ASSETS/'maps/korea_outline.png',(x+43,260,574,626))
  if data.get('status')=='approved_snapshot':
   if idx==0:
    group(im,occasion,x+330,450,maxwidth=390,size=135,tag='today-central')
    group(im,cloud,x+310,706,maxwidth=370,size=135,tag='today-south')
    boundary(im,[(x+80,659),(x+260,622),(x+440,528),(x+545,398)])
   else:
    group(im,[state('cloudy'),state()],x+142,421,maxwidth=265,size=105,tag='tomorrow-northwest')
    group(im,raincloud,x+348,655,maxwidth=460,size=128,tag='tomorrow-other')
    boundary(im,[(x+80,568),(x+300,508),(x+310,418),(x+270,261)])
  else:
   north,south=week[idx]['north'],week[idx]['south']
   if north==south:group(im,north,x+330,530,maxwidth=480,size=145,tag=f'day{idx}-nationwide')
   else:
    group(im,north,x+330,435,maxwidth=450,size=135,tag=f'day{idx}-central')
    group(im,south,x+330,710,maxwidth=450,size=135,tag=f'day{idx}-south')
    boundary(im,[(x+80,635),(x+240,630),(x+420,565),(x+550,480)])
  rec=records[idx];prev=previous if idx==0 else records[0]
  d.rectangle((x+110,894,x+637,1008),fill='white')
  right=x+630
  spaced_text(im,(right,928),'전국가중 최고 / 최저기온 (전일대비, ℃)',25,anchor='rm',spacing=1.3)
  spans=[(f"{rec['max']:.1f}",43,RED),(f"({rec['max']-prev['max']:+.1f})",29,RED),(' / ',36,'black'),(f"{rec['min']:.1f}",43,BLUE),(f"({rec['min']-prev['min']:+.1f})",29,BLUE)]
  widths=[d.textlength(label,font=font(size))+2 for label,size,color in spans]
  left=right-sum(widths)
  for (label,size,color),width in zip(spans,widths):
   text(im,(left,980),label,size,color,anchor='lm',bold=True)
   left+=width
 
 footer(im,'전일대비: 전일 관측 최고·최저 기준 · 기온은 소수 첫째 자리로 반올림 후 계산')
 return im
render_page1(True).save(OUT/'background.webp',lossless=True)
render_page1(False).save(OUT/'01.webp',lossless=True)
editor['background']='background.webp'
editor['width']=1920;editor['height']=1080
editor['palette']={p.stem:uri(p) for p in (ASSETS/'icons').glob('*.png')}
(OUT/'editor.json').write_text(json.dumps(editor,ensure_ascii=False),encoding='utf-8')
# Page 2
im=base();d=ImageDraw.Draw(im);d.rounded_rectangle((27,107,1884,1028),radius=33,outline=GRAY,width=5)
x0=184;x1=1840;cw=(x1-x0)/9;xs=np.array([x0+(i+.5)*cw for i in range(9)])
d.rectangle((94,227,184,995),fill='#fac495')
for y in [155,227,449,995]:d.line((94,y,1840,y),fill='black',width=3)
for i,day in enumerate(dates):
 cx=xs[i];text(im,(cx,190),f'{day.month}/{day.day}('+ '월화수목금토일'[day.weekday()]+')',30,RED if day.weekday()>4 else 'black',bold=True)
 if i:
  for y in range(155,449,8):d.line((x0+i*cw,y,x0+i*cw,y+2),fill='#888888')
 n,s=week[i]['north'],week[i]['south']
 if n==s:group(im,n,cx,321,maxwidth=cw-18,size=100,tag=f'day{i}-merged')
 else:
  group(im,n,cx,279,maxwidth=cw-18,size=67,tag=f'day{i}-central');group(im,s,cx,369,maxwidth=cw-18,size=67,tag=f'day{i}-south')
 if notes[i]:
  # Two short lines preserve readability in narrow daily columns.
  words=notes[i].split(' ');cut=max(1,len(words)//2)
  text(im,(cx,412),' '.join(words[:cut]),18,'#555555');text(im,(cx,434),' '.join(words[cut:]),18,'#555555')
text(im,(139,280),'중부',33,bold=True);text(im,(139,375),'남부',33,bold=True);text(im,(139,717),'기온',33,bold=True)
low=np.array([r['min'] for r in records]);high=np.array([r['max'] for r in records])
values=[r[k] for r in records for k in ['min','max']]+[n[k][b] for n in norm for k in ['min','max'] for b in ['lower','upper']]
vmin=min(values)-2;vmax=max(values)+2
def yy(v):return 900-(v-vmin)/(vmax-vmin)*310
for k,color in [('max','#fbe3d3'),('min','#dceaf7')]:
 d.polygon(list(zip(xs,[yy(n[k]['upper']) for n in norm]))+list(zip(xs[::-1],[yy(n[k]['lower']) for n in norm[::-1]])),fill=color)
# Light anomaly tint over normal bands, below forecast lines and labels.
shade=Image.new('RGBA',im.size,(0,0,0,0));sd=ImageDraw.Draw(shade)
for i,r in enumerate(records):
 for cold in [True,False]:
  kinds=[k for k in ['min','max'] if (r[k]<norm[i][k]['p10'] if cold else r[k]>norm[i][k]['p90'])]
  if not kinds:continue
  top=min(yy(r[k]) for k in kinds)-62;bottom=max(yy(r[k]) for k in kinds)+60
  sd.rectangle((x0+i*cw+4,top,x0+(i+1)*cw-4,bottom),fill=(40,130,235,28) if cold else (235,55,60,28))
im.paste(shade,(0,0),shade)
for vals,color in [(high,RED),(low,BLUE)]:
 grid=np.linspace(0,8,401);ys=PchipInterpolator(np.arange(9),vals)(grid)
 smoothline(im,[(xs[0]+g*cw,yy(v)) for g,v in zip(grid,ys)],color,6)
 for i,v in enumerate(vals):
  x=xs[i];y=yy(v);d.ellipse((x-7,y-7,x+7,y+7),fill=color)
  text(im,(x,y+(-30 if color==RED else 30)),f'{v:.1f}',27,color,bold=True)
flags=[]
for i,r in enumerate(records):
 for cold in [True,False]:
  kinds=[k for k in ['min','max'] if (r[k]<norm[i][k]['p10'] if cold else r[k]>norm[i][k]['p90'])]
  if not kinds:continue
  top=min(yy(r[k]) for k in kinds)-62;bottom=max(yy(r[k]) for k in kinds)+60
  color=BLUE if cold else RED;d.rectangle((x0+i*cw+4,top,x0+(i+1)*cw-4,bottom),outline=color,width=4)
  lab='이상저온' if cold else '이상고온';d.rectangle((xs[i]-64,top-18,xs[i]+64,top+18),fill='white');text(im,(xs[i],top),lab,24,color,bold=True)
  flags.append({'date':r['date'],'type':lab,'variables':kinds})
# Four-item legend, reserved above the plotted curves at the upper right.
d.rounded_rectangle((1220,460,1835,551),radius=10,fill='white',outline='#dddddd',width=1)
for x,y,color,label,band in [(1240,482,'#fbe3d3','최고기온 평년범위',True),(1540,482,'#dceaf7','최저기온 평년범위',True),(1240,525,BLUE,'최저기온',False),(1540,525,RED,'최고기온',False)]:
 if band:d.rectangle((x,y-8,x+34,y+8),fill=color)
 else:
  d.line((x,y,x+34,y),fill=color,width=4);d.ellipse((x+13,y-4,x+21,y+4),fill=color)
 text(im,(x+44,y),label,22,'#444444',anchor='lm')
text(im,(1150,482),'단위: ℃',22,'#666666')
text(im,(1000,975),'평년범위: 일평년 평균 ± 0.43σ  |  이상저온 < P10 · 이상고온 > P90 (1991~2020)',20,'#555555')
footer(im,'전국가중기온: 회사 8개 지점 가중치 적용')
im.save(OUT/'02.webp',lossless=True)
