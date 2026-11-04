'use strict';
const reportFetch=(url,opts)=>window.ENERGY_PREVIEW?.data?.[url.split('?')[0]]?Promise.resolve({ok:true,json:async()=>clone(window.ENERGY_PREVIEW.data[url.split('?')[0]])}):fetch(url,opts);
const el=id=>document.getElementById(id);
const format=d=>`${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}`;
const clone=o=>JSON.parse(JSON.stringify(o));
const labels={clear:'맑음',sun_cloud_a:'구름조금',sun_cloud_b:'구름많음',cloudy:'흐림',rain:'비',shower:'소나기',snow:'눈',snow_rain_a:'눈·비',thunderstorm:'뇌우',fog:'안개',haze:'연무',dust:'황사',arrow_right:'화살표 →',parentheses:'괄호 (  )'};
// Editor-only symbols are available for both archived and newly generated reports.
const editorSymbols={arrow_right:'data:image/svg+xml;charset=utf-8,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="76" height="50" viewBox="0 0 76 50"><path d="M2 13 H46 V2 L74 25 L46 48 V37 H2 Z" fill="#ffd1c9" stroke="#c74848" stroke-width="3" stroke-linejoin="round"/></svg>')};
editorSymbols.parentheses='data:image/svg+xml;charset=utf-8,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="150" height="100" viewBox="0 0 150 100"><path d="M20 4 C2 26 2 74 20 96 M130 4 C148 26 148 74 130 96" fill="none" stroke="#000" stroke-width="4" stroke-linecap="round"/></svg>');
const imageryEndpoint=document.querySelector('meta[name=energy-imagery-endpoint]')?.content.trim().replace(/\/$/,'')||'';
let index,loadToken=0,refreshing=false;
function image(src){return new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=reject;im.src=window.ENERGY_PREVIEW?.images?.[src.split('?')[0]]||src;});}
// Keep the opposite corner fixed, preserving aspect ratio and page edit bounds.
function resizedGroupRect(start,corner,x,y,bounds,maxWidth=800){
 const east=corner.includes('e'),south=corner.includes('s');
 const ax=east?start.x:start.x+start.w,ay=south?start.y:start.y+start.h;
 const dx=(x-ax)*(east?1:-1),dy=(y-ay)*(south?1:-1);
 const availableW=east?bounds.x+bounds.w-ax:ax-bounds.x;
 const availableH=south?bounds.y+bounds.h-ay:ay-bounds.y;
 const maxScale=Math.max(0,Math.min(maxWidth/start.w,availableW/start.w,availableH/start.h));
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
  this.setupReportFields();
  this.node('undo').onclick=()=>{if(this.history.length){this.scene=this.history.pop();this.selected=null;this.changed=true;this.controls();this.draw();}};
  this.node('reset').onclick=()=>{if(!this.scene)return;this.remember();this.scene=clone(this.original);this.selected=null;this.controls();this.draw();};
  this.node('remove').onclick=()=>{if(!this.selected)return;this.remember();this.objects(this.selected.type).splice(this.selected.index,1);this.selected=null;this.controls();this.draw();};
  this.node('size').onchange=e=>this.resize(Number(e.target.value)/100);
  this.node('addText').onclick=()=>this.editText(false);
  this.node('updateText').onclick=()=>this.editText(true);
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
 title(){return `${this.page}페이지 편집`;}
 clear(){this.finishInline?.(true);this.scene=null;this.original=null;this.background=null;this.selected=null;this.drag=null;this.history=[];this.editing=false;this.changed=false;this.day='';this.sprites.clear();this.node('editorControls').hidden=true;this.canvas.hidden=true;el('page'+this.page).hidden=false;this.node('edit').disabled=true;this.node('edit').textContent=this.title();this.node('textInput').value='';}
 storageKey(){return `kpx-energy-editor-v1-${this.day}-${this.original?.revision}`+(this.page===2?'-page2':'');}
 remember(){this.changed=true;this.history.push(clone(this.scene));if(this.history.length>40)this.history.shift();}
 async sprite(src){if(!this.sprites.has(src))this.sprites.set(src,await image(src));return this.sprites.get(src);}
 bounds(type='group'){if(type==='text')return {x:8,y:8,w:1904,h:1064};return this.page===2?{x:188,y:234,w:1648,h:210}:{x:0,y:90,w:1920,h:935};}
 constrain(g,type='group'){const b=this.bounds(type);const scale=Math.min(1,b.w/g.w,b.h/g.h);g.w*=scale;g.h*=scale;g.x=Math.max(b.x,Math.min(b.x+b.w-g.w,g.x));g.y=Math.max(b.y,Math.min(b.y+b.h-g.h,g.y));}
 objects(type){return this.scene?.[type==='text'?'texts':type==='group'?'groups':'boundaries']||[];}
 selectedObject(){return ['group','text'].includes(this.selected?.type)?this.objects(this.selected.type)[this.selected.index]:null;}
 controls(){
  this.syncReportFields();
  const g=this.selectedObject();this.node('remove').disabled=!this.selected;this.node('size').disabled=!g;
  this.node('replaceIcon').disabled=this.selected?.type!=='group';this.node('updateText').disabled=this.selected?.type!=='text';
  if(this.selected?.type==='text'&&g)this.node('textInput').value=g.text;
  this.node('size').value='100';this.node('undo').disabled=!this.history.length;
 }
 textMetrics(text){
  const c=this.ctx,lines=text.split('\n');c.save();c.font= '700 32px "Malgun Gothic", "맑은 고딕", sans-serif' ;
  const w=Math.max(48,...lines.map(line=>c.measureText(line).width))+32;c.restore();
  return {lines,w,h:lines.length*44+24};
 }
 editText(replace){
  if(!this.scene||(replace&&this.selected?.type!=='text'))return;
  const input=this.node('textInput'),text=input.value.replace(/\r\n?/g,'\n').slice(0,200).trim();
  if(!text){this.node('editStatus').textContent='주석 문구를 입력한 뒤 글상자를 삽입해 주세요.';input.focus();return;}
  const prev=replace?this.selectedObject():null;if(prev?.text===text)return;
  const m=this.textMetrics(text),scale=prev?prev.w/this.textMetrics(prev.text).w:1;
  this.remember();this.scene.texts=this.scene.texts||[];
  const g={id:prev?.id||'text-'+Date.now(),text,x:prev?.x??800,y:prev?.y??(this.page===2?300:450),w:m.w*scale,h:m.h*scale};
  this.constrain(g,'text');
  if(replace)this.scene.texts[this.selected.index]=g;
  else{this.scene.texts.push(g);this.selected={type:'text',index:this.scene.texts.length-1};}
  this.controls();this.draw();this.node('editStatus').textContent='글상자를 끌어 원하는 곳에 놓으세요. 모서리로 크기를 조절하고, 문구를 바꾼 뒤 선택 글상자 수정을 누르세요.';
 }
 drawText(g){
  const c=this.ctx,m=this.textMetrics(g.text);c.save();c.translate(g.x,g.y);c.scale(g.w/m.w,g.h/m.h);
  c.fillStyle='#ffffff';c.fillRect(0,0,m.w,m.h);c.strokeStyle='#000000';c.lineWidth=3;c.setLineDash([]);c.strokeRect(1.5,1.5,m.w-3,m.h-3);
  c.fillStyle='#0653b8';c.font= '700 32px "Malgun Gothic", "맑은 고딕", sans-serif' ;c.textAlign='center';c.textBaseline='middle';
  m.lines.forEach((line,i)=>c.fillText(line,m.w/2,12+44*(i+.5)));c.restore();
 }
 selectionHandles(){
  const g=this.selectedObject();if(!g)return [];
  return [['nw',g.x,g.y],['ne',g.x+g.w,g.y],['se',g.x+g.w,g.y+g.h],['sw',g.x,g.y+g.h]];
 }
 handleAt(x,y,pointerType='mouse'){
  const radius=(pointerType==='touch'?18:10)*1920/this.canvas.getBoundingClientRect().width;
  return this.selectionHandles().map(([corner,hx,hy])=>({corner,distance:Math.hypot(x-hx,y-hy)})).filter(h=>h.distance<=radius).sort((a,b)=>a.distance-b.distance)[0]?.corner;
 }
 drawSelection(){
  const g=this.selectedObject();if(!g)return;
  const c=this.ctx,unit=1920/this.canvas.getBoundingClientRect().width;
  c.save();c.strokeStyle='#7c3aed';c.fillStyle='white';c.lineWidth=2*unit;c.setLineDash([6*unit,4*unit]);c.strokeRect(g.x,g.y,g.w,g.h);c.setLineDash([]);
  for(const [,x,y] of this.selectionHandles()){c.fillRect(x-5*unit,y-5*unit,10*unit,10*unit);c.strokeRect(x-5*unit,y-5*unit,10*unit,10*unit);}
  c.restore();
 }
 point(e){const r=this.canvas.getBoundingClientRect();return [(e.clientX-r.left)*1920/r.width,(e.clientY-r.top)*1080/r.height];}
 pointerDown(e){
  if(!this.editing||!this.scene)return;
  const [x,y]=this.point(e),corner=this.handleAt(x,y,e.pointerType);this.drag=null;
  if(corner){
   const index=this.selected.index;this.drag={type:'resize',objectType:this.selected.type,index,corner,start:clone(this.selectedObject())};
  }else{
   this.selected=null;
   for(let i=(this.scene.texts||[]).length-1;i>=0;i--){const g=this.scene.texts[i];if(x>=g.x&&x<=g.x+g.w&&y>=g.y&&y<=g.y+g.h){this.selected={type:'text',index:i};this.drag={type:'text',index:i,dx:x-g.x,dy:y-g.y};break;}}
   if(!this.drag&&this.page===1)for(let b=0;b<this.scene.boundaries.length;b++)for(let p=0;p<4;p++){const xy=this.scene.boundaries[b].points[p];if(Math.hypot(x-xy[0],y-xy[1])<20){this.selected={type:'boundary',index:b};this.drag={type:'point',b,p};}}
   if(!this.drag)for(let i=this.scene.groups.length-1;i>=0;i--){const g=this.scene.groups[i];if(x>=g.x&&x<=g.x+g.w&&y>=g.y&&y<=g.y+g.h){this.selected={type:'group',index:i};this.drag={type:'group',index:i,dx:x-g.x,dy:y-g.y};break;}}
  }
  if(this.drag){e.preventDefault();this.remember();this.canvas.setPointerCapture(e.pointerId);this.canvas.style.cursor=this.drag.type==='resize'?(['nw','se'].includes(corner)?'nwse-resize':'nesw-resize'):'grabbing';}
  this.controls();this.draw();
 }
 pointerMove(e){
  if(!this.editing||!this.scene)return;const [x,y]=this.point(e);
  if(!this.drag){const corner=this.handleAt(x,y,e.pointerType);this.canvas.style.cursor=corner?(['nw','se'].includes(corner)?'nwse-resize':'nesw-resize'):'grab';return;}
  if(this.drag.type==='resize')Object.assign(this.objects(this.drag.objectType)[this.drag.index],resizedGroupRect(this.drag.start,this.drag.corner,x,y,this.bounds(this.drag.objectType),this.drag.objectType==='text'?1904:800));
  else if(this.drag.type==='point'&&this.page===1)this.scene.boundaries[this.drag.b].points[this.drag.p]=[Math.max(0,Math.min(1920,x)),Math.max(90,Math.min(1025,y))];
  else if(['group','text'].includes(this.drag.type)){const g=this.objects(this.drag.type)[this.drag.index];g.x=x-this.drag.dx;g.y=y-this.drag.dy;this.constrain(g,this.drag.type);}
  this.draw();
 }
 resize(scale){const g=this.selectedObject();if(!g||!Number.isFinite(scale)||scale<=0)return;this.remember();const w=Math.min(this.selected.type==='text'?1904:800,g.w*scale),h=w*g.h/g.w;g.x-=(w-g.w)/2;g.y-=(h-g.h)/2;g.w=w;g.h=h;this.constrain(g,this.selected.type);this.controls();this.draw();}
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
 setupReportFields(){
  const box=document.createElement('div');box.className='text-tools';
  const field=(id,label,placeholder,max=60)=>{const wrap=document.createElement('label');wrap.textContent=label+' ';const input=document.createElement('input');input.id=id+(this.page===2?'2':'');input.type='text';input.maxLength=max;input.placeholder=placeholder;input.style.cssText='font:inherit;padding:8px;border:1px solid #9aa8b8;border-radius:6px;width:260px';wrap.append(input);box.append(wrap);return input;};
  field('publicationText','우측 상단 기준시각','자동 표시 유지 (예: 2026.11.02.(월) 09시 기준)');
  if(this.page===1){
   field('satelliteTime','위성 시각','자동 표시 유지 (예: 06:30 KST)',30);
   field('radarTime','레이더·대체 이미지 시각','자동 표시 유지 (예: 09:00 KST)',30);
   field('radarTitle','레이더 영역 제목','자동 표시 유지 (예: 황사 현황)',30);
   for(const [kind,name] of [['satellite','위성'],['radar','레이더']]){
   const label=document.createElement('label');label.textContent=name+' 영역 이미지 선택 ';const input=document.createElement('input');input.type='file';input.accept='image/png,image/jpeg,image/webp,image/gif';input.id=kind+'Upload';input.onchange=()=>this.uploadPanel(kind,input);label.append(input);box.append(label);
   const restore=document.createElement('button');restore.textContent='기존 '+name+' 복원';restore.onclick=()=>{if(!this.scene)return;this.remember();this.scene.panels=this.scene.panels.filter(p=>p.id!==kind);const original=this.original.panels?.find(p=>p.id===kind);if(original)this.scene.panels.push(clone(original));this.controls();this.draw();};box.append(restore);
   }
  }
  const apply=document.createElement('button');apply.textContent='시각·제목 적용';apply.onclick=()=>{
   if(!this.scene)return;this.remember();this.scene.publicationText=this.node('publicationText').value.trim();
   if(this.page===1)for(const id of ['satellite','radar']){let panel=this.scene.panels.find(p=>p.id===id);if(!panel){panel={id};this.scene.panels.push(panel);}panel.timeText=this.node(id+'Time').value.trim();if(id==='radar')panel.titleText=this.node('radarTitle').value.trim();}
   this.controls();this.draw();this.node('editStatus').textContent='입력한 표시 문구를 적용했습니다. 실제 예보·관측자료의 시각은 변경되지 않습니다.';
  };box.append(apply);
  const hint=document.createElement('span');hint.textContent='빈 입력칸은 자동 표시를 유지합니다. 기준시각은 페이지별로 적용됩니다.';box.append(hint);this.node('reportFields').append(box);
 }
 syncReportFields(){
  if(!this.scene)return;this.node('publicationText').value=this.scene.publicationText||this.scene.labels?.find(t=>t.text.startsWith('발표시점:'))?.text||'';
  if(this.page===1){for(const id of ['satellite','radar']){const p=this.scene.panels?.find(p=>p.id===id);this.node(id+'Time').value=p?.timeText||'';}this.node('radarTitle').value=this.scene.panels?.find(p=>p.id==='radar')?.titleText||'';}
 }
 async uploadPanel(kind,input){
  if(!['satellite','radar'].includes(kind))return;
  const file=input.files?.[0];input.value='';if(!file||!this.scene)return;
  const active=this.scene,token=loadToken;let url;
  try{
   if(file.size>20*1024*1024||!/^image\/(png|jpeg|webp|gif)$/.test(file.type))throw Error('format');
   url=URL.createObjectURL(file);const full=await image(url);if(full.width*full.height>40000000)throw Error('size');
   const thumb=document.createElement('canvas'),scale=Math.min(1,870/full.width,730/full.height);thumb.width=Math.max(1,Math.round(full.width*scale));thumb.height=Math.max(1,Math.round(full.height*scale));thumb.getContext('2d').drawImage(full,0,0,thumb.width,thumb.height);
   const src=thumb.toDataURL('image/png');await this.sprite(src);if(token!==loadToken||active!==this.scene)return;
   this.remember();let panel=this.scene.panels.find(p=>p.id===kind);if(!panel){panel={id:kind};this.scene.panels.push(panel);}Object.assign(panel,{src,updated:true,custom:true,timeText:this.node(kind+'Time').value.trim()});if(kind==='radar')panel.titleText=this.node('radarTitle').value.trim();
   this.controls();this.draw();this.node('editStatus').textContent=`선택한 이미지를 ${kind==='satellite'?'위성':'레이더'} 영역에 적용했습니다. 시각을 확인하고 시각·제목 적용을 눌러 주세요. 이미지 비율은 유지됩니다.`;
  }catch{if(token===loadToken)this.node('editStatus').textContent='이미지를 읽지 못했습니다. 20MB 이하 PNG·JPG·WebP·GIF 파일을 선택해 주세요.';}finally{if(url)URL.revokeObjectURL(url);}
 }
 drawPanels(){
  const c=this.ctx;c.save();this.drawLabels();
  if(this.scene.publicationText&&!this.scene.labels){c.fillStyle='#ffc400';c.fillRect(1290,15,620,65);c.fillStyle='black';c.font='700 24px \"Malgun Gothic\", \"맑은 고딕\", sans-serif';c.textAlign='right';c.textBaseline='middle';c.fillText(this.scene.publicationText,1880,49,585);}
  if(this.page===1)for(const p of this.scene.panels||[]){
   const top=p.id==='satellite'?202:659,y=p.id==='satellite'?151:622;
   if(p.updated){const im=this.sprites.get(p.src);if(im){c.fillStyle='white';c.fillRect(65,top,435,365);const scale=Math.min((p.custom?435:365)/im.width,365/im.height),w=im.width*scale,h=im.height*scale;c.drawImage(im,282-w/2,top+(365-h)/2,w,h);}}
   if(p.updated||p.timeText){c.fillStyle='white';c.fillRect(310,y,190,36);c.fillStyle='#333333';c.font='21px \"Malgun Gothic\", \"맑은 고딕\", sans-serif';c.textAlign='right';c.textBaseline='middle';const time=p.timeText||(Number.isFinite(Date.parse(p.time))?new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Seoul',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(p.time))+' KST':'');c.fillText(time,497,y+18,184);}
   if(p.titleText){c.fillStyle='#fff300';c.fillRect(67,y,240,35);c.strokeStyle='black';c.lineWidth=1;c.strokeRect(67,y,240,35);c.fillStyle='black';c.font='700 24px \"Malgun Gothic\", \"맑은 고딕\", sans-serif';c.textAlign='center';c.textBaseline='middle';c.fillText(p.titleText,187,y+18,228);}
  }c.restore();
 }

 draw(handles=this.editing){
  this.canvas.hidden=!this.editing&&!this.changed;el('page'+this.page).hidden=this.editing||this.changed;
  const c=this.ctx;c.clearRect(0,0,1920,1080);if(!this.background||!this.scene)return;c.drawImage(this.background,0,0,1920,1080);this.drawPanels();
  if(this.page===1)for(const b of this.scene.boundaries){const p=b.points;c.beginPath();c.moveTo(...p[0]);c.bezierCurveTo(...p[1],...p[2],...p[3]);c.strokeStyle=b.color;c.lineWidth=b.width;c.stroke();}
  c.save();if(this.page===2){const b=this.bounds();c.beginPath();c.rect(b.x,b.y,b.w,b.h);c.clip();}
  for(let i=0;i<this.scene.groups.length;i++){const g=this.scene.groups[i],im=this.sprites.get(g.src);if(im)c.drawImage(im,g.x,g.y,g.w,g.h);}c.restore();
  for(const g of this.scene.texts||[])this.drawText(g);
  if(handles)this.drawSelection();
  if(handles&&this.page===1)for(const [bi,b] of this.scene.boundaries.entries())if(this.selection().some(s=>s.type==='boundary'&&s.index===bi)){c.strokeStyle='#6d28d9';c.lineWidth=1;c.setLineDash([6,6]);c.beginPath();c.moveTo(...b.points[0]);for(const xy of b.points.slice(1))c.lineTo(...xy);c.stroke();c.setLineDash([]);for(const xy of b.points){c.beginPath();c.arc(...xy,8,0,2*Math.PI);c.fillStyle='white';c.fill();c.strokeStyle='#7c3aed';c.lineWidth=3;c.stroke();}}
 }
 async load(day,version,token){
  this.clear();this.day=day;
  try{
   const r=await reportFetch(`energy/${day}/editor${this.page===2?'2':''}.json?v=${version}`);if(!r.ok)throw Error('editor');const data=await r.json();
   if(!Array.isArray(data.groups)||!Array.isArray(data.boundaries)||!data.palette)throw Error('schema');
   data.palette={...data.palette,...editorSymbols};data.texts=[];
   const bg=await image(`energy/${day}/${data.background}?v=${version}`);if(token!==loadToken)return;
   this.original=data;this.original.revision=data.revision||1;this.scene=clone(data);this.background=bg;
   try{const saved=JSON.parse(localStorage.getItem(this.storageKey()));if(saved&&Array.isArray(saved.groups)&&Array.isArray(saved.boundaries)&&saved.groups.every(g=>['x','y','w','h'].every(k=>Number.isFinite(g[k]))&&g.w>0&&g.h>0&&typeof g.src==='string')){this.scene=saved;this.scene.palette=clone(data.palette);this.scene.labels=data.labels?clone(data.labels):undefined;this.changed=true;}}catch{}
   this.scene.texts=(Array.isArray(this.scene.texts)?this.scene.texts:[]).filter(g=>g&&typeof g.text==='string'&&g.text.trim()&&g.text.length<=200&&['x','y','w','h'].every(k=>Number.isFinite(g[k]))&&g.w>0&&g.h>0);this.scene.texts.forEach(g=>this.constrain(g,'text'));
   this.scene.panels=this.scene.panels||clone(data.panels||[]);if(this.page===2){this.scene.boundaries=[];this.scene.panels=[];this.scene.groups.forEach(g=>this.constrain(g));}
   await Promise.all([...this.scene.groups,...this.scene.panels.filter(p=>p.updated)].map(g=>this.sprite(g.src)));if(token!==loadToken)return;
   this.node('iconChoice').replaceChildren();for(const name of Object.keys(this.scene.palette)){const option=document.createElement('option');option.value=name;option.textContent=labels[name]||name;this.node('iconChoice').append(option);}
   this.node('edit').disabled=false;this.node('editStatus').textContent=this.page===2?'아이콘·화살표·글상자를 선택한 뒤 모서리의 보라색 네모를 끌어 크기를 조절하세요. 객체를 끌면 이동합니다. 주석 문구를 입력하고 글상자 삽입을 누르면 페이지 어디에나 주석을 놓을 수 있습니다.':'아이콘·화살표·글상자를 선택한 뒤 모서리의 보라색 네모를 끌어 크기를 조절하세요. 객체를 끌면 이동하고, 경계선은 보라색 조절점으로 수정합니다. 주석은 문구를 입력하고 글상자 삽입을 누르세요.';this.controls();this.draw();
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
// Selection and clipboard are local to the report editor; text inputs retain native shortcuts.
let activeEditor=null,objectClipboard=[],clipboardPage=null;
const reportFont='"Malgun Gothic", "맑은 고딕", sans-serif';
const selectionKey=s=>s.type+':'+s.index;
Object.assign(labels,{mist:'박무',sun_rain:'해·비',sun_snow:'해·눈',sun_snow_rain_a:'해·눈비 ①',sun_snow_rain_b:'해·눈비 ②',snow_rain_b:'눈·비 ②'});
const originalControls=ReportEditor.prototype.controls,originalDraw=ReportEditor.prototype.draw;
const originalLoad=ReportEditor.prototype.load,originalChoose=ReportEditor.prototype.chooseIcon,originalEditText=ReportEditor.prototype.editText;
Object.assign(ReportEditor.prototype,{
 selection(){
  // Existing add/undo actions set `selected`; reconcile without stale object indexes.
  if(!this.selected)this.selections=[];
  else if(!(this.selections||[]).some(s=>selectionKey(s)===selectionKey(this.selected)))this.selections=[this.selected];
  return (this.selections||[]).filter(s=>this.objects(s.type)[s.index]);
 },
 setSelection(list){this.selections=list;this.selected=list.at(-1)||null;},
 objectRect(s){const g=this.objects(s.type)[s.index];if(s.type==='boundary'){const xs=g.points.map(p=>p[0]),ys=g.points.map(p=>p[1]);return {x:Math.min(...xs),y:Math.min(...ys),w:Math.max(1,Math.max(...xs)-Math.min(...xs)),h:Math.max(1,Math.max(...ys)-Math.min(...ys))};}return {x:g.x,y:g.y,w:g.w,h:g.h};},
 selectionRect(){const all=this.selection().map(s=>this.objectRect(s));if(!all.length)return null;const x=Math.min(...all.map(g=>g.x)),y=Math.min(...all.map(g=>g.y));return {x,y,w:Math.max(...all.map(g=>g.x+g.w))-x,h:Math.max(...all.map(g=>g.y+g.h))-y};},
 controls(){
  originalControls.call(this);const list=this.selection();const count=list.length;
  if(!this.node('selectionLabel'))return;
  this.node('selectionLabel').textContent=count?`${count}개 선택됨`:'객체를 선택하세요';
  this.node('size').disabled=!count;this.node('remove').disabled=!count;
  this.node('copyObjects').disabled=!count;this.node('pasteObjects').disabled=!objectClipboard.length;
  const isText=count===1&&list[0].type==='text';this.node('updateText').disabled=!isText;
  if(isText)this.node('textTools').hidden=false;
  else if(count)this.node('textTools').hidden=true;
 },
 selectionHandles(){const g=this.selectionRect();return g?[['nw',g.x,g.y],['ne',g.x+g.w,g.y],['se',g.x+g.w,g.y+g.h],['sw',g.x,g.y+g.h]]:[];},
 drawSelection(){
  const g=this.selectionRect();if(!g)return;const c=this.ctx,unit=1920/Math.max(1,this.canvas.getBoundingClientRect().width);
  c.save();c.strokeStyle='#2769b0';c.fillStyle='#fff';c.lineWidth=1.5*unit;c.setLineDash([5*unit,3*unit]);
  for(const s of this.selection()){const b=this.objectRect(s);c.strokeRect(b.x,b.y,b.w,b.h);}
  c.setLineDash([]);c.strokeRect(g.x,g.y,g.w,g.h);for(const [,x,y] of this.selectionHandles()){c.fillRect(x-4*unit,y-4*unit,8*unit,8*unit);c.strokeRect(x-4*unit,y-4*unit,8*unit,8*unit);}c.restore();
 },
 hit(x,y){
  for(const type of ['text','group'])for(let i=this.objects(type).length-1;i>=0;i--){const g=this.objects(type)[i];if(x>=g.x&&x<=g.x+g.w&&y>=g.y&&y<=g.y+g.h)return {type,index:i};}
  // Sample the visible Bezier curve, not its empty bounding box.
  for(let i=this.objects('boundary').length-1;i>=0;i--){const p=this.objects('boundary')[i].points;for(let t=0;t<=1;t+=.02){const q=[0,1].map(k=>(1-t)**3*p[0][k]+3*(1-t)**2*t*p[1][k]+3*(1-t)*t*t*p[2][k]+t**3*p[3][k]);if(Math.hypot(x-q[0],y-q[1])<14)return {type:'boundary',index:i};}}
  return null;
 },
 snapshotSelection(){return this.selection().map(s=>({...s,original:clone(this.objects(s.type)[s.index])}));},
 moveSnapshot(items,dx,dy){
  let minX=-Infinity,maxX=Infinity,minY=-Infinity,maxY=Infinity;
  for(const s of items){const b=this.bounds(s.type),g=s.original,r=s.type==='boundary'?{x:Math.min(...g.points.map(p=>p[0])),y:Math.min(...g.points.map(p=>p[1])),w:Math.max(...g.points.map(p=>p[0]))-Math.min(...g.points.map(p=>p[0])),h:Math.max(...g.points.map(p=>p[1]))-Math.min(...g.points.map(p=>p[1]))}:g;minX=Math.max(minX,b.x-r.x);maxX=Math.min(maxX,b.x+b.w-r.x-r.w);minY=Math.max(minY,b.y-r.y);maxY=Math.min(maxY,b.y+b.h-r.y-r.h);}
  dx=Math.max(minX,Math.min(maxX,dx));dy=Math.max(minY,Math.min(maxY,dy));
  for(const s of items){const g=this.objects(s.type)[s.index];if(s.type==='boundary')g.points=s.original.points.map(p=>[p[0]+dx,p[1]+dy]);else Object.assign(g,{x:s.original.x+dx,y:s.original.y+dy});}
 },
 pointerDown(e){
  if(!this.editing||!this.scene)return;activeEditor=this;this.canvas.focus({preventScroll:true});const [x,y]=this.point(e);this.drag=null;
  const multi=e.ctrlKey||e.metaKey,corner=multi?null:this.handleAt(x,y,e.pointerType);
  if(corner){this.drag={type:'multiResize',corner,box:this.selectionRect(),items:this.snapshotSelection(),remembered:false};}
  else{
   let point=null;if(!multi&&this.selection().length===1&&this.selected.type==='boundary'){const b=this.objects('boundary')[this.selected.index];const k=b.points.findIndex(p=>Math.hypot(x-p[0],y-p[1])<15);if(k>=0)point={index:this.selected.index,k};}
   if(point)this.drag={type:'curvePoint',...point,remembered:false};
   else {const hit=this.hit(x,y),list=this.selection();
    if(multi){if(hit){const key=selectionKey(hit);this.setSelection(list.some(s=>selectionKey(s)===key)?list.filter(s=>selectionKey(s)!==key):[...list,hit]);}this.controls();this.draw();return;}
    if(!hit)this.setSelection([]);else if(!list.some(s=>selectionKey(s)===selectionKey(hit)))this.setSelection([hit]);
    if(hit)this.drag={type:'multiMove',x,y,items:this.snapshotSelection(),remembered:false};
   }
  }
  if(this.drag){e.preventDefault();this.canvas.setPointerCapture(e.pointerId);}this.controls();this.draw();
 },
 transformSelection(items,box,scale,ax,ay){
  for(const s of items){const src=s.original,g=this.objects(s.type)[s.index];if(s.type==='boundary')g.points=src.points.map(p=>[ax+(p[0]-box.x)*scale,ay+(p[1]-box.y)*scale]);else Object.assign(g,{x:ax+(src.x-box.x)*scale,y:ay+(src.y-box.y)*scale,w:src.w*scale,h:src.h*scale});}
 },
 resizeBounds(){const all=this.selection().map(s=>this.bounds(s.type));return {x:Math.max(...all.map(b=>b.x)),y:Math.max(...all.map(b=>b.y)),w:Math.min(...all.map(b=>b.x+b.w))-Math.max(...all.map(b=>b.x)),h:Math.min(...all.map(b=>b.y+b.h))-Math.max(...all.map(b=>b.y))};},
 pointerMove(e){
  if(!this.editing||!this.scene)return;const [x,y]=this.point(e);if(!this.drag){const corner=this.handleAt(x,y,e.pointerType);this.canvas.style.cursor=corner?(['nw','se'].includes(corner)?'nwse-resize':'nesw-resize'):'grab';return;}
  const d=this.drag;if(!d.remembered){if(d.type==='multiMove'&&Math.hypot(x-d.x,y-d.y)<2)return;this.remember();d.remembered=true;}
  if(d.type==='multiMove')this.moveSnapshot(d.items,x-d.x,y-d.y);
  if(d.type==='multiResize'){const r=resizedGroupRect(d.box,d.corner,x,y,this.resizeBounds(),1904);this.transformSelection(d.items,d.box,r.w/d.box.w,r.x,r.y);}
  if(d.type==='curvePoint'){const b=this.bounds();this.objects('boundary')[d.index].points[d.k]=[Math.max(b.x,Math.min(b.x+b.w,x)),Math.max(b.y,Math.min(b.y+b.h,y))];}
  this.draw();this.node('undo').disabled=!this.history.length;
 },
 resize(scale){const box=this.selectionRect();if(!box||!Number.isFinite(scale)||scale<=0)return;const b=this.resizeBounds();scale=Math.min(scale,b.w/box.w,b.h/box.h);const x=Math.max(b.x,Math.min(b.x+b.w-box.w*scale,box.x+(box.w-box.w*scale)/2)),y=Math.max(b.y,Math.min(b.y+b.h-box.h*scale,box.y+(box.h-box.h*scale)/2));this.remember();this.transformSelection(this.snapshotSelection(),box,scale,x,y);this.controls();this.draw();},
 copyObjects(){const list=this.selection();if(!list.length)return;clipboardPage=this.page;objectClipboard=list.map(s=>({type:s.type,object:clone(this.objects(s.type)[s.index])}));for(const ed of Object.values(editors))ed.controls();this.node('editStatus').textContent=`${list.length}개 객체를 복사했습니다. Ctrl+V로 붙여넣으세요.`;},
 async pasteObjects(){
  if(!this.scene||!objectClipboard.length)return;const active=this.scene,token=loadToken,items=clone(objectClipboard);
  try{await Promise.all(items.filter(s=>s.type==='group').map(s=>this.sprite(s.object.src)));}catch{this.node('editStatus').textContent='복사한 이미지를 불러오지 못했습니다.';return;}if(active!==this.scene||token!==loadToken)return;
  this.remember();this.scene.texts=this.scene.texts||[];const list=[];for(const s of items){const g=s.object;g.id='copy-'+Date.now()+'-'+list.length;const objects=this.objects(s.type);objects.push(g);list.push({type:s.type,index:objects.length-1});}this.setSelection(list);
  // Fit a cross-page paste as a whole so the relative layout remains intact.
  if(clipboardPage===this.page)this.moveSnapshot(this.snapshotSelection(),24,24);else{const box=this.selectionRect(),b=this.resizeBounds(),scale=Math.min(1,b.w/box.w,b.h/box.h);this.transformSelection(this.snapshotSelection(),box,scale,Math.max(b.x,Math.min(b.x+b.w-box.w*scale,box.x+24)),Math.max(b.y,Math.min(b.y+b.h-box.h*scale,box.y+24)));}
  this.controls();this.draw();this.canvas.focus({preventScroll:true});
 },
 deleteObjects(){const list=this.selection();if(!list.length)return;this.remember();for(const type of ['group','text','boundary'])for(const s of list.filter(s=>s.type===type).sort((a,b)=>b.index-a.index))this.objects(type).splice(s.index,1);this.setSelection([]);this.controls();this.draw();},
 async chooseIcon(replace){await originalChoose.call(this,replace);this.setSelection(this.selected?[this.selected]:[]);this.controls();this.draw();},
 editText(replace){originalEditText.call(this,replace);this.setSelection(this.selected?[this.selected]:[]);this.controls();this.draw();},
 buildSourceChoices(){
  if(this.page!==1)return;
  let box=this.node('sourceChoices');if(box)box.remove();
  box=document.createElement('div');box.id='sourceChoices';box.className='source-choices';
  const title=document.createElement('span');title.textContent='왼쪽 아래 자료';box.append(title);
  for(const source of this.original.panels||[]){
   if(!source.src)continue;const button=document.createElement('button');button.type='button';
   button.textContent=source.id==='radar'?'저장된 레이더':'저장된 위성';
   button.onclick=async()=>{const active=this.scene;await this.sprite(source.src);if(active!==this.scene)return;this.remember();const panel=this.scene.panels.find(p=>p.id==='radar');Object.assign(panel,clone(source),{id:'radar',updated:true,custom:false,titleText:source.id==='radar'?'강수현황(레이더)':'위성영상',timeText:''});this.controls();this.draw();};box.append(button);
  }
  const hint=document.createElement('span');hint.textContent='저장된 영상은 바로 선택 · 황사·산불 자료는 아래에서 직접 업로드';box.append(hint);this.node('reportFields').prepend(box);
 },
 drawLabels(){
  const c=this.ctx;c.save();c.textBaseline='middle';
  for(const t of this.scene.labels||[]){c.font=`${t.bold?700:400} ${t.size}px ${reportFont}`;c.fillStyle=t.color;c.textAlign=t.anchor.startsWith('r')?'right':t.anchor.startsWith('l')?'left':'center';let text=t.text;if(text.startsWith('발표시점:')&&this.scene.publicationText)text=this.scene.publicationText;if(t.text==='전국가중기온(전일대비 증감)'){const tail='(전일대비 증감)';c.font=`700 26.6667px ${reportFont}`;const w=c.measureText(tail).width;c.fillText(tail,t.x,t.y);c.font=`700 29.3333px ${reportFont}`;c.fillText('전국가중기온',t.x-w,t.y);}else c.fillText(text,t.x,t.y);}
  c.restore();
 },
 draw(handles=this.editing){if(this.scene?.labels)this.changed=true;originalDraw.call(this,handles);},
 buildPalette(){
  for(const target of ['paletteGrid','symbolGrid'])this.node(target).replaceChildren();
  for(const name of Object.keys(this.scene.palette)){
   const symbol=['arrow_right','parentheses'].includes(name),button=document.createElement('button');button.type='button';button.className='palette-item';button.title=labels[name]||'날씨 아이콘';button.setAttribute('aria-label',(labels[name]||'날씨 아이콘')+' 추가');
   const im=document.createElement('img');im.src=this.scene.palette[name];im.alt='';const label=document.createElement('span');label.textContent=labels[name]||'날씨 아이콘';button.append(im,label);button.onclick=()=>{activeEditor=this;this.node('iconChoice').value=name;this.chooseIcon(false);};this.node(symbol?'symbolGrid':'paletteGrid').append(button);
  }
  const text=document.createElement('button');text.className='palette-item';text.innerHTML='<b style="font-size:20px">T</b><span>글상자</span>';text.onclick=()=>{this.setSelection([]);this.controls();this.draw();this.node('textTools').hidden=false;this.node('textInput').value='';this.node('textInput').focus();};this.node('symbolGrid').append(text);
  if(this.page===1){const boundary=document.createElement('button');boundary.className='palette-item';boundary.textContent='경계선';boundary.onclick=()=>this.node('addBoundary').click();this.node('symbolGrid').append(boundary);}
 },
 async load(day,version,token){await originalLoad.call(this,day,version,token);if(this.scene&&token===loadToken){this.buildPalette();this.buildSourceChoices();this.node('editStatus').textContent='아이콘을 클릭해 추가하고, 화면에서 선택해 이동·크기 조절하세요.';this.controls();this.draw();}},
});
function installEditorUX(){
 for(const ed of Object.values(editors)){
  const originalEdit=ed.node('edit').onclick;ed.node('edit').onclick=()=>{originalEdit();activeEditor=ed;el('figure'+ed.page).classList.toggle('report-preview-only',!ed.editing);ed.node('palettePanel').hidden=!ed.editing;ed.node('imageSettings').hidden=!ed.editing;el('save'+ed.page).hidden=ed.editing;ed.node('edit').textContent=ed.editing?'편집 종료':ed.title();if(ed.editing)ed.canvas.focus({preventScroll:true});};
  ed.node('remove').onclick=()=>ed.deleteObjects();ed.node('copyObjects').onclick=()=>ed.copyObjects();ed.node('pasteObjects').onclick=()=>ed.pasteObjects();
  ed.node('editorControls').addEventListener('pointerdown',()=>{activeEditor=ed;});
 }
 document.querySelectorAll('[data-page]').forEach(button=>button.onclick=()=>{const page=Number(button.dataset.page);document.querySelectorAll('[data-page]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));for(const ed of Object.values(editors)){ed.finishInline?.(true);el('figure'+ed.page).hidden=ed.page!==page;}activeEditor=editors[page];activeEditor.draw();});
 document.addEventListener('keydown',e=>{
  const ed=activeEditor;if(!ed?.editing||!ed.scene||el('figure'+ed.page).hidden)return;
  if(e.target.closest?.('input,textarea,select,[contenteditable="true"]'))return;
  const key=e.key.toLowerCase(),mod=e.ctrlKey||e.metaKey;
  if(mod&&['c','v','z'].includes(key)){e.preventDefault();if(key==='c')ed.copyObjects();if(key==='v')ed.pasteObjects();if(key==='z')ed.node('undo').click();return;}
  if(key==='delete'){e.preventDefault();ed.deleteObjects();}
  if(key==='escape'){ed.setSelection([]);ed.node('textTools').hidden=true;ed.controls();ed.draw();}
 });
}

const editors={1:new ReportEditor(1),2:new ReportEditor(2)};
installEditorUX();
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
 const version=encodeURIComponent(index.updated_kst||'two-page-icons-1');for(const n of [1,2]){el('page'+n).src=window.ENERGY_PREVIEW?.images?.[`energy/${day}/0${n}.webp`]||`energy/${day}/0${n}.webp?v=${version}`;el('save'+n).hidden=false;}el('report').hidden=false;el('print').disabled=false;
 await Promise.all(Object.values(editors).map(ed=>ed.load(day,version,token)));if(token===loadToken){refreshControls();for(const ed of Object.values(editors)){el('figure'+ed.page).classList.add('report-preview-only');ed.node('palettePanel').hidden=true;ed.node('imageSettings').hidden=true;}if(window.ENERGY_PREVIEW){el('status').textContent='검토용 시안 · 2026-11-04 저장 자료 · 편집 내용은 운영 페이지에 반영되지 않습니다.';editors[1].node('edit').click();}}
}
el('date').addEventListener('change',show);el('print').onclick=()=>window.print();
window.addEventListener('beforeprint',()=>Object.values(editors).forEach(ed=>ed.draw(false)));window.addEventListener('afterprint',()=>Object.values(editors).forEach(ed=>ed.draw()));
(async()=>{try{const r=await reportFetch('energy/index.json',{cache:'no-store'});if(!r.ok)throw Error('index');index=await r.json();const dates=index.dates.filter(d=>/^\d{8}$/.test(d));if(!dates.length){el('status').textContent='최근 30일 이내 게시된 자료가 없습니다.';return;}for(const d of dates){const o=document.createElement('option');o.value=d;o.textContent=format(d);el('date').append(o);}el('date').disabled=false;await show();}catch{el('status').textContent='자료 목록을 불러오지 못했습니다. 잠시 후 새로고침해 주세요.';}})();
