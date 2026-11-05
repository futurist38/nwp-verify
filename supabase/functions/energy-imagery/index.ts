// Public KMA data only. Browser users must already have unlocked the energy editor.
// Plain JavaScript so the same implementation is tested with Node and run by Deno.
const WEATHER = 'https://www.weather.go.kr';
const ORIGIN = 'https://futurist38.github.io';
const DAY = 86400000;
const cache = new Map(), pending = new Map(), users = new Map();
export const isoKST = ms => new Date(ms + 9 * 3600000).toISOString().slice(0, 19) + '+09:00';
export const compact = ms => isoKST(ms).replace(/\D/g, '').slice(0, 12);
export function parseTime(tm) {
  if (!/^\d{12}$/.test(tm)) throw Error('time');
  const ms = Date.parse(`${tm.slice(0,4)}-${tm.slice(4,6)}-${tm.slice(6,8)}T${tm.slice(8,10)}:${tm.slice(10)}:00+09:00`);
  if (!Number.isFinite(ms) || compact(ms) !== tm) throw Error('time');
  return ms;
}
export function requestTime(kind, value, now = Date.now()) {
  if (!['satellite', 'radar', 'warning', 'pm10', 'fog'].includes(kind)) throw Error('kind');
  const ms = parseTime(value);
  if (ms > now || ms < now - 30 * DAY) throw Error('range');
  const interval = {satellite: 2, radar: 5, warning: 1, pm10: 60, fog: 10}[kind] * 60000;
  return {requested: ms, at: Math.floor(ms / interval) * interval};
}
export function pngData(bytes) {
  if (bytes.length < 24 || ![137,80,78,71,13,10,26,10].every((v,i) => bytes[i] === v)) throw Error('png');
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), w = view.getUint32(16), h = view.getUint32(20);
  if (w < 200 || h < 200 || w > 2200 || h > 2200) throw Error('dimensions');
  let s = ''; for (let i=0;i<bytes.length;i+=8192) s += String.fromCharCode(...bytes.subarray(i,i+8192));
  return 'data:image/png;base64,' + btoa(s);
}
async function get(url, signal, limit = 5000000) {
  // URLs are generated internally. Redirects cannot escape the fixed upstreams.
  const u = new URL(url);
  if (!['www.weather.go.kr', 'radar.kma.go.kr'].includes(u.hostname) || u.protocol !== 'https:') throw Error('host');
  const r = await fetch(u, {redirect:'error', signal:AbortSignal.any([signal, AbortSignal.timeout(12000)])});
  if (!r.ok || Number(r.headers.get('content-length')) > limit) throw Error('upstream');
  const reader = r.body.getReader(), chunks = []; let size = 0;
  while (true) {const {done,value} = await reader.read(); if (done) break; size += value.length; if (size > limit) {await reader.cancel();throw Error('size');}chunks.push(value);}
  const out = new Uint8Array(size);let offset=0;for(const v of chunks){out.set(v,offset);offset+=v.length;}return out;
}
const text = async (url, signal) => new TextDecoder().decode(await get(url, signal, 2000000));
async function cached(key, fn, age = 120000) {
  const hit = cache.get(key);if (hit && hit.until > Date.now()) return hit.value;
  if (pending.has(key)) return pending.get(key);
  const task = (async () => {try {const value = await fn();if(cache.size>=32)cache.delete(cache.keys().next().value);cache.set(key,{value,until:Date.now()+age});return value;}finally{pending.delete(key);}})();
  pending.set(key,task);return task;
}
export function satelliteFrame(rows, at, kind = 'satellite') {
  if (!Array.isArray(rows)) throw Error('frames');
  const pattern = kind === 'fog' ? /^\/w\/repositary\/image\/sat\/gk2a\/KO\/gk2a_ami_le2_fog_ko020lc_\d{12}\.png$/ : /^\/w\/repositary\/image\/sat\/gk2a\/KO\/gk2a_ami_le1b_rgb-s-daynight_ko020lc_\d{12}\.png$/;
  // KMA row.tm is KST, whereas the image filename is UTC. Never infer KST from the filename.
  return rows.map(r => {try {const ms=parseTime(r.tm),url=new URL(r.url,WEATHER);if(url.origin!==WEATHER||!pattern.test(url.pathname)||url.search||url.hash)return null;return {ms,url:url.href};}catch{return null;}}).filter(r=>r&&r.ms===at)[0] || null;
}
export function warningChoices(markup, at) {
  return [...markup.matchAll(/<option\b[^>]*value="(met:(\d{12}):(\d+))"/g)].map(m=>({id:m[1],ms:parseTime(m[2]),serial:m[3]})).filter(r=>r.ms<=at).sort((a,b)=>b.ms-a.ms);
}
export function warningImage(markup, issue) {
  const match = markup.match(/src=["']([^"']*KTKO50_(\d{12})_108_(\d+)\.png)[^"']*["']/);
  if(!match || parseTime(match[2])!==issue.ms || match[3]!==issue.serial) throw Error('warning');
  const url = new URL(match[1], WEATHER);
  if(url.origin!==WEATHER || !/^\/w\/repositary\/image\/wrn\/img\/KTKO50_\d{12}_108_\d+\.png$/.test(url.pathname))throw Error('warning');
  const block=markup.split('□ 발효시각')[1]?.split('<strong>')[0]||'';
  const effective=[...block.matchAll(/(\d{4})년\s*(\d+)월\s*(\d+)일\s*(\d+)시\s*(\d+)분/g)].map(m=>parseTime(m.slice(1).map((v,i)=>i?v.padStart(2,'0'):v).join('')));
  return {url:url.href, effective:[...new Set(effective)].map(isoKST)};
}
export function pm10Rows(markup, at) {
  // KMA tables use 01..24 hours. 00:00 belongs to the previous day's 24:00 column.
  const kst=isoKST(at),hour=Number(kst.slice(11,13)),day=isoKST(at-(hour===0?DAY:0)).slice(0,10),col=(hour||24)-1;
  const tables=[...markup.matchAll(/<table\b[^>]*>([\s\S]*?)<\/table>/g)];
  const table=tables.find(m=>{const d=m[1].match(/PM10\s*:\s*1시간 평균값[^\d]*(\d{4})년\s*(\d+)월\s*(\d+)일/);return d && d.slice(1).map((s,i)=>i?s.padStart(2,'0'):s).join('-')===day;});
  if(!table)throw Error('date');
  const rows=[];
  for(const m of table[1].matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/g)){
    const name=m[1].match(/<th\s+scope="row">\s*(\d+)\s+([^<]+)<\/th>/);if(!name)continue;
    const cells=[...m[1].matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/g)];if(cells.length!==24)throw Error('columns');
    const v=cells[col][1].trim();rows.push({id:String(Number(name[1])),name:name[2].trim(),value:/^\d+$/.test(v)?Number(v):null});
  }
  if(rows.length<10 || !rows.some(r=>r.value!==null))throw Error('unavailable');
  return rows;
}
export async function loadSource(kind, tm, now=Date.now()) {
  const {requested,at}=requestTime(kind,tm,now),signal=AbortSignal.timeout(45000);
  const common={id:kind,requestedTime:isoKST(requested),time:isoKST(at),provider:kind==='pm10'?'기상청 황사 관측망':'기상청'};
  if(kind==='satellite'||kind==='fog'){
    const query=new URLSearchParams({mapType:'img',tm:isoKST(at).slice(0,16).replaceAll('-','.').replace('T','.'),itv:'0.5',leaflet:'0',kmap:'0',area:'ko020lc',data:kind==='fog'?'fog':'rgb-s-daynight'});
    const rows=JSON.parse(await text(WEATHER+'/w/wnuri-img/rest/sat/images/gk2a.do?'+query,signal));
    const frame=satelliteFrame(rows,at,kind);if(!frame)throw Error('unavailable');
    return {...common,title:kind==='fog'?'안개(위성)':'위성영상',src:pngData(await get(frame.url,signal))};
  }
  if(kind==='radar'){
    const query=new URLSearchParams({mapType:'img',tm:isoKST(at).slice(0,16).replaceAll('-','.').replace('T','.'),itv:'5',leaflet:'0',kmap:'0',area:'KWK',data:'pop'});
    const rows=JSON.parse(await text(WEATHER+'/w/wnuri-img/rest/radar/cmp/images.do?'+query,signal));
    const row=Array.isArray(rows)?rows.find(r=>r.tm===compact(at)):null;if(!row)throw Error('unavailable');
    const url=new URL(row.url,WEATHER);
    if(url.origin!==WEATHER||url.pathname!=='/w/cgi-bin/rdr_new/nph-vs_rdr_cmp_img'||url.searchParams.get('tm')!==compact(at)||url.searchParams.get('obs')!=='HSR'||url.searchParams.get('cmp')!=='SFC')throw Error('radar');
    return {...common,title:'강수현황(레이더)',src:pngData(await get(url.href,signal))};
  }
  if(kind==='warning'){
    // Stop at the latest published bulletin no later than the requested time.
    // The graphic is the bulletin's effective-status graphic, not a reconstructed minute-by-minute status.
    for(let lag=0;lag<30;lag++){
      const date=isoKST(at-lag*DAY).slice(0,10);
      const url=WEATHER+'/w/special-report/list.do?'+new URLSearchParams({stn:'108',kind:'met',date});
      let markup=await cached('wrn:'+date,()=>text(url,signal));const issue=warningChoices(markup,at)[0];if(!issue)continue;
      try{warningImage(markup,issue);}catch{markup=await text(url+'&'+new URLSearchParams({reportId:issue.id}),signal);}
      const graphic=warningImage(markup,issue);
      return {...common,title:'특보현황',time:isoKST(issue.ms),timeKind:'발표',effectiveTimes:graphic.effective,src:pngData(await get(graphic.url,signal))};
    }
    throw Error('unavailable');
  }
  const hour=Number(isoKST(at).slice(11,13)),date=isoKST(at-(hour===0?DAY:0)).slice(0,10).replaceAll('-','.')+'.';
  const markup=await cached('pm10:'+date,()=>text(WEATHER+'/w/hazard/dust/dust-obs/graph.do?'+new URLSearchParams({area:'0',stnId:'0',view:'2',tm:date}),signal));
  const rows=pm10Rows(markup,at);
  const css=await cached('pm10:css',()=>text(WEATHER+'/w/resources/css-2021/common-ui.css',signal),DAY);
  const positions=new Map([...css.matchAll(/li\.pm10_(\d+)\{left:\s*(\d+)px;top:\s*(\d+)px;/g)].map(m=>[String(Number(m[1])),[Number(m[2]),Number(m[3])]]));
  for(const row of rows){if(!positions.has(row.id))throw Error('layout');[row.x,row.y]=positions.get(row.id);}
  const basemap=await cached('pm10:map',async()=>pngData(await get(WEATHER+'/w/resources/images/korea_map3.png',signal)),DAY);
  return {...common,title:'미세먼지(PM10)',map:{basemap,rows},timeKind:'관측'};
}
function response(value,status=200){return new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Access-Control-Allow-Origin':ORIGIN,'Access-Control-Allow-Headers':'authorization, apikey, content-type','Access-Control-Allow-Methods':'POST, OPTIONS','Vary':'Origin','Cache-Control':'no-store'}});}
export async function handle(req,env){
  if(req.headers.get('Origin') && req.headers.get('Origin')!==ORIGIN)return response({error:'origin'},403);
  if(req.method==='OPTIONS')return response({});
  if(req.method!=='POST')return response({error:'method'},405);
  try{
    const auth=req.headers.get('Authorization');if(!auth?.startsWith('Bearer '))return response({error:'unauthorized'},401);
    // RLS returns only this authenticated user's row. No service role key is used.
    const r=await fetch(env.url+'/rest/v1/energy_editors?select=user_id,unlocked_at&limit=1',{headers:{apikey:env.key,Authorization:auth},signal:AbortSignal.timeout(8000)});
    const rows=r.ok?await r.json():[];const user=rows[0];if(!user||Date.parse(user.unlocked_at)<Date.now()-DAY)return response({error:'locked'},403);
    const state=users.get(user.user_id)||{at:Date.now(),n:0};if(Date.now()-state.at>60000){state.at=Date.now();state.n=0;}if(++state.n>12)return response({error:'rate_limit'},429);if(users.size>=500)users.delete(users.keys().next().value);users.set(user.user_id,state);
    const raw=await req.text();if(raw.length>512)return response({error:'request'},400);
    let body;try{body=JSON.parse(raw);requestTime(body.kind,body.time);}catch{return response({error:'invalid_time'},400);}
    const data=await cached(body.kind+':'+body.time,()=>loadSource(body.kind,body.time));return response(data);
  }catch{return response({error:'source_unavailable'},502);}
}
if(typeof Deno!=='undefined'){
  const keys=JSON.parse(Deno.env.get('SUPABASE_PUBLISHABLE_KEYS')||'{}');
  Deno.serve(req=>handle(req,{url:Deno.env.get('SUPABASE_URL'),key:keys.default||Object.values(keys)[0]||Deno.env.get('SUPABASE_ANON_KEY')}));
}

