import requests,zipfile,io,math,json,shapefile
from pathlib import Path
url='https://naturalearth.s3.amazonaws.com/50m_physical/ne_50m_coastline.zip'
r=requests.get(url,timeout=25);r.raise_for_status();z=zipfile.ZipFile(io.BytesIO(r.content));reader=shapefile.Reader(shp=io.BytesIO(z.read('ne_50m_coastline.shp')))
r=math.radians;p1,p2=r(30),r(60);n=math.log(math.cos(p1)/math.cos(p2))/math.log(math.tan(math.pi/4+p2/2)/math.tan(math.pi/4+p1/2));f=math.cos(p1)*math.tan(math.pi/4+p1/2)**n/n;rho0=f/math.tan(math.pi/4+r(38)/2)**n
xmin,ymin,xmax,ymax=-443999.38881,-773848.93476,578999.20298,249149.65703
paths=[]
for shape in reader.shapes():
 pts=shape.points
 for a,b in zip(list(shape.parts),list(shape.parts)[1:]+[len(pts)]):
  part=[]
  for lon,lat in pts[a:b]:
   if not 119<=lon<=134 or not 30<=lat<=41:
    if len(part)>1:paths.append(part)
    part=[];continue
   rho=f/math.tan(math.pi/4+r(lat)/2)**n;theta=n*r(lon-126);x=rho*math.sin(theta)*6371000;y=(rho0-rho*math.cos(theta))*6371000;x=(x-xmin)/(xmax-xmin)*640;y=(ymax-y)/(ymax-ymin)*640
   if -5<=x<=645 and -5<=y<=645:part.append([round(x,2),round(y,2)])
   else:
    if len(part)>1:paths.append(part)
    part=[]
  if len(part)>1:paths.append(part)
result={'schema':1,'width':640,'height':640,'paths':paths,'source':'Natural Earth 1:50m coastline (public domain)','source_url':url,'projection':'KMA SFC-HSR LCC, standard parallels 30/60, central meridian 126; four corners verified against KMA image-player.js'}
Path('site/energy-radar-map.json').write_text(json.dumps(result,separators=(',',':')))
print('coast map',len(paths),'paths',sum(map(len,paths)),'points')
