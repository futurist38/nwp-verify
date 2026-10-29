'use strict';
const el=id=>document.getElementById(id);
const format=d=>`${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}`;
const clone=o=>JSON.parse(JSON.stringify(o));
let index,scene,original,background,selected=null,drag=null,history=[],editing=false,loadToken=0;
const imageryEndpoint=document.querySelector('meta[name=energy-imagery-endpoint]')?.content.trim().replace(/\/$/,'')||'';
let refreshing=false;
const spriteImages=new Map();const canvas=el('editorCanvas'),ctx=canvas.getContext('2d');
function image(src){return new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=reject;im.src=src;});}
async function sprite(src){if(!spriteImages.has(src))spriteImages.set(src,await image(src));return spriteImages.get(src);}
function remember(){history.push(clone(scene));if(history.length>40)history.shift();}
function draw(handles=editing){
 ctx.clearRect(0,0,1920,1080);if(!background||!scene)return;ctx.drawImage(background,0,0,1920,1080);drawPanels();
 for(const b of scene.boundaries){const p=b.points;ctx.beginPath();ctx.moveTo(...p[0]);ctx.bezierCurveTo(...p[1],...p[2],...p[3]);ctx.strokeStyle=b.color;ctx.lineWidth=b.width;ctx.stroke();}
 for(let i=0;i<scene.groups.length;i++){const g=scene.groups[i],im=spriteImages.get(g.src);if(im)ctx.drawImage(im,g.x,g.y,g.w,g.h);
  if(handles&&selected?.type==='group'&&selected.index===i){ctx.strokeStyle='#7c3aed';ctx.lineWidth=3;ctx.setLineDash([8,6]);ctx.strokeRect(g.x-5,g.y-5,g.w+10,g.h+10);ctx.setLineDash([]);}}
 if(handles){for(let b=0;b<scene.boundaries.length;b++){const p=scene.boundaries[b].points;ctx.strokeStyle='#6d28d9';ctx.lineWidth=1;ctx.setLineDash([6,6]);ctx.beginPath();ctx.moveTo(...p[0]);for(const xy of p.slice(1))ctx.lineTo(...xy);ctx.stroke();ctx.setLineDash([]);for(const xy of p){ctx.beginPath();ctx.arc(...xy,8,0,2*Math.PI);ctx.fillStyle='white';ctx.fill();ctx.strokeStyle='#7c3aed';ctx.lineWidth=3;ctx.stroke();}}}
}
function point(e){const r=canvas.getBoundingClientRect();return [(e.clientX-r.left)*1920/r.width,(e.clientY-r.top)*1080/r.height];}
function controls(){el('remove').disabled=!selected;el('size').disabled=selected?.type!=='group';el('size').value='100';}
canvas.addEventListener('pointerdown',e=>{
 if(!editing||!scene)return;const [x,y]=point(e);selected=null;
 for(let b=0;b<scene.boundaries.length;b++)for(let p=0;p<4;p++){const xy=scene.boundaries[b].points[p];if(Math.hypot(x-xy[0],y-xy[1])<20){selected={type:'boundary',index:b};drag={type:'point',b,p};}}
 if(!drag)for(let i=scene.groups.length-1;i>=0;i--){const g=scene.groups[i];if(x>=g.x&&x<=g.x+g.w&&y>=g.y&&y<=g.y+g.h){selected={type:'group',index:i};drag={type:'group',index:i,dx:x-g.x,dy:y-g.y};break;}}
 if(drag){remember();canvas.setPointerCapture(e.pointerId);}controls();draw();
});
canvas.addEventListener('pointermove',e=>{if(!drag)return;const [x,y]=point(e);if(drag.type==='point')scene.boundaries[drag.b].points[drag.p]=[Math.max(0,Math.min(1920,x)),Math.max(90,Math.min(1025,y))];else{const g=scene.groups[drag.index];g.x=Math.max(0,Math.min(1920-g.w,x-drag.dx));g.y=Math.max(90,Math.min(1025-g.h,y-drag.dy));}draw();});
function endDrag(){drag=null;}
canvas.addEventListener('pointerup',endDrag);canvas.addEventListener('pointercancel',endDrag);canvas.addEventListener('lostpointercapture',endDrag);
function drawPanels(){
 for(const p of scene.panels||[]){
  if(!p.updated)continue;const im=spriteImages.get(p.src);if(!im)continue;
  const top=p.id==='satellite'?202:659,y=p.id==='satellite'?151:622;
  ctx.fillStyle='white';ctx.fillRect(65,top,435,365);ctx.fillRect(310,y,190,36);
  const scale=Math.min(365/im.width,365/im.height,1),w=im.width*scale,h=im.height*scale;
  ctx.drawImage(im,282-w/2,top+(365-h)/2,w,h);
  ctx.fillStyle='#333333';ctx.font='21px system-ui, sans-serif';ctx.textAlign='right';ctx.textBaseline='middle';
  const time=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Seoul',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(p.time));
  ctx.fillText(time+' KST',497,y+18);
 }
}
function refreshControls(){const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul'}).format(new Date()).replaceAll('-','');el('refreshImages').hidden=!imageryEndpoint;el('refreshImages').disabled=refreshing||!scene||el('date').value!==today;}
el('refreshImages').onclick=async()=>{
 if(refreshing||!scene||!imageryEndpoint)return;
 const token=loadToken;refreshing=true;refreshControls();el('status').textContent='기상청에서 최신 공개 위성·레이더 영상을 확인하고 있습니다…';
 try{
  const result=await Promise.allSettled(['satellite','radar'].map(async kind=>{
   const r=await fetch(imageryEndpoint+'/latest/'+kind,{credentials:'omit',signal:AbortSignal.timeout(90000)});
   if(!r.ok)throw Error('unavailable');const p=await r.json();
   if(p.id!==kind||typeof p.src!=='string'||p.src.length>5500000||!p.src.startsWith('data:image/png;base64,')||!Number.isFinite(Date.parse(p.time)))throw Error('invalid');
   const ms=Date.parse(p.time);if(ms>Date.now()+60000||ms<Date.now()-3600000)throw Error('stale');
   // Keep browser storage compact while retaining the entire image and legend.
   const full=await image(p.src),thumb=document.createElement('canvas'),scale=Math.min(365/full.width,365/full.height,1);
   thumb.width=Math.round(full.width*scale);thumb.height=Math.round(full.height*scale);thumb.getContext('2d').drawImage(full,0,0,thumb.width,thumb.height);
   p.src=thumb.toDataURL('image/png');await sprite(p.src);return {...p,updated:true};
  }));
  if(token!==loadToken)return;
  const good=result.filter(r=>r.status==='fulfilled').map(r=>r.value);
  if(!good.length)throw Error('unavailable');remember();scene.panels=scene.panels||clone(original.panels||[]);
  for(const p of good){const i=scene.panels.findIndex(x=>x.id===p.id);if(i<0)scene.panels.push(p);else scene.panels[i]=p;}
  if(!editing)el('edit').click();draw();
  el('status').textContent=(good.length===2?'최신 위성·레이더 영상을 적용했습니다.':'불러온 영상만 갱신했습니다. 실패한 영상은 기존 상태로 유지됩니다.')+' 영상별 관측 시각을 확인해 주세요. 예보와 지도 편집 내용은 유지됩니다. 편집본 PNG 저장으로 내려받을 수 있습니다.';
 }catch{if(token===loadToken)el('status').textContent='최신 영상을 가져오지 못했습니다. 기존 영상과 편집 내용은 유지됩니다. 잠시 후 다시 시도해 주세요.';}
 finally{refreshing=false;refreshControls();}
};
el('edit').onclick=()=>{editing=!editing;el('editorControls').hidden=!editing;canvas.hidden=!editing;el('page1').hidden=editing;el('edit').textContent=editing?'편집 닫기':'1페이지 편집';draw();};
el('undo').onclick=()=>{if(history.length){scene=history.pop();selected=null;controls();draw();}};
el('reset').onclick=()=>{remember();scene=clone(original);selected=null;controls();draw();};
el('remove').onclick=()=>{if(!selected)return;remember();scene[selected.type==='group'?'groups':'boundaries'].splice(selected.index,1);selected=null;controls();draw();};
el('size').onchange=e=>{if(selected?.type!=='group')return;remember();const g=scene.groups[selected.index],scale=Number(e.target.value)/100;const w=Math.min(800,g.w*scale),h=w*g.h/g.w;g.x-=(w-g.w)/2;g.y-=(h-g.h)/2;g.w=w;g.h=h;controls();draw();};
el('addIcon').onclick=async()=>{if(!scene)return;remember();const src=scene.palette[el('iconChoice').value];const im=await sprite(src);const s=130/Math.max(im.width,im.height);scene.groups.push({id:'added-'+Date.now(),x:800,y:450,w:im.width*s,h:im.height*s,src});selected={type:'group',index:scene.groups.length-1};controls();draw();};
el('addBoundary').onclick=()=>{remember();scene.boundaries.push({points:[[650,620],[790,620],[990,550],[1100,470]],color:'#3c6090',width:5});selected={type:'boundary',index:scene.boundaries.length-1};controls();draw();};
function storageKey(){return 'kpx-energy-editor-v1-'+el('date').value+'-'+original?.revision;}
el('saveLayout').onclick=()=>{try{localStorage.setItem(storageKey(),JSON.stringify(scene));el('editStatus').textContent='이 브라우저에 날짜별 편집 상태를 저장했습니다. 공유하려면 PNG를 저장해 주세요.';}catch(e){el('editStatus').textContent='브라우저 저장 공간이 부족합니다. PNG로 저장해 주세요.';}};
async function downloadPng(n,edited=false){
 try{let output;
 if(edited){draw(false);output=canvas;}
 else{output=document.createElement('canvas');output.width=1920;output.height=1080;output.getContext('2d').drawImage(await image(el('page'+n).src),0,0,1920,1080);}
 const blob=await new Promise(resolve=>output.toBlob(resolve,'image/png'));if(!blob)throw Error('PNG');
 const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`KPX_weather_${el('date').value}_0${n}${edited?'_edited':''}.png`;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
 }catch(e){el('status').textContent='PNG 저장에 실패했습니다. 이미지를 모두 불러온 뒤 다시 시도해 주세요.';}finally{draw();}
}
el('save1').onclick=e=>{e.preventDefault();downloadPng(1);};el('save2').onclick=e=>{e.preventDefault();downloadPng(2);};el('exportEdit').onclick=()=>downloadPng(1,true);
const labels={clear:'맑음',sun_cloud_a:'구름조금',sun_cloud_b:'구름많음',cloudy:'흐림',rain:'비',shower:'소나기',snow:'눈',snow_rain_a:'눈·비',thunderstorm:'뇌우',fog:'안개',haze:'연무',dust:'황사'};
async function show(){
 const token=++loadToken,day=el('date').value;if(!/^\d{8}$/.test(day))return;
 editing=false;scene=null;background=null;history=[];selected=null;drag=null;el('editorControls').hidden=true;canvas.hidden=true;el('page1').hidden=false;el('edit').disabled=true;refreshControls();el('edit').textContent='1페이지 편집';
 const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul'}).format(new Date()).replaceAll('-','');
 el('status').textContent=`${format(day)} 자료입니다. `+(index.automatic_generation?'매일 오전 7시 기준 자동 생성 · ':'자동 생성 연결 중 · ')+(day!==today?'오늘 자료가 아니므로 날짜를 확인해 주세요.':'');
 const version=encodeURIComponent(index.updated_kst||'editor-v1');
 for(const n of [1,2]){el('page'+n).src=`energy/${day}/0${n}.webp?v=${version}`;el('save'+n).hidden=false;}
 el('report').hidden=false;el('print').disabled=false;
 try{
  const r=await fetch(`energy/${day}/editor.json?v=${version}`);if(!r.ok)throw Error('editor');const data=await r.json();
  const bg=await image(`energy/${day}/${data.background}?v=${version}`);if(token!==loadToken)return;
  original=data;original.revision=data.revision||1;scene=clone(original);background=bg;
  try{const saved=JSON.parse(localStorage.getItem(storageKey()));if(saved&&Array.isArray(saved.groups)&&Array.isArray(saved.boundaries))scene=saved;}catch(e){}
  scene.panels=scene.panels||clone(original.panels||[]);
  await Promise.all([...scene.groups,...scene.panels.filter(p=>p.updated)].map(g=>sprite(g.src)));if(token!==loadToken)return;
  el('iconChoice').replaceChildren();for(const name of Object.keys(scene.palette)){const option=document.createElement('option');option.value=name;option.textContent=labels[name]||name;el('iconChoice').append(option);}
  el('edit').disabled=false;refreshControls();el('editStatus').textContent='아이콘을 끌어 이동하고, 경계선의 보라색 조절점을 움직이세요. 편집 내용은 자동 생성 원본에 영향을 주지 않습니다.';controls();draw();
 }catch(e){if(token===loadToken)el('editStatus').textContent='이 날짜의 편집 정보를 불러오지 못했습니다.';}
}
el('date').addEventListener('change',show);el('print').onclick=()=>window.print();
window.addEventListener('beforeprint',()=>draw(false));window.addEventListener('afterprint',()=>draw());
(async()=>{try{const r=await fetch('energy/index.json',{cache:'no-store'});if(!r.ok)throw Error('index');index=await r.json();const dates=index.dates.filter(d=>/^\d{8}$/.test(d));if(!dates.length){el('status').textContent='최근 30일 이내 게시된 자료가 없습니다.';return;}for(const d of dates){const o=document.createElement('option');o.value=d;o.textContent=format(d);el('date').append(o);}el('date').disabled=false;await show();}catch(e){el('status').textContent='자료 목록을 불러오지 못했습니다. 잠시 후 새로고침해 주세요.';}})();

