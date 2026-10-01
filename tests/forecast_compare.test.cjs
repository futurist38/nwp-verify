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
  assert.deepEqual(fc.selectEntries(entries,'2026100118','수원'),[]);
});
test('new medium weather does not hide the latest available medium temperature',()=>{
  const entries=[entry('2026100106','mid'),entry('2026100118','mid',['서울'],[],['서울'])];
  assert.equal(fc.selectEntries(entries,'2026100118','서울').length,2);
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
  assert.equal(data['20261002'].tmin.kind,'mid');
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
  const sandbox={document,fetch,console,Date,Map,Set,URLSearchParams};sandbox.window={document};
  vm.runInNewContext(fs.readFileSync(require.resolve('../site/forecast-compare.js'),'utf8'),sandbox);
  const settle=()=>new Promise(resolve=>setImmediate(resolve));await settle();await settle();
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
});
