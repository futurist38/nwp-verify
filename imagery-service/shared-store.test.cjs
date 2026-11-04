const {test}=require('node:test');const assert=require('node:assert/strict');
const {EnergySharedStore}=require('../site/energy-shared.js');
function harness(handler){const calls=[],values=new Map();return {calls,values,store:new EnergySharedStore({storage:{getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)},fetcher:async(url,opts)=>{calls.push({url,opts});const [status,value]=await handler(url,opts);return {ok:status<300,status,json:async()=>value};}})};}
const session={access_token:'test-access',refresh_token:'test-refresh',user:{id:'test-user'},expires_at:9999999999};
test('public read does not create a login and distinguishes empty from unavailable',async()=>{
 const h=harness(()=>[200,[]]);assert.equal((await h.store.read('20261104',1)).version,0);assert.equal(h.calls.length,1);assert.equal(h.calls[0].opts.headers.Authorization,undefined);
 const f=harness(()=>[503,{message:'offline'}]);await assert.rejects(f.store.read('20261104',1),e=>e.status===503);
});
test('unlock shares one anonymous login for concurrent calls and persists session',async()=>{
 const h=harness(url=>url.includes('/auth/')?[200,session]:[200,true]);await Promise.all([h.store.unlock('energy'),h.store.unlock('energy')]);
 assert.equal(h.calls.filter(c=>c.url.includes('/auth/')).length,1);assert.equal(h.values.size,1);assert.equal(JSON.parse(h.calls.at(-1).opts.body).p_key,'energy');
});
test('save uses expected version and propagates conflicts without overwriting or retry',async()=>{
 const h=harness(()=>[409,{message:'edit_conflict'}]);h.store.session=session;
 await assert.rejects(h.store.save('20261104',2,3,{schema:1,reset:true}),e=>e.status===409);
 assert.equal(h.calls.length,1);assert.deepEqual(JSON.parse(h.calls[0].opts.body),{p_day:'2026-11-04',p_page:2,p_expected_version:3,p_payload:{schema:1,reset:true}});
});
test('refresh network errors preserve anonymous identity',async()=>{
 const h=harness(()=>[503,{message:'offline'}]);h.store.session={...session,expires_at:0};await assert.rejects(h.store.authenticate());assert.equal(h.calls.length,1);assert.match(h.calls[0].url,/refresh_token/);
});
test('expired session refreshes and does not create a new account',async()=>{
 const h=harness(()=>[200,session]);h.store.session={...session,expires_at:0};await h.store.authenticate();assert.equal(h.calls.length,1);assert.match(h.calls[0].url,/refresh_token/);
});
test('images reject SVG and oversized files; identical content uses stable non-overwriting path',async()=>{
 const h=harness(()=>[200,{Key:'ok'}]);h.store.session=session;
 await assert.rejects(h.store.upload('20261104',new Blob(['svg'],{type:'image/svg+xml'})));
 await assert.rejects(h.store.upload('20261104',new Blob([new Uint8Array(2097153)],{type:'image/png'})));
 const blob=new Blob(['PNG'],{type:'image/png'}),a=await h.store.upload('20261104',blob),b=await h.store.upload('20261104',blob);assert.equal(a,b);assert.equal(h.calls.length,2);assert.equal(h.calls[0].opts.headers['x-upsert'],'false');
});
