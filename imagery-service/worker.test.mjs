import {test,beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import worker,{satelliteUrl,pngData,parseTime} from './worker.mjs';
import scheduler from '../scheduler/worker.js';
const request=(path='/latest/radar',headers={Origin:'https://futurist38.github.io'})=>new Request('https://example.workers.dev'+path,{headers});
const env={IMAGERY_LIMITER:{limit:async()=>({success:true})}};
const bytes=new Uint8Array(24);bytes.set([137,80,78,71,13,10,26,10]);const view=new DataView(bytes.buffer);view.setUint32(16,678);view.setUint32(20,663);
const tm=()=>new Date(Date.now()+9*3600000-300000).toISOString().slice(0,16).replace(/[-T:]/g,'');
let saved,calls;
beforeEach(()=>{saved=null;calls=[];globalThis.caches={default:{match:async()=>saved?.clone(),put:async(k,r)=>{saved=r;}}};globalThis.fetch=async(url,options)=>{url=new URL(url);calls.push({url,options});if(url.pathname.endsWith('.do'))return Response.json([{tm:tm(),url:'/w/repositary/image/sat/gk2a/KO/gk2a_ami_le1b_rgb-s-daynight_ko020lc_202610290000.png'}]);return new Response(bytes);};});
test('rejects unknown routes, queries, methods and foreign origins before upstream',async()=>{
 for(const [req,code] of [[request('/latest/radar?url=https://evil.test'),404],[request('/latest/fire'),404],[request('/latest/radar',{Origin:'https://evil.test'}),403],[new Request('https://example.workers.dev/latest/radar',{method:'POST'}),405]])assert.equal((await worker.fetch(req,env,{})).status,code);
 assert.equal(calls.length,0);
});
test('requires limiter, never requires an API key, and enforces rate limit',async()=>{
 assert.equal((await worker.fetch(request(),{},{})).status,503);
 assert.equal((await worker.fetch(request(),{IMAGERY_LIMITER:{limit:async()=>({success:false})}},{})).status,429);
 assert.equal((await worker.fetch(request(),env,{})).status,200);
});
test('allows only fixed satellite products and validates date/PNG bounds',()=>{
 for(const path of ['https://evil.test/x.png','//evil.test/x.png','/w/other.png'])assert.throws(()=>satelliteUrl(path));
 assert.throws(()=>pngData(new TextEncoder().encode('<html>API error</html>')));
 assert.throws(()=>parseTime('202602310900'));
 assert.equal(parseTime('202610290900').iso,'2026-10-29T09:00:00+09:00');
});
test('radar is public complete HSR with real frame time and 60-second cache',async()=>{
 const r=await worker.fetch(request(),env,{});assert.equal(r.status,200);assert.equal(r.headers.get('Access-Control-Allow-Origin'),'https://futurist38.github.io');assert.equal(r.headers.get('Cache-Control'),'public, max-age=60');
 const data=await r.json();assert.equal(data.time,parseTime(tm()).iso);assert.match(data.src,/^data:image\/png;base64,/);
 const u=calls[1].url;assert.equal(u.hostname,'radar.kma.go.kr');assert.equal(u.pathname,'/cgi-bin/center/nph-rdr_cmp2_img');for(const [k,v] of Object.entries({cmp:'HSR',map:'HR',legend:'1'}))assert.equal(u.searchParams.get(k),v);assert.equal(u.searchParams.has('authKey'),false);
 assert.equal((await worker.fetch(request(),env,{})).status,200);assert.equal(calls.length,2);
});
test('parallel requests share one upstream fetch',async()=>{
 const results=await Promise.all([worker.fetch(request(),env,{}),worker.fetch(request(),env,{})]);assert.deepEqual(results.map(r=>r.status),[200,200]);assert.equal(calls.length,2);
});
test('rejects stale/future metadata and upstream HTML instead of fabricating imagery',async()=>{
 globalThis.fetch=async()=>Response.json([{tm:'200001010000'},{tm:'209901010000'}]);assert.equal((await worker.fetch(request(),env,{})).status,502);
 globalThis.fetch=async url=>String(url).includes('.do')?Response.json([{tm:tm()}]):new Response('<html>Error</html>');assert.equal((await worker.fetch(request(),env,{})).status,502);
});
test('errors do not echo authenticated scheduler secrets or upstream details',async()=>{
 globalThis.fetch=async()=>{throw Error('private-token-test');};const r=await scheduler.fetch(request(),{...env,GH_TOKEN:'private-token-test'},{});assert.equal(r.status,502);assert.equal(await r.text(),'{"error":"image_unavailable"}');
});
test('scheduler cron still dispatches the same workflow',async()=>{
 let task;globalThis.fetch=async(url,options)=>{calls.push({url,options});return new Response(null,{status:204});};await scheduler.scheduled({cron:'25 * * * *'},{GH_TOKEN:'test-token'},{waitUntil:p=>task=p});await task;assert.match(calls[0].url,/obs-hourly.yml\/dispatches$/);assert.equal(JSON.parse(calls[0].options.body).ref,'main');
});
test('public image route cannot dispatch workflows, original protected test route remains protected',async()=>{
 await scheduler.fetch(request('/latest/radar?wf=daily.yml&key=test'),{...env,GH_TOKEN:'test-token',TEST_KEY:'test'},{});assert.equal(calls.length,0);
 const r=await scheduler.fetch(request('/?wf=daily.yml'),{...env,GH_TOKEN:'test-token',TEST_KEY:'test'},{});assert.equal(await r.text(),'nwp-verify scheduler alive\n');assert.equal(calls.length,0);
});
