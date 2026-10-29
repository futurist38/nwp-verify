// Generated from imagery-service/worker.mjs and scheduler/worker.js.
// Public imagery only. Never accept caller-supplied URLs, times, or credentials.
const ORIGIN = 'https://futurist38.github.io';
const WEATHER = 'https://www.weather.go.kr';
const MAX_BYTES = 4_000_000;
const pending = new Map();
function parseTime(value) {
 if (!/^\d{12}$/.test(value)) throw Error('time');
 const iso = `${value.slice(0,4)}-${value.slice(4,6)}-${value.slice(6,8)}T${value.slice(8,10)}:${value.slice(10)}:00+09:00`;
 const ms = Date.parse(iso); if (!Number.isFinite(ms) || new Date(ms+9*3600000).toISOString().replace(/\D/g,'').slice(0,12)!==value) throw Error('time');
 return {iso,ms};
}
async function get(url, limit=MAX_BYTES) {
 const r = await fetch(url, {redirect:'error',signal:AbortSignal.timeout(20000)});
 if (!r.ok || Number(r.headers.get('content-length'))>limit) throw Error('upstream');
 const reader=r.body.getReader();let size=0;const chunks=[];
 while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>limit){await reader.cancel();throw Error('size');}chunks.push(value);}
 const bytes=new Uint8Array(size);let offset=0;for(const c of chunks){bytes.set(c,offset);offset+=c.length;}return bytes;
}
function satelliteUrl(path) {
 const url=new URL(path,WEATHER);
 if(url.origin!==WEATHER || !/^\/w\/repositary\/image\/sat\/gk2a\/KO\/gk2a_ami_le1b_rgb-s-daynight_ko020lc_\d{12}\.png$/.test(url.pathname) || url.search || url.hash)throw Error('image URL');
 return url;
}
function pngData(bytes) {
 if(bytes.length<24 || ![137,80,78,71,13,10,26,10].every((v,i)=>bytes[i]===v))throw Error('PNG');
 const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
 const w=view.getUint32(16),h=view.getUint32(20);if(w<500||h<500||w>2000||h>2000)throw Error('dimensions');
 let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
 return 'data:image/png;base64,'+btoa(binary);
}
async function panel(kind) {
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
    url=new URL('https://radar.kma.go.kr/cgi-bin/center/nph-rdr_cmp2_img');
    url.search=new URLSearchParams({tm:row.tm,cmp:'HSR',qcd:'HSO',obs:'ECHO',color:'C4',aws:'1',map:'HR',grid:'2',legend:'1',size:'643',itv:'',zoom_level:'0',zoom_x:'0000000',zoom_y:'0000000',gov:'KMA',lonlat:'0',xp:'512',yp:'512',zoom:'1'});
   }
   return {id:kind,title:kind==='satellite'?'위성영상':'강수현황(레이더)',time:row.iso,src:pngData(await get(url))};
  }catch{/* No upstream URLs or exception text in public responses/logs. */}
 }
 throw Error('unavailable');
}
function response(body,status=200){return new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json','Access-Control-Allow-Origin':ORIGIN,'Vary':'Origin','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});}
const imagery = {async fetch(req,env,ctx){
 const url=new URL(req.url);const match=/^\/latest\/(satellite|radar)$/.exec(url.pathname);
 if(req.method!=='GET')return response({error:'method'},405);
 if(!match||url.search)return response({error:'route'},404);
 if(req.headers.get('Origin')!==ORIGIN)return response({error:'origin'},403);
 // Public imagery uses no credentials. Fail closed if the limiter binding is absent.
 if(!env.IMAGERY_LIMITER)return response({error:'not_configured'},503);
 const ip=req.headers.get('CF-Connecting-IP')||'unknown';
 if(!(await env.IMAGERY_LIMITER.limit({key:'ip:'+ip})).success)return response({error:'rate_limit'},429);
 const kind=match[1];const key=new Request(url.origin+'/cache-public-v2/'+kind);const cached=await caches.default.match(key);
 if(cached)return cached;
 if(!pending.has(kind)){
  pending.set(kind,(async()=>{try{
   if(!(await env.IMAGERY_LIMITER.limit({key:'upstream:'+kind})).success)return response({error:'rate_limit'},429);
   const result=response(await panel(kind));result.headers.set('Cache-Control','public, max-age=60');
   await caches.default.put(key,result.clone());return result;
  }catch{return response({error:'image_unavailable'},502);}finally{pending.delete(kind);}})());
 }
 return (await pending.get(kind)).clone();
}};



// GitHub Actions 예약 대행 (Cloudflare Worker, 2026-09-01)
//
// 왜 필요한가: GitHub 의 schedule 이 이 저장소에서 신뢰할 수 없다.
// 매시 예약인데 8/27~9/1 닷새간 하루 1~6회만 떴고, 발동 분도 제멋대로였다.
// 공식 문서가 "부하가 높으면 대기 작업 일부가 버려질 수 있다"고 인정한 동작이다.
// 반면 workflow_dispatch 는 언제나 즉시 실행된다 → 밖에서 정확한 시각에 깨운다.
//
// 필요한 비밀값 (Worker Settings > Variables and Secrets):
//   GH_TOKEN  — 세분화 PAT. futurist38/nwp-verify 한 곳, Actions = Read and write 만.
//   TEST_KEY  — (선택) 브라우저로 수동 시험할 때 쓸 임의 문자열. 없으면 시험 경로 비활성.
//
// 만료 주의: PAT 는 최대 1년. 만료되면 이 Worker 는 계속 돌지만 GitHub 가 401 로 거절해
// 사이트가 조용히 멈춘다. 갱신일은 구글 캘린더에 등록해 두었다.

const REPO = "futurist38/nwp-verify";

// cron 식 → 깨울 워크플로. wrangler.toml 의 crons 와 문자열이 정확히 같아야 한다.
const JOBS = {
  "25 * * * *": "obs-hourly.yml", // 매시 :25 — ASOS 는 정시 +2분이 보통, 드물게 +42분
  "10 21 * * *": "daily.yml",     // 06:10 KST (전일 12z 런)
  "40 1 * * *": "daily.yml",      // 10:40 KST (당일 00z 런)
};

async function dispatch(wf, env) {
  const res = await fetch(
    `https://api.github.com/repos/${REPO}/actions/workflows/${wf}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "nwp-verify-scheduler",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main" }),
    },
  );
  // 204 가 정상. 401 = 토큰 만료/오타, 403 = 권한 부족(Actions 쓰기 확인), 404 = 저장소·파일명.
  const detail = res.status === 204 ? "" : ` ${await res.text()}`;
  console.log(`[dispatch] ${wf} -> ${res.status}${detail}`);
  return res.status;
}

export default {
  async scheduled(event, env, ctx) {
    const wf = JOBS[event.cron];
    if (!wf) return console.log(`[skip] 등록되지 않은 cron: ${event.cron}`);
    ctx.waitUntil(dispatch(wf, env));
  },

  async fetch(req, env, ctx) {
    // Imagery never reaches dispatch and never receives a token in its requests.
    if (new URL(req.url).pathname.startsWith('/latest/')) return imagery.fetch(req, env, ctx);
    const key = new URL(req.url).searchParams.get("key");
    const wf = new URL(req.url).searchParams.get("wf");
    // 시험 경로는 TEST_KEY 를 설정한 경우에만 열린다 (열어두면 그 자체가 남용 통로)
    if (!wf || !env.TEST_KEY || key !== env.TEST_KEY) {
      return new Response("nwp-verify scheduler alive\n");
    }
    if (!Object.values(JOBS).includes(wf)) {
      return new Response("unknown workflow\n", { status: 400 });
    }
    return new Response(`${wf} -> ${await dispatch(wf, env)}\n`);
  },
};

