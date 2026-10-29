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


const overview=require('../site/overview.js');
const cityNames=['서울','인천','수원','원주','강릉','대전','청주','전주','광주','대구','부산','제주'];
const common=source.slice(source.indexOf('const DISPLAY_CITIES ='),source.indexOf('let MF ='));
function legacyContext(extra={}) {
  const ctx={window:{WeatherOverview:overview},...extra};vm.createContext(ctx);vm.runInContext(common,ctx);return ctx;
}
test('shared city order and same-valid-time forecast error never borrow another index',()=>{
  const ctx=legacyContext();
  assert.deepEqual(Array.from(vm.runInContext('CITY_ORDER',ctx)),cityNames);
  assert.equal(ctx.matchedTemperature([null,12],[10,null],0),null);
  assert.equal(ctx.matchedTemperature([null,12],[10,null],1),null);
  assert.equal(ctx.matchedTemperature([0,-1],[0,1],0),0);
  assert.equal(ctx.matchedTemperature([0,-1],[0,1],1),-2);
  assert.equal(ctx.observationAt({108:[4,null],119:[1,0]},108,1),null);
  assert.equal(ctx.observationAt({108:[4,null],119:[1,0]},119,1),0);
  assert.equal(ctx.observationAt({108:[4]},112,0),null);
});
test('forecast-observation renders all twelve city charts from only selected issue and matching indices',()=>{
  const els={issueSelK:{value:'2026102905'},dateSelK:{value:'20261029'},kmafCharts:{}};
  const panels=[];let hover;
  const ctx=legacyContext({$:id=>els[id],KMAF:{data:{t0:'2026102900',hours:48,cities:['서울'],
    fcst:{2026102905:{서울:[null,12]},2026102823:{원주:[99,99]}},obs:{서울:[10,null]}}},
    drawPanel:o=>{panels.push(o);return '<svg></svg>';},bindHover:(_id,fn)=>hover=fn,fmtWhen:x=>x,
    keyToMs:k=>Date.UTC(+k.slice(0,4),+k.slice(4,6)-1,+k.slice(6,8),+k.slice(8))-9*3600e3});
  vm.runInContext(source.slice(source.indexOf('function renderKmaf()'),source.indexOf('// ── 예보 변화')),ctx);
  ctx.renderKmaf();
  assert.deepEqual(panels.map(p=>p.title),cityNames);
  assert.match(panels.find(p=>p.title==='강릉').titleLabel,/참조/);
  assert.match(panels.find(p=>p.title==='원주').titleLabel,/자료 없음/);
  assert.equal(panels.find(p=>p.title==='원주').series[0].data,undefined);
  assert.equal(hover('서울',0).rows.length,2);assert.equal(hover('서울',1).rows.length,2);
});
test('observation twelve-city summary uses one global hour and explicitly shows missing stations',()=>{
  const els={obsLabel:{},obsSlider:{},obsMap:{}};
  const ctx=legacyContext({$:id=>els[id],isAnom:()=>false,obsHours:()=>[0,1],fmtDate:d=>d,
    obsEpoch:()=>0,relNow:()=>'',obsBins:()=>({colors:['#fff'],edges:[0,1],step:1}),
    lerpColor:()=> '#ffffff',obsColor:v=>v==null?null:'#ffffff',bindDotHover:()=>{},
    obsState:{date:'20261029',v:'ta',idx:1,base:{w:760,h:760,paths:{admin:'',coast:''}},
      meta:{scales:{ta:{label:'기온',unit:'℃',vmin:0,vmax:30}},stations:overview.CITIES.map(c=>({s:c.stn,n:c.name,x:0,y:0,L:0}))},
      data:{vars:{ta:{108:[4,null],119:[3,0],112:[5,1]}}}}});
  vm.runInContext(source.slice(source.indexOf('function renderObs()'),source.indexOf('$("obsSlider").oninput')),ctx);
  ctx.renderObs();const html=els.obsMap.innerHTML;
  const rows=[...html.matchAll(/<tr><th>([^<]+)<\/th><td>([^<]+)<\/td><td>([^<]+)<\/td><\/tr>/g)];
  assert.deepEqual(rows.map(r=>r[1].replace(' · 참조','')),cityNames);
  assert.equal(rows[0][2],'자료 없음');assert.equal(rows[2][2],'0.0℃');
  assert.ok(rows.every(r=>r[3]==='20261029 01시 KST'));
  assert.match(html,/강릉 · 참조/);assert.doesNotMatch(html,/>4.0℃</);
});
test('medium history remains opt-in, with all twelve cities in the shared list',()=>{
  assert.match(source,/const MID_CITIES = CITY_ORDER/);
  assert.match(source,/const prevIss = \$\("midHistory"\)\?\.checked \?/);
  assert.match(source,/\$\("midHistory"\)\.onchange = renderMid/);
});


test('verification keeps all twelve city placeholders and existing model rows',async()=>{
  const els={dateSelV:{value:'20261029'},verifDailyT:{},verifDailyC:{},verifDailyS:{},verifDailySH:{}};
  const ctx=legacyContext({$:id=>els[id],fetchJSON:async()=>({t2m:{서울:{obs:{0:0},models:{ECMWF:{0:[1,1]},GFS:{0:[-1,-1]}}}}})});
  vm.runInContext(source.slice(source.indexOf('async function renderVerifDaily()'),source.indexOf('// ── 검증 탭 ──')),ctx);
  await ctx.renderVerifDaily();const html=els.verifDailyT.innerHTML;
  assert.equal((html.match(/class="city-sep"/g)||[]).length,12);
  assert.match(html,/청주 관측 · 자료 없음/);assert.match(html,/강릉 · 참조 관측/);
  assert.match(html,/ECMWF/);assert.match(html,/GFS/);
});


test('legacy tabs retain canonical twelve-city metadata when optional overview script is unavailable',()=>{
  const ctx=legacyContext({window:{}});
  assert.deepEqual(Array.from(vm.runInContext('CITY_ORDER',ctx)),cityNames);
  assert.deepEqual(Array.from(vm.runInContext('DISPLAY_CITIES.map(c=>c.stn)',ctx)),overview.CITIES.map(c=>c.stn));
  assert.equal(ctx.window.WeatherCities.length,12);
});
