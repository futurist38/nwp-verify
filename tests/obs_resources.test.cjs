const test=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),vm=require('vm');
const source=fs.readFileSync('site/app.js','utf8');
const fn=source.slice(source.indexOf('async function ensureObsResources()'),source.indexOf('async function renderFd()'));
test('map initialization waits for missing geography even when station metadata already exists',async()=>{
 const obsState={meta:{stations:[]}},calls=[];let resolve;
 const ctx={obsState,fetchJSON:url=>{calls.push(url);return new Promise(r=>resolve=r);}};
 vm.createContext(ctx);vm.runInContext(fn,ctx);let ready=false;
 const pending=ctx.ensureObsResources().then(()=>ready=true);await Promise.resolve();
 assert.equal(ready,false);assert.deepEqual(calls,['basemap.json']);resolve({w:760});await pending;
 assert.equal(obsState.base.w,760);await ctx.ensureObsResources();assert.equal(calls.length,1);
 assert.equal((source.match(/await ensureObsResources\(\)/g)||[]).length,2);
});
test('failed map resource remains retryable without discarding completed station metadata',async()=>{
 const obsState={meta:{stations:[]}};let fail=true;
 const ctx={obsState,fetchJSON:async()=>{if(fail)throw Error('offline');return {w:760};}};
 vm.createContext(ctx);vm.runInContext(fn,ctx);await assert.rejects(ctx.ensureObsResources(),/offline/);
 fail=false;await ctx.ensureObsResources();assert.equal(obsState.base.w,760);
});
