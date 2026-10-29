// Public imagery only. Never accept caller-supplied URLs, times, or credentials.
const ORIGIN = 'https://futurist38.github.io';
const WEATHER = 'https://www.weather.go.kr';
const MAX_BYTES = 4_000_000;
const pending = new Map();
export function parseTime(value) {
 if (!/^\d{12}$/.test(value)) throw Error('time');
 const iso = `${value.slice(0,4)}-${value.slice(4,6)}-${value.slice(6,8)}T${value.slice(8,10)}:${value.slice(10)}:00+09:00`;
 const ms = Date.parse(iso); if (!Number.isFinite(ms)) throw Error('time');
 return {iso,ms};
}
async function get(url, limit=MAX_BYTES) {
 const r = await fetch(url, {redirect:'error',signal:AbortSignal.timeout(20000)});
 if (!r.ok || Number(r.headers.get('content-length'))>limit) throw Error('upstream');
 const reader=r.body.getReader();let size=0;const chunks=[];
 while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>limit){await reader.cancel();throw Error('size');}chunks.push(value);}
 const bytes=new Uint8Array(size);let offset=0;for(const c of chunks){bytes.set(c,offset);offset+=c.length;}return bytes;
}
export function satelliteUrl(path) {
 const url=new URL(path,WEATHER);
 if(url.origin!==WEATHER || !/^\/w\/repositary\/image\/sat\/gk2a\/KO\/gk2a_ami_le1b_rgb-s-daynight_ko020lc_\d{12}\.png$/.test(url.pathname) || url.search || url.hash)throw Error('image URL');
 return url;
}
export function pngData(bytes) {
 if(bytes.length<24 || ![137,80,78,71,13,10,26,10].every((v,i)=>bytes[i]===v))throw Error('PNG');
 const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
 const w=view.getUint32(16),h=view.getUint32(20);if(w<500||h<500||w>2000||h>2000)throw Error('dimensions');
 let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
 return 'data:image/png;base64,'+btoa(binary);
}
async function panel(kind,env) {
 const now=Date.now();const kst=new Date(now+9*3600000).toISOString();
 const query=new URLSearchParams({mapType:'img',tm:kst.slice(0,16).replaceAll('-','.').replace('T','.'),itv:kind==='satellite'?'0.5':'5',leaflet:'0',kmap:'0',area:kind==='satellite'?'ko020lc':'KWK',data:kind==='satellite'?'rgb-s-daynight':'pop'});
 const path=kind==='satellite'?'/w/wnuri-img/rest/sat/images/gk2a.do':'/w/wnuri-img/rest/radar/cmp/images.do';
 const rows=JSON.parse(new TextDecoder().decode(await get(WEATHER+path+'?'+query,1_000_000)));
 if(!Array.isArray(rows))throw Error('frames');
 const candidates=rows.map(row=>{try{return {...row,...parseTime(row.tm)};}catch{return null;}}).filter(row=>row&&row.ms<=now&&row.ms>=now-3600000).sort((a,b)=>b.ms-a.ms);
 // At most two published frames; never invent an observation time from the browser clock.
 for(const row of candidates.slice(0,2)){
  try{
   let url;
   if(kind==='satellite')url=satelliteUrl(row.url);
   else{
    url=new URL('https://apihub-pub.kma.go.kr/api/typ03/cgi/rdr/nph-rdr_cmp1_img');
    url.search=new URLSearchParams({tm:row.tm,cmp:'HSR',qcd:'HSLP',obs:'ECHD',color:'C4',aws:'0',acc:'',map:'HR',grid:'2',legend:'1',size:'600',itv:'5',zoom_level:'0',zoom_x:'0000000',zoom_y:'0000000',gov:'',authKey:env.KMA_AUTH_KEY});
   }
   return {id:kind,title:kind==='satellite'?'위성영상':'강수현황(레이더)',time:row.iso,src:pngData(await get(url))};
  }catch{/* No upstream URLs or exception text in public responses/logs. */}
 }
 throw Error('unavailable');
}
function response(body,status=200){return new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json','Access-Control-Allow-Origin':ORIGIN,'Vary':'Origin','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});}
export default {async fetch(req,env,ctx){
 const url=new URL(req.url);const match=/^\/latest\/(satellite|radar)$/.exec(url.pathname);
 if(req.method!=='GET')return response({error:'method'},405);
 if(!match||url.search)return response({error:'route'},404);
 if(req.headers.get('Origin')!==ORIGIN)return response({error:'origin'},403);
 // Fail closed if the deployment forgot its secret or server-side limiter.
 if(!env.KMA_AUTH_KEY||!env.IMAGERY_LIMITER)return response({error:'not_configured'},503);
 const ip=req.headers.get('CF-Connecting-IP')||'unknown';
 if(!(await env.IMAGERY_LIMITER.limit({key:'ip:'+ip})).success)return response({error:'rate_limit'},429);
 const kind=match[1];const key=new Request(url.origin+'/cache-v1/'+kind);const cached=await caches.default.match(key);
 if(cached)return cached;
 if(!pending.has(kind)){
  if(!(await env.IMAGERY_LIMITER.limit({key:'upstream:'+kind})).success)return response({error:'rate_limit'},429);
  pending.set(kind,(async()=>{try{
   const result=response(await panel(kind,env));result.headers.set('Cache-Control','public, max-age=60');
   await caches.default.put(key,result.clone());return result;
  }catch{return response({error:'image_unavailable'},502);}finally{pending.delete(kind);}})());
 }
 return (await pending.get(kind)).clone();
}};
