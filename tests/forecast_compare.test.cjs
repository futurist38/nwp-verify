const {test}=require('node:test');
const assert=require('node:assert/strict');
const fc=require('../site/forecast-compare.js');
const wx=(code,key=code+'|')=>({code,key,label:code});
const rec=(am,pm)=>({wx:{am,pm}});
const entry=(issue,kind,cities=['서울'],temp=cities,weather=cities)=>({issue,kind,cities,temperature_cities:temp,weather_cities:weather,file:issue+'-'+kind});

test('cutoff never selects a future issue, products remain independent',()=>{
  const entries=[entry('2026100105','short'),entry('2026100106','mid'),entry('2026100111','short'),entry('2026100118','mid')];
  assert.deepEqual(fc.selectEntries(entries,'2026100111','서울').map(e=>e.issue),['2026100111','2026100106']);
  assert.deepEqual(fc.selectEntries(entries,'2026092518','서울'),[]);
  assert.deepEqual(fc.selectEntries(entries,'2026100118','수원').map(e=>e.issue),['2026100111','2026100118']);
});
test('missing medium temperature stays missing rather than loading an older temperature issue',()=>{
  const entries=[entry('2026100106','mid'),entry('2026100118','mid',['서울'],[],['서울'])];
  const selected=fc.selectEntries(entries,'2026100118','서울');
  assert.equal(selected.length,1);assert.equal(selected[0].issue,'2026100118');
});
test('same weather is white; only changed half takes the resulting color',()=>{
  const a=rec(wx('clear'),wx('partly')),b=rec(wx('clear'),wx('overcast'));
  assert.deepEqual(fc.compareWeather(a,b).map(s=>s.color),['#ffffff','#cbd0d6']);
  for(const code of ['clear','partly','overcast','rain']) {
    const s=fc.compareWeather(rec(wx('partly','different'),null),rec(wx(code),null))[0];
    assert.equal(s.color,fc.COLORS[code]);
  }
});
test('unknown and resolution mismatch must not count as maintained or changed',()=>{
  assert.equal(fc.compareWeather(rec(null,null),rec(wx('clear'),null))[0].state,'missing');
  assert.equal(fc.compareWeather({wx:{day:wx('clear')}},rec(wx('clear'),wx('clear')))[0].state,'resolution');
  assert.equal(fc.compareWeather({wx:{day:wx('clear')}},{wx:{day:wx('clear')}})[0].color,'#ffffff');
});
test('temperature deltas do not turn missing values into zero',()=>{
  assert.equal(fc.delta(null,{value:12}),null);
  assert.equal(fc.delta({value:0},{value:-1.2}),-1.2);
  assert.equal(fc.delta({value:10},{value:10}),0);
});
test('short-to-medium transition preserves actual sources and missing half days',()=>{
  const docs=[{issue:'2026100105',kind:'short',cities:{서울:{20261002:{tmax:{value:25,basis:'TMX'},wx_pm:wx('clear')}}}},
    {issue:'2026100106',kind:'mid',cities:{서울:{20261002:{tmin:{value:12,basis:'MID'},wx_day:wx('overcast')},20261005:{tmax:{value:23,basis:'MID'}}}}}];
  const data=fc.assemble(docs,'서울');
  assert.equal(data['20261002'].tmax.issue,'2026100105');
  assert.equal(data['20261002'].tmin,null);
  assert.equal(data['20261002'].wx.am,null);
  assert.equal(data['20261002'].wx.day,null);
  assert.equal(data['20261005'].tmax.kind,'mid');
});
test('last Friday handles Friday itself and date ranges cross month correctly',()=>{
  assert.equal(fc.lastFriday('20261001'),'20260925');
  assert.equal(fc.lastFriday('20261002'),'20260925');
  assert.deepEqual(fc.range('20260930','20261002'),['20260930','20261001','20261002']);
});

test('medium bounds reject absent, inverted, and short-range pseudo intervals',()=>{
  assert.deepEqual(fc.bounds({basis:'MID',value:-2,lower:-4,upper:1}),{lower:-4,upper:1});
  assert.deepEqual(fc.bounds({basis:'MID',value:20,lower:20,upper:20}),{lower:20,upper:20});
  for(const r of [{basis:'MID',value:20,lower:null,upper:21},{basis:'MID',value:20,lower:21,upper:22},{basis:'TMX',value:20,lower:18,upper:22}])assert.equal(fc.bounds(r),null);
});
test('hourly alignment preserves one-sided data, midnight, gaps, and real issue provenance',()=>{
  const d={issue:'2026100117',kind:'short',cities:{서울:{20261002:{hourly:{2026100200:{temp:0,wx:wx('clear'),pop:0},2026100202:{temp:2}}},20261003:{hourly:{2026100300:{temp:3}}}}}};
  const a=fc.assemble([d],'서울');
  assert.equal(a['20261002'].hourly['2026100200'].issue,'2026100117');
  assert.equal(a['20261002'].hourly['2026100200'].wx.issue,'2026100117');
  const slots=fc.hourlySlots(a,{},['20261002','20261003']);
  assert.equal(slots.length,48);assert.equal(slots[24].key,'2026100300');
  assert.equal(slots[0].a.temp,0);assert.equal(slots[0].b,null);assert.equal(slots[1].a,null);
  assert.equal(fc.hourlyPath(slots,'a',i=>i,v=>v),'M0,0 M2,2 M24,3 ');
  assert.equal(fc.hourlyPath(slots,'b',i=>i,v=>v),'');
  const mid=fc.assemble([{issue:'2026100106',kind:'mid',cities:{서울:{20261002:{tmax:{value:23,basis:'MID'}}}}}],'서울');
  assert.equal(fc.hourlySlots(mid,{},['20261002']).some(h=>h.a),false);
});

test('screen controls render four real series, change periods, swap, and recover from fetch failure',async()=>{
  const fs=require('fs'),vm=require('vm');
  class Element {
    constructor(){this.value='';this.attributes={};this.buttons=[];this.classList={contains:()=>true};}
    set innerHTML(value){this.html=value;const values=[...value.matchAll(/<option value="([^"]+)"/g)].map(m=>m[1]);if(values.length)this.value=values[0];this.buttons=[...value.matchAll(/data-(day|hour)="([^"]+)"/g)].map(m=>{const e=new Element();e.dataset={[m[1]]:m[2]};return e;});}
    get innerHTML(){return this.html||'';}
    setAttribute(k,v){this.attributes[k]=v;}
    querySelectorAll(){return this.buttons;}
    addEventListener(){}
  }
  const ids=[...fs.readFileSync(require.resolve('../site/index.html'),'utf8').matchAll(/id="(fc-[^"]+)"/g)].map(m=>m[1]);
  const elements=Object.fromEntries(ids.map(id=>[id,new Element()]));
  const tab=new Element(),nav=new Element();
  const document={getElementById:id=>id==='tab-compare'?tab:elements[id]||(elements[id]=new Element()),querySelector:()=>nav,querySelectorAll:()=>elements['fc-timeline'].buttons};
  const doc=(issue,value,code)=>({schema:1,issue,kind:'short',cities:{서울:Object.fromEntries(['20261002','20261003'].map(day=>[day,{tmax:{value,basis:'TMX'},tmin:{value:value-10,basis:'TMN'},wx_am:wx(code),wx_pm:wx(code),hourly:{[day+'12']:{temp:value,wx:wx(code),pop:20}}}]))}});
  const data={'2026093017-short':doc('2026093017',25,'clear'),'2026100117-short':doc('2026100117',23,'overcast'),'2026092517-short':doc('2026092517',21,'partly')};
  for(const issue of ['2026093018','2026100118'])data[issue+'-mid']={schema:1,issue,kind:'mid',cities:{서울:{20261004:{
    tmax:{value:23,basis:'MID',lower:21,upper:32},tmin:{value:13,basis:'MID',lower:11,upper:14},wx_am:wx('clear'),wx_pm:wx('clear')
  }}}};
  const idx={schema:1,issues:Object.values(data).map(d=>({...entry(d.issue,d.kind),file:d.issue+'-'+d.kind,rev:'1'}))};
  let fail=true;
  const fetch=async url=>{if(url.includes('2026092517')&&fail)return {ok:false,status:503};return {ok:true,json:async()=>url.includes('index.json')?idx:data[url.split('/').at(-1).split('?')[0]]};};
  const sandbox={document,fetch,console,Date,Map,Set,URLSearchParams};sandbox.window={document}; // Optional Today script failed to load; this tab remains usable.
  vm.runInNewContext(fs.readFileSync(require.resolve('../site/forecast-compare.js'),'utf8'),sandbox);
  const settle=()=>new Promise(resolve=>setImmediate(resolve));await settle();await settle();
  // Default is the immediately previous stored short issue, not a calendar-day fallback.
  assert.equal(elements['fc-a-date'].value,'20260930');
  assert.equal(elements['fc-a-time'].value,'17');
  assert.equal(elements['fc-b-date'].value,'20261001');
  assert.equal(elements['fc-b-time'].value,'17');
  // Explicit historical controls still support the medium-issue cutoff.
  elements['fc-a-time'].value='18';elements['fc-a-time'].onchange();await settle();
  elements['fc-b-time'].value='18';elements['fc-b-time'].onchange();await settle();
  let html=elements['fc-timeline'].innerHTML;
  assert.equal((html.match(/data-series=/g)||[]).length,4);
  assert.ok(!html.includes('NaN'));assert.match(html,/#cbd0d6/);
  assert.equal((html.match(/data-range=/g)||[]).length,4);
  assert.equal((html.match(/data-range-band=/g)||[]).length,4);
  assert.match(html,/>35<\/text>/); // Axis includes the official upper bound.
  elements['fc-ranges'].checked=false;elements['fc-ranges'].onchange();
  assert.doesNotMatch(elements['fc-timeline'].innerHTML,/data-range=/);
  assert.doesNotMatch(elements['fc-timeline'].innerHTML,/>35<\/text>/);
  elements['fc-ranges'].checked=true;elements['fc-ranges'].onchange();
  elements['fc-timeline'].buttons[2].onclick();
  assert.match(elements['fc-detail'].innerHTML,/예보 범위 21~32℃/);
  assert.match(elements['fc-hourly-plot'].innerHTML,/저장된 시간별 예보가 없습니다/);
  elements['fc-timeline'].buttons[0].onclick();
  assert.equal((elements['fc-hourly-plot'].innerHTML.match(/data-hour-series=/g)||[]).length,2);
  assert.equal(elements['fc-hourly-plot'].buttons.length,24);
  elements['fc-hourly-plot'].buttons[12].onclick();
  assert.match(elements['fc-hourly-detail'].innerHTML,/25℃ → 23℃/);
  elements['fc-hourly-day'].value='all';elements['fc-hourly-day'].onchange();
  assert.equal(elements['fc-hourly-plot'].buttons.length,48);
  elements['fc-end'].value='20261003';elements['fc-end'].onchange();
  elements['fc-start'].value='20261003';elements['fc-start'].onchange();
  assert.equal(elements['fc-timeline'].buttons.length,1);
  elements['fc-swap'].onclick();await settle();
  assert.match(elements['fc-timeline'].innerHTML,/#fff6d5/);
  elements['fc-a-date'].value='20260925';elements['fc-a-date'].onchange();await settle();
  assert.equal(elements['fc-timeline'].innerHTML,'');assert.match(elements['fc-status'].innerHTML,/다시 시도/);
  assert.equal(elements['fc-hourly'].hidden,true);
  fail=false;elements['fc-retry'].onclick();await settle();
  assert.equal((elements['fc-timeline'].innerHTML.match(/data-series=/g)||[]).length,4);
  assert.deepEqual([...elements['fc-city'].innerHTML.matchAll(/option value="([^"]+)"/g)].map(m=>m[1]), ['서울','인천','수원','원주','강릉','대전','청주','전주','광주','대구','부산','제주']);
  assert.match(elements['fc-city'].innerHTML,/강릉 · 참조/);
  elements['fc-city'].value='원주';elements['fc-city'].onchange();await settle();
  assert.equal(elements['fc-timeline'].innerHTML,'');
  assert.match(elements['fc-status'].textContent,/자료|없/);
  elements['fc-city'].value='서울';elements['fc-city'].onchange();await settle();
  assert.equal((elements['fc-timeline'].innerHTML.match(/data-series=/g)||[]).length,4);
});


test('globally latest issue never falls back by city, metric, date, or hour',()=>{
  const old={issue:'2026100105',kind:'short',cities:{서울:{20261002:{tmax:{value:99},hourly:{2026100200:{temp:99},2026100201:{temp:98}}}},원주:{20261002:{tmax:{value:97}}}}};
  const latest={issue:'2026100111',kind:'short',cities:{서울:{20261002:{tmin:{value:0},hourly:{2026100200:{temp:0}}}}}};
  const mid={issue:'2026100106',kind:'mid',cities:{서울:{20261002:{tmax:{value:88}},20261004:{tmax:{value:12}}},원주:{20261002:{tmax:{value:87}}}}};
  const index=[entry(old.issue,'short',['서울','원주']),entry(latest.issue,'short',['서울']),entry(mid.issue,'mid',['서울','원주'])];
  assert.equal(fc.selectEntries(index,latest.issue,'원주')[0].issue,latest.issue);
  assert.deepEqual(fc.assemble([old,latest,mid],'원주'),{});
  const got=fc.assemble([old,latest,mid],'서울');
  assert.equal(got['20261002'].tmax,null);assert.equal(got['20261002'].tmin.value,0);
  assert.equal(got['20261002'].hourly['2026100200'].temp,0);
  assert.equal(got['20261002'].hourly['2026100201'],undefined);
  assert.equal(got['20261004'].tmax.issue,mid.issue);
  // An explicit earlier cutoff still reads the actual archived issue.
  assert.equal(fc.selectEntries(index,old.issue,'원주')[0].issue,old.issue);
});


test('default baseline is adjacent distinct short issues, never an unrelated mid issue',()=>{
  assert.deepEqual(fc.defaultPair([entry('2026102905','short'),entry('2026102823','short'),entry('2026102906','mid')]),{latest:'2026102905',previous:'2026102823'});
  assert.deepEqual(fc.defaultPair([entry('2026102905','short'),entry('2026102823','mid')]),{latest:'2026102905',previous:null});
  assert.deepEqual(fc.defaultPair([]),{latest:null,previous:null});
});
test('comparison retains all cities and correct default without optional overview script',()=>{
  assert.deepEqual(fc.CITIES.map(c=>c.name),require('../site/overview.js').CITIES.map(c=>c.name));
  assert.deepEqual(fc.CITIES.map(c=>c.stn),require('../site/overview.js').CITIES.map(c=>c.stn));
});
