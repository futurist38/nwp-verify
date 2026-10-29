import {test} from 'node:test';
import assert from 'node:assert/strict';
import worker,{satelliteUrl,pngData,parseTime} from './worker.mjs';
const origin='https://futurist38.github.io';
const request=(path='/latest/radar',headers={Origin:origin})=>new Request('https://example.workers.dev'+path,{headers});
const env={KMA_AUTH_KEY:'test-only-secret',IMAGERY_LIMITER:{limit:async()=>({success:true})}};
test('rejects unknown routes, queries, methods and foreign origins',async()=>{
 for(const [req,code] of [[request('/latest/radar?url=https://evil.test'),404],[request('/latest/fire'),404],[request('/latest/radar',{Origin:'https://evil.test'}),403],[new Request('https://example.workers.dev/latest/radar',{method:'POST'}),405]])assert.equal((await worker.fetch(req,env,{})).status,code);
});
test('fails closed without configuration and respects server rate limit',async()=>{
 assert.equal((await worker.fetch(request(),{},{})).status,503);
 assert.equal((await worker.fetch(request(),{...env,IMAGERY_LIMITER:{limit:async()=>({success:false})}},{})).status,429);
});
test('only approved satellite paths and valid PNG dimensions accepted',()=>{
 for(const path of ['https://evil.test/x.png','//evil.test/x.png','/w/other.png'])assert.throws(()=>satelliteUrl(path));
 assert.match(satelliteUrl('/w/repositary/image/sat/gk2a/KO/gk2a_ami_le1b_rgb-s-daynight_ko020lc_202610290000.png').href,/weather.go.kr/);
 assert.throws(()=>pngData(new TextEncoder().encode('<html>API error</html>')));
 assert.equal(parseTime('202610290900').iso,'2026-10-29T09:00:00+09:00');
});
test('returns actual frame time, caches result and never exposes secret',async()=>{
 const bytes=new Uint8Array(24);bytes.set([137,80,78,71,13,10,26,10]);const view=new DataView(bytes.buffer);view.setUint32(16,636);view.setUint32(20,620);
 let saved=null,calls=0;globalThis.caches={default:{match:async()=>saved?.clone(),put:async(k,r)=>{saved=r;}}};
 const tm=new Date(Date.now()+9*3600000-300000).toISOString().slice(0,16).replace(/[-T:]/g,'');
 globalThis.fetch=async url=>{calls++;url=new URL(url);if(url.hostname==='www.weather.go.kr')return Response.json([{tm}]);assert.equal(url.hostname,'apihub-pub.kma.go.kr');assert.equal(url.searchParams.get('authKey'),env.KMA_AUTH_KEY);assert.equal(url.searchParams.get('legend'),'1');return new Response(bytes);};
 const r=await worker.fetch(request(),env,{});assert.equal(r.status,200);const text=await r.text();assert.ok(!text.includes(env.KMA_AUTH_KEY));assert.ok(!text.includes('authKey'));const data=JSON.parse(text);assert.equal(data.time,parseTime(tm).iso);assert.match(data.src,/^data:image\/png;base64,/);assert.equal(calls,2);
 assert.equal((await worker.fetch(request(),env,{})).status,200);assert.equal(calls,2);
});
test('upstream errors do not echo secret URLs',async()=>{
 globalThis.caches={default:{match:async()=>null}};globalThis.fetch=async()=>{throw Error('authKey=test-only-secret');};
 const r=await worker.fetch(request(),env,{});assert.equal(r.status,502);assert.equal(await r.text(),'{"error":"image_unavailable"}');
});
