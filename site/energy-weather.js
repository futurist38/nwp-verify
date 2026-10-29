'use strict';
const el=id=>document.getElementById(id);
const format=d=>`${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}`;
const clone=o=>JSON.parse(JSON.stringify(o));
const labels={clear:'맑음',sun_cloud_a:'구름조금',sun_cloud_b:'구름많음',cloudy:'흐림',rain:'비',shower:'소나기',snow:'눈',snow_rain_a:'눈·비',thunderstorm:'뇌우',fog:'안개',haze:'연무',dust:'황사',arrow_right:'화살표 →'};
// Editor-only symbols are available for both archived and newly generated reports.
const editorSymbols={arrow_right:'data:image/svg+xml;charset=utf-8,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="76" height="50" viewBox="0 0 76 50"><path d="M2 13 H46 V2 L74 25 L46 48 V37 H2 Z" fill="#ffd1c9" stroke="#c74848" stroke-width="3" stroke-linejoin="round"/></svg>')};
const imageryEndpoint=document.querySelector('meta[name=energy-imagery-endpoint]')?.content.trim().replace(/\/$/,'')||'';
let index,loadToken=0,refreshing=false;
function image(src){return new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=reject;im.src=src;});}
// Keep the opposite corner fixed, preserving aspect ratio and page edit bounds.
function resizedGroupRect(start,corner,x,y,bounds){
 const east=corner.includes('e'),south=corner.includes('s');
 const ax=east?start.x:start.x+start.w,ay=south?start.y:start.y+start.h;
 const dx=(x-ax)*(east?1:-1),dy=(y-ay)*(south?1:-1);
 const availableW=east?bounds.x+bounds.w-ax:ax-bounds.x;
 const availableH=south?bounds.y+bounds.h-ay:ay-bounds.y;
 const maxScale=Math.max(0,Math.min(800/start.w,availableW/start.w,availableH/start.h));
 const minScale=Math.min(maxScale,20/Math.max(start.w,start.h));
 const scale=Math.max(minScale,Math.min(maxScale,(dx*start.w+dy*start.h)/(start.w*start.w+start.h*start.h)));
 const w=start.w*scale,h=start.h*scale;
 return {x:east?ax:ax-w,y:south?ay:ay-h,w,h};
}
class ReportEditor {
 constructor(page){
  this.page=page;this.node=id=>el(id+(page===2?'2':''));
  this.canvas=this.node('editorCanvas');this.ctx=this.canvas.getContext('2d');this.sprites=new Map();this.clear();
  this.node('edit').onclick=()=>{if(!this.scene)return;this.editing=!this.editing;this.node('editorControls').hidden=!this.editing;this.node('edit').textContent=this.editing?`${page}페이지 편집 닫기`:this.title();this.draw();};
  this.node('undo').onclick=()=>{if(this.history.length){this.scene=this.history.pop();this.selected=null;this.changed=true;this.controls();this.draw();}};
  this.node('reset').onclick=()=>{if(!this.scene)return;this.remember();this.scene=clone(this.original);this.selected=null;this.controls();this.draw();};
  this.node('remove').onclick=()=>{if(!this.selected)return;this.remember();this.scene[this.selected.type==='group'?'groups':'boundaries'].splice(this.selected.index,1);this.selected=null;this.controls();this.draw();};
  this.node('size').onchange=e=>this.resize(Number(e.target.value)/100);
  this.node('addIcon').onclick=()=>this.chooseIcon(false);
  this.node('replaceIcon').onclick=()=>this.chooseIcon(true);
  if(page===1)this.node('addBoundary').onclick=()=>{if(!this.scene)return;this.remember();this.scene.boundaries.push({points:[[650,620],[790,620],[990,550],[1100,470]],color:'#3c6090',width:5});this.selected={type:'boundary',index:this.scene.boundaries.length-1};this.controls();this.draw();};
  this.node('saveLayout').onclick=()=>{if(!this.scene)return;try{localStorage.setItem(this.storageKey(),JSON.stringify(this.scene));this.node('editStatus').textContent=`${page}페이지 편집 상태를 이 브라우저에 저장했습니다. 공유하려면 PNG로 저장해 주세요.`;}catch{this.node('editStatus').textContent='브라우저 저장 공간이 부족합니다. PNG로 저장해 주세요.';}};
  this.node('exportEdit').onclick=()=>this.download(true);
  el('save'+page).onclick=e=>{e.preventDefault();return this.download(Boolean(this.scene&&this.changed));};
  this.canvas.addEventListener('pointerdown',e=>this.pointerDown(e));
  this.canvas.addEventListener('pointermove',e=>this.pointerMove(e));
  for(const event of ['pointerup','pointercancel','lostpointercapture'])this.canvas.addEventListener(event,()=>{this.drag=null;this.canvas.style.cursor=this.editing?'grab':'default';});
 }
 title(){return this.page===1?'1페이지 편집':'2페이지 날씨 아이콘 편집';}
 clear(){this.scene=null;this.original=null;this.background=null;this.selected=null;this.drag=null;this.history=[];this.editing=false;this.changed=false;this.day='';this.sprites.clear();this.node('editorControls').hidden=true;this.canvas.hidden=true;el('page'+this.page).hidden=false;this.node('edit').disabled=true;this.node('edit').textContent=this.title();}
 storageKey(){return `kpx-energy-editor-v1-${this.day}-${this.original?.revision}`+(this.page===2?'-page2':'');}
 remember(){this.changed=true;this.history.push(clone(this.scene));if(this.history.length>40)this.history.shift();}
 async sprite(src){if(!this.sprites.has(src))this.sprites.set(src,await image(src));return this.sprites.get(src);}
 bounds(){return this.page===2?{x:188,y:234,w:1648,h:210}:{x:0,y:90,w:1920,h:935};}
 constrain(g){const b=this.bounds();const scale=Math.min(1,b.w/g.w,b.h/g.h);g.w*=scale;g.h*=scale;g.x=Math.max(b.x,Math.min(b.x+b.w-g.w,g.x));g.y=Math.max(b.y,Math.min(b.y+b.h-g.h,g.y));}
 controls(){this.node('remove').disabled=!this.selected;this.node('size').disabled=this.selected?.type!=='group';this.node('replaceIcon').disabled=this.selected?.type!=='group';this.node('size').value='100';this.node('undo').disabled=!this.history.length;}
 selectionHandles(){
  if(this.selected?.type!=='group'||!this.scene)return [];
  const g=this.scene.groups[this.selected.index];if(!g)return [];
  return [['nw',g.x,g.y],['ne',g.x+g.w,g.y],['se',g.x+g.w,g.y+g.h],['sw',g.x,g.y+g.h]];
 }
 handleAt(x,y,pointerType='mouse'){
  const radius=(pointerType==='touch'?18:10)*1920/this.canvas.getBoundingClientRect().width;
  return this.selectionHandles().map(([corner,hx,hy])=>({corner,distance:Math.hypot(x-hx,y-hy)})).filter(h=>h.distance<=radius).sort((a,b)=>a.distance-b.distance)[0]?.corner;
 }
 drawSelection(){
  if(this.selected?.type!=='group')return;
  const g=this.scene.groups[this.selected.index],c=this.ctx,unit=1920/this.canvas.getBoundingClientRect().width;
  c.save();c.strokeStyle='#7c3aed';c.fillStyle='white';c.lineWidth=2*unit;c.setLineDash([6*unit,4*unit]);c.strokeRect(g.x,g.y,g.w,g.h);c.setLineDash([]);
  for(const [,x,y] of this.selectionHandles()){c.fillRect(x-5*unit,y-5*unit,10*unit,10*unit);c.strokeRect(x-5*unit,y-5*unit,10*unit,10*unit);}
  c.restore();
 }
 point(e){const r=this.canvas.getBoundingClientRect();return [(e.clientX-r.left)*1920/r.width,(e.clientY-r.top)*1080/r.height];}
 pointerDown(e){
  if(!this.editing||!this.scene)return;
  const [x,y]=this.point(e),corner=this.handleAt(x,y,e.pointerType);this.drag=null;
  if(corner){
   const index=this.selected.index;this.drag={type:'resize',index,corner,start:clone(this.scene.groups[index])};
  }else{
   this.selected=null;
   if(this.page===1)for(let b=0;b<this.scene.boundaries.length;b++)for(let p=0;p<4;p++){const xy=this.scene.boundaries[b].points[p];if(Math.hypot(x-xy[0],y-xy[1])<20){this.selected={type:'boundary',index:b};this.drag={type:'point',b,p};}}
   if(!this.drag)for(let i=this.scene.groups.length-1;i>=0;i--){const g=this.scene.groups[i];if(x>=g.x&&x<=g.x+g.w&&y>=g.y&&y<=g.y+g.h){this.selected={type:'group',index:i};this.drag={type:'group',index:i,dx:x-g.x,dy:y-g.y};break;}}
  }
  if(this.drag){e.preventDefault();this.remember();this.canvas.setPointerCapture(e.pointerId);this.canvas.style.cursor=this.drag.type==='resize'?(['nw','se'].includes(corner)?'nwse-resize':'nesw-resize'):'grabbing';}
  this.controls();this.draw();
 }
 pointerMove(e){
  if(!this.editing||!this.scene)return;const [x,y]=this.point(e);
  if(!this.drag){const corner=this.handleAt(x,y,e.pointerType);this.canvas.style.cursor=corner?(['nw','se'].includes(corner)?'nwse-resize':'nesw-resize'):'grab';return;}
  if(this.drag.type==='resize')Object.assign(this.scene.groups[this.drag.index],resizedGroupRect(this.drag.start,this.drag.corner,x,y,this.bounds()));
  else if(this.drag.type==='point'&&this.page===1)this.scene.boundaries[this.drag.b].points[this.drag.p]=[Math.max(0,Math.min(1920,x)),Math.max(90,Math.min(1025,y))];
  else if(this.drag.type==='group'){const g=this.scene.groups[this.drag.index];g.x=x-this.drag.dx;g.y=y-this.drag.dy;this.constrain(g);}
  this.draw();
 }
 resize(scale){if(this.selected?.type!=='group'||!Number.isFinite(scale)||scale<=0)return;this.remember();const g=this.scene.groups[this.selected.index],w=Math.min(800,g.w*scale),h=w*g.h/g.w;g.x-=(w-g.w)/2;g.y-=(h-g.h)/2;g.w=w;g.h=h;this.constrain(g);this.controls();this.draw();}
 async chooseIcon(replace){
  if(!this.scene||(replace&&this.selected?.type!=='group'))return;
  const active=this.scene,token=loadToken,chosen=this.selected?.index,iconName=this.node('iconChoice').value,src=this.scene.palette[iconName];if(!src)return;
  try{const im=await this.sprite(src);if(token!==loadToken||active!==this.scene||(replace&&(this.selected?.type!=='group'||this.selected.index!==chosen)))return;
   this.remember();let g;
   if(replace){const prev=this.scene.groups[chosen],scale=Math.min(prev.w/im.width,prev.h/im.height);g={id:prev.id,src,w:im.width*scale,h:im.height*scale};g.x=prev.x+(prev.w-g.w)/2;g.y=prev.y+(prev.h-g.h)/2;this.scene.groups[chosen]=g;}
   else{const size=iconName==='arrow_right'?(this.page===2?30:50):(this.page===2?70:130),scale=size/Math.max(im.width,im.height);g={id:'added-'+Date.now(),src,w:im.width*scale,h:im.height*scale,x:this.page===2?240:800,y:this.page===2?260:450};this.scene.groups.push(g);this.selected={type:'group',index:this.scene.groups.length-1};}
   this.constrain(g);this.controls();this.draw();
  }catch{this.node('editStatus').textContent='날씨 아이콘을 불러오지 못했습니다.';}
 }
 drawPanels(){if(this.page!==1)return;const c=this.ctx;for(const p of this.scene.panels||[]){if(!p.updated)continue;const im=this.sprites.get(p.src);if(!im)continue;const top=p.id==='satellite'?202:659,y=p.id==='satellite'?151:622;c.fillStyle='white';c.fillRect(65,top,435,365);c.fillRect(310,y,190,36);const scale=Math.min(365/im.width,365/im.height,1),w=im.width*scale,h=im.height*scale;c.drawImage(im,282-w/2,top+(365-h)/2,w,h);c.fillStyle='#333333';c.font='21px system-ui, sans-serif';c.textAlign='right';c.textBaseline='middle';const time=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Seoul',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(p.time));c.fillText(time+' KST',497,y+18);}}
 draw(handles=this.editing){
  this.canvas.hidden=!this.editing&&!this.changed;el('page'+this.page).hidden=this.editing||this.changed;
  const c=this.ctx;c.clearRect(0,0,1920,1080);if(!this.background||!this.scene)return;c.drawImage(this.background,0,0,1920,1080);this.drawPanels();
  if(this.page===1)for(const b of this.scene.boundaries){const p=b.points;c.beginPath();c.moveTo(...p[0]);c.bezierCurveTo(...p[1],...p[2],...p[3]);c.strokeStyle=b.color;c.lineWidth=b.width;c.stroke();}
  c.save();if(this.page===2){const b=this.bounds();c.beginPath();c.rect(b.x,b.y,b.w,b.h);c.clip();}
  for(let i=0;i<this.scene.groups.length;i++){const g=this.scene.groups[i],im=this.sprites.get(g.src);if(im)c.drawImage(im,g.x,g.y,g.w,g.h);}c.restore();
  if(handles)this.drawSelection();
  if(handles&&this.page===1)for(const b of this.scene.boundaries){c.strokeStyle='#6d28d9';c.lineWidth=1;c.setLineDash([6,6]);c.beginPath();c.moveTo(...b.points[0]);for(const xy of b.points.slice(1))c.lineTo(...xy);c.stroke();c.setLineDash([]);for(const xy of b.points){c.beginPath();c.arc(...xy,8,0,2*Math.PI);c.fillStyle='white';c.fill();c.strokeStyle='#7c3aed';c.lineWidth=3;c.stroke();}}
 }
 async load(day,version,token){
  this.clear();this.day=day;
  try{
   const r=await fetch(`energy/${day}/editor${this.page===2?'2':''}.json?v=${version}`);if(!r.ok)throw Error('editor');const data=await r.json();
   if(!Array.isArray(data.groups)||!Array.isArray(data.boundaries)||!data.palette)throw Error('schema');
   data.palette={...data.palette,...editorSymbols};
   const bg=await image(`energy/${day}/${data.background}?v=${version}`);if(token!==loadToken)return;
   this.original=data;this.original.revision=data.revision||1;this.scene=clone(data);this.background=bg;
   try{const saved=JSON.parse(localStorage.getItem(this.storageKey()));if(saved&&Array.isArray(saved.groups)&&Array.isArray(saved.boundaries)&&saved.groups.every(g=>['x','y','w','h'].every(k=>Number.isFinite(g[k]))&&g.w>0&&g.h>0&&typeof g.src==='string')){this.scene=saved;this.scene.palette=clone(data.palette);this.changed=true;}}catch{}
   this.scene.panels=this.scene.panels||clone(data.panels||[]);if(this.page===2){this.scene.boundaries=[];this.scene.panels=[];this.scene.groups.forEach(g=>this.constrain(g));}
   await Promise.all([...this.scene.groups,...this.scene.panels.filter(p=>p.updated)].map(g=>this.sprite(g.src)));if(token!==loadToken)return;
   this.node('iconChoice').replaceChildren();for(const name of Object.keys(this.scene.palette)){const option=document.createElement('option');option.value=name;option.textContent=labels[name]||name;this.node('iconChoice').append(option);}
   this.node('edit').disabled=false;this.node('editStatus').textContent=this.page===2?'아이콘·화살표를 선택한 뒤 모서리의 보라색 네모를 끌어 크기를 조절하세요. 객체를 끌면 이동합니다. 날짜·기온 그래프·수치·범례는 고정입니다.':'아이콘·화살표를 선택한 뒤 모서리의 보라색 네모를 끌어 크기를 조절하세요. 객체를 끌면 이동하고, 경계선은 보라색 조절점으로 수정합니다.';this.controls();this.draw();
  }catch{if(token===loadToken){this.scene=null;this.node('editStatus').textContent='이 날짜의 편집 정보를 불러오지 못했습니다.';}}
 }
 async download(edited=false){
  const day=this.day||el('date').value;
  try{let output;if(edited&&this.scene){this.draw(false);output=document.createElement('canvas');output.width=1920;output.height=1080;output.getContext('2d').drawImage(this.canvas,0,0);}
   else{const src=el('page'+this.page).src;output=document.createElement('canvas');output.width=1920;output.height=1080;output.getContext('2d').drawImage(await image(src),0,0,1920,1080);}
   const blob=await new Promise(resolve=>output.toBlob(resolve,'image/png'));if(!blob)throw Error('PNG');const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`KPX_weather_${day}_0${this.page}${edited?'_edited':''}.png`;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
  }catch{el('status').textContent='PNG 저장에 실패했습니다. 이미지를 모두 불러온 뒤 다시 시도해 주세요.';}finally{this.draw();}
 }
}
const editors={1:new ReportEditor(1),2:new ReportEditor(2)};
function refreshControls(){const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul'}).format(new Date()).replaceAll('-','');el('refreshImages').hidden=!imageryEndpoint;el('refreshImages').disabled=refreshing||!editors[1].scene||el('date').value!==today;}
el('refreshImages').onclick=async()=>{
 const ed=editors[1];if(refreshing||!ed.scene||!imageryEndpoint||el('refreshImages').disabled)return;const token=loadToken;refreshing=true;refreshControls();el('status').textContent='기상청에서 최신 공개 위성·레이더 영상을 확인하고 있습니다…';
 try{
  const result=await Promise.allSettled(['satellite','radar'].map(async kind=>{const r=await fetch(imageryEndpoint+'/latest/'+kind,{credentials:'omit',signal:AbortSignal.timeout(90000)});if(!r.ok)throw Error('unavailable');const p=await r.json();if(p.id!==kind||typeof p.src!=='string'||p.src.length>5500000||!p.src.startsWith('data:image/png;base64,')||!Number.isFinite(Date.parse(p.time)))throw Error('invalid');const ms=Date.parse(p.time);if(ms>Date.now()+60000||ms<Date.now()-3600000)throw Error('stale');const full=await image(p.src);if(full.width<500||full.height<500||full.width>2000||full.height>2000)throw Error('dimensions');const thumb=document.createElement('canvas'),scale=Math.min(365/full.width,365/full.height,1);thumb.width=Math.round(full.width*scale);thumb.height=Math.round(full.height*scale);thumb.getContext('2d').drawImage(full,0,0,thumb.width,thumb.height);p.src=thumb.toDataURL('image/png');await ed.sprite(p.src);return {...p,updated:true};}));
  if(token!==loadToken)return;const good=result.filter(r=>r.status==='fulfilled').map(r=>r.value);if(!good.length)throw Error('unavailable');ed.remember();ed.scene.panels=ed.scene.panels||clone(ed.original.panels||[]);for(const p of good){const i=ed.scene.panels.findIndex(x=>x.id===p.id);if(i<0)ed.scene.panels.push(p);else ed.scene.panels[i]=p;}ed.draw();el('status').textContent=(good.length===2?'최신 위성·레이더 영상을 적용했습니다.':'불러온 영상만 갱신했습니다. 실패한 영상은 기존 상태로 유지됩니다.')+' 영상별 관측 시각을 확인해 주세요. 예보와 지도 편집 내용은 유지됩니다. 1페이지 PNG 저장으로 내려받을 수 있습니다.';
 }catch{if(token===loadToken)el('status').textContent='최신 영상을 가져오지 못했습니다. 기존 영상과 편집 내용은 유지됩니다. 잠시 후 다시 시도해 주세요.';}finally{refreshing=false;refreshControls();}
};
async function show(){
 const token=++loadToken,day=el('date').value;if(!/^\d{8}$/.test(day))return;for(const ed of Object.values(editors))ed.clear();refreshControls();
 const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul'}).format(new Date()).replaceAll('-','');el('status').textContent=`${format(day)} 자료입니다. `+(index.automatic_generation?'매일 오전 7시 기준 자동 생성 · ':'자동 생성 연결 중 · ')+(day!==today?'오늘 자료가 아니므로 날짜를 확인해 주세요.':'');
 const version=encodeURIComponent(index.updated_kst||'two-page-icons-1');for(const n of [1,2]){el('page'+n).src=`energy/${day}/0${n}.webp?v=${version}`;el('save'+n).hidden=false;}el('report').hidden=false;el('print').disabled=false;
 await Promise.all(Object.values(editors).map(ed=>ed.load(day,version,token)));if(token===loadToken)refreshControls();
}
el('date').addEventListener('change',show);el('print').onclick=()=>window.print();
window.addEventListener('beforeprint',()=>Object.values(editors).forEach(ed=>ed.draw(false)));window.addEventListener('afterprint',()=>Object.values(editors).forEach(ed=>ed.draw()));
(async()=>{try{const r=await fetch('energy/index.json',{cache:'no-store'});if(!r.ok)throw Error('index');index=await r.json();const dates=index.dates.filter(d=>/^\d{8}$/.test(d));if(!dates.length){el('status').textContent='최근 30일 이내 게시된 자료가 없습니다.';return;}for(const d of dates){const o=document.createElement('option');o.value=d;o.textContent=format(d);el('date').append(o);}el('date').disabled=false;await show();}catch{el('status').textContent='자료 목록을 불러오지 못했습니다. 잠시 후 새로고침해 주세요.';}})();
