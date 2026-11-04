/* Shared editor integration. Generated report data remains the baseline. */
(()=>{
 if(window.ENERGY_PREVIEW)return;
 const store=new EnergySharedStore(),states=new Map();let unlocked=0;
 const note=(ed,text)=>ed.node('editStatus').textContent=text;
 const safeURL=s=>typeof s==='string'&&/^https:\/\/lfxajxconibunipejdjz\.supabase\.co\/storage\/v1\/object\/public\/energy-images\/[0-9a-f-]{36}\/\d{8}\/[0-9a-f]{64}\.(png|jpg|webp)$/.test(s);
 const st=ed=>states.get(ed.page);
 async function unlock(){if(Date.now()<unlocked)return true;const key=window.prompt('편집 키를 입력하세요.');if(key===null)return false;await store.unlock(key.trim());unlocked=Date.now()+23*3600000;return true;}
 function message(e){return e.status===409?'다른 사람이 먼저 저장했습니다. 내 작업은 브라우저에 보관했습니다. 공유본 다시 불러오기로 최신 내용을 확인해 주세요.':e.status===403?'편집 권한을 확인하지 못했습니다. 편집을 종료한 뒤 키를 다시 입력해 주세요.':'공유 저장소에 연결하지 못했습니다. 내 작업은 유지됩니다. 잠시 후 다시 시도해 주세요.';}
 async function source(src,ed,day){
  for(const [key,value] of Object.entries(ed.original.palette||{}))if(value===src)return {palette:key};
  const n=ed.original.groups.findIndex(g=>g.src===src);if(n>=0)return {original:n};
  if(safeURL(src))return {url:src};
  if(!/^data:image\/(png|jpeg|webp);base64,/.test(src))throw Error('Unsupported image');
  return {url:await store.upload(day,await (await fetch(src)).blob())};
 }
 function resolve(ref,ed){if(ref&&typeof ref.palette==='string'&&Object.hasOwn(ed.original.palette,ref.palette))return ed.original.palette[ref.palette];if(Number.isInteger(ref?.original)&&ed.original.groups[ref.original])return ed.original.groups[ref.original].src;if(safeURL(ref?.url))return ref.url;throw Error('Invalid shared image');}
 async function pack(ed,scene,day){
  ed={original:clone(ed.original)};
  const out={schema:1,groups:[],boundaries:scene.boundaries||[],texts:scene.texts||[],labelOverrides:scene.labelOverrides||{},labelColors:scene.labelColors||{},publicationText:scene.publicationText||'',panels:[]};
  for(const g of scene.groups)out.groups.push({...g,src:undefined,image:await source(g.src,ed,day)});
  for(const p of scene.panels||[]){const q={...p};delete q.src;if(p.updated)q.image=await source(p.src,ed,day);out.panels.push(q);}
  if(JSON.stringify(out).length>500000)throw Error('Edit too large');return out;
 }
 function unpack(ed,p){
  if(p?.schema!==1)throw Error('Unsupported shared data');const out=clone(ed.original);if(p.reset===true)return out;
  const list=(a,max)=>{if(!Array.isArray(a)||a.length>max)throw Error('Invalid shared list');return a;};
  const box=g=>{if(!g||!['x','y','w','h'].every(k=>Number.isFinite(g[k]))||g.w<=0||g.h<=0||g.w>4000||g.h>4000||Math.abs(g.x)>4000||Math.abs(g.y)>4000)throw Error('Invalid shared object');return {x:g.x,y:g.y,w:g.w,h:g.h};};
  const text=t=>{if(typeof t!=='string'||t.length>500)throw Error('Invalid text');return t;};
  const colors=a=>{if(!Array.isArray(a)||a.length>500)throw Error('Invalid colors');return a.map(x=>['#000000','#e60012','#0074bf','#666666'].includes(x)?x:null);};
  out.groups=list(p.groups,300).map(g=>({...box(g),src:resolve(g.image,ed)}));
  out.texts=list(p.texts,100).map(g=>({...box(g),text:text(g.text),colors:colors(g.colors||[])}));
  out.boundaries=ed.page===2?[]:list(p.boundaries,100).map(b=>{if(!/^#[0-9a-f]{6}$/i.test(b.color)||!Number.isFinite(b.width)||b.width<0||b.width>30)throw Error('Invalid boundary');return {color:b.color,width:b.width,points:list(b.points,4).map(x=>{if(!Array.isArray(x)||x.length!==2||!x.every(v=>Number.isFinite(v)&&Math.abs(v)<5000))throw Error('Invalid point');return x;})};});
  if(out.boundaries.some(b=>b.points.length!==4))throw Error('Invalid points');
  out.labelOverrides={};out.labelColors={};
  for(const [i,v] of Object.entries(p.labelOverrides||{}))if(/^\d+$/.test(i)&&out.labels?.[i])out.labelOverrides[i]=text(v);
  for(const [i,v] of Object.entries(p.labelColors||{}))if(/^\d+$/.test(i)&&out.labels?.[i])out.labelColors[i]=colors(v);
  out.publicationText=text(p.publicationText||'');
  if(ed.page===1)for(const q of list(p.panels,2)){const panel=out.panels.find(x=>x.id===q.id);if(!panel)throw Error('Invalid panel');for(const k of ['timeText','titleText','time'])if(q[k]!==undefined)panel[k]=text(q[k]);if(q.updated){panel.src=resolve(q.image,ed);panel.updated=true;panel.custom=!!q.custom;}}
  return out;
 }
 async function apply(ed,scene,day,token){
  await Promise.all([...scene.groups,...(scene.panels||[]).filter(p=>p.updated)].map(g=>ed.sprite(g.src)));
  if(day!==ed.day||token!==loadToken)return false;ed.finishInline?.(false);ed.scene=scene;ed.setSelection([]);ed.history=[];ed.drag=null;ed.changed=true;ed.controls();ed.draw();return true;
 }
 async function load(ed){
  if(!ed.scene)return;const day=ed.day,token=loadToken,state={day,version:null,busy:true};states.set(ed.page,state);ed.node('edit').disabled=true;
  try{const row=await store.read(day,ed.page);if(st(ed)!==state||token!==loadToken)return;
   if(row.payload)await apply(ed,unpack(ed,row.payload),day,token);
   if(st(ed)!==state||token!==loadToken)return;state.version=Number(row.version);
   note(ed,row.payload?'공유된 편집 내용을 불러왔습니다.':'아직 공유된 편집이 없습니다. 편집 후 공유 저장을 눌러 주세요.');
  }catch(e){if(st(ed)===state)note(ed,'공유본을 불러오지 못했습니다. 현재 자료를 표시합니다. 공유본 다시 불러오기를 눌러 주세요.');}
  finally{if(st(ed)===state){state.busy=false;ed.node('edit').disabled=false;}}
 }
 async function save(ed){
  const state=st(ed);if(!state||state.busy||!ed.scene)return;
  ed.finishInline?.(true);const scene=clone(ed.scene),day=ed.day,token=loadToken;
  try{localStorage.setItem(ed.storageKey(),JSON.stringify(scene));}catch{}
  if(state.version===null){note(ed,'최신 공유본을 확인하지 못해 저장을 멈췄습니다. 내 작업은 유지됩니다. 공유본 다시 불러오기를 눌러 주세요.');return;}
  state.busy=true;ed.node('saveLayout').disabled=true;note(ed,'공유 저장 중…');
  try{if(!await unlock())return;const payload=await pack(ed,scene,day);const row=await store.save(day,ed.page,state.version,payload);
   if(st(ed)===state&&token===loadToken){state.version=Number(row.version);note(ed,'공유 저장 완료 · 다른 접속자도 새로고침하면 볼 수 있습니다.');}
  }catch(e){if(e.status===403)unlocked=0;if(st(ed)===state)note(ed,message(e));}
  finally{state.busy=false;if(st(ed)===state)ed.node('saveLayout').disabled=false;}
 }
 window.energyShared={load:async()=>{await Promise.all(Object.values(editors).map(load));},pack,unpack};
 for(const ed of Object.values(editors)){
  const edit=ed.node('edit').onclick;ed.node('edit').onclick=async()=>{if(st(ed)?.busy)return;if(ed.editing){edit();return;}try{if(await unlock())edit();}catch(e){unlocked=0;note(ed,message(e));}};
  ed.node('saveLayout').textContent='공유 저장';ed.node('saveLayout').onclick=()=>save(ed);
  const reset=ed.node('reset').onclick;ed.node('reset').onclick=()=>{reset();note(ed,'자동 배치로 초기화했습니다. 모두에게 반영하려면 공유 저장을 눌러 주세요.');};
  const reload=document.createElement('button');reload.type='button';reload.className='shared-reload';reload.textContent='공유본 다시 불러오기';reload.onclick=async()=>{if(st(ed)?.busy)return;if(ed.editing&&!window.confirm('현재 화면 대신 최신 공유본을 불러올까요?'))return;await load(ed);};
  ed.node('editStatus').before(reload);
  const local=document.createElement('button');local.type='button';local.textContent='이 브라우저 저장본 불러오기';local.onclick=async()=>{if(st(ed)?.busy||!ed.scene)return;try{if(!await unlock())return;const raw=JSON.parse(localStorage.getItem(ed.storageKey()));if(!raw){note(ed,'이 브라우저에 저장된 편집이 없습니다.');return;}const scene={...clone(ed.original),...raw,palette:clone(ed.original.palette),labels:clone(ed.original.labels||[])};await apply(ed,scene,ed.day,loadToken);note(ed,'브라우저 저장본을 불러왔습니다. 확인 후 공유 저장을 눌러 주세요.');}catch{note(ed,'브라우저 저장본을 불러오지 못했습니다.');}};
  ed.node('editorControls').append(local);
 }
})();
