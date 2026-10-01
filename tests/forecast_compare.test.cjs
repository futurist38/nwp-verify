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

test('screen controls render four real series, change periods, swap, and recover from fetch failure',async()=>{
  const fs=require('fs'),vm=require('vm');
  class Element {
    constructor(){this.value='';this.attributes={};this.buttons=[];this.classList={contains:()=>true};}
    set innerHTML(value){this.html=value;const values=[...value.matchAll(/<option value="([^"]+)"/g)].map(m=>m[1]);if(values.length)this.value=values[0];this.buttons=[...value.matchAll(/data-day="([^"]+)"/g)].map(m=>{const e=new Element();e.dataset={day:m[1]};return e;});}
    get innerHTML(){return this.html||'';}
    setAttribute(k,v){this.attributes[k]=v;}
    querySelectorAll(){return this.buttons;}
    addEventListener(){}
  }
  const ids=[...fs.readFileSync(require.resolve('../site/index.html'),'utf8').matchAll(/id="(fc-[^"]+)"/g)].map(m=>m[1]);
  const elements=Object.fromEntries(ids.map(id=>[id,new Element()]));
  const tab=new Element(),nav=new Element();
  const document={getElementById:id=>id==='tab-compare'?tab:elements[id]||(elements[id]=new Element()),querySelector:()=>nav,querySelectorAll:()=>elements['fc-timeline'].buttons};
  const doc=(issue,value,code)=>({schema:1,issue,kind:'short',cities:{서울:Object.fromEntries(['20261002','20261003'].map(day=>[day,{tmax:{value,basis:'TMX'},tmin:{value:value-10,basis:'TMN'},wx_am:wx(code),wx_pm:wx(code)}]))}});
  const data={'2026093017-short':doc('2026093017',25,'clear'),'2026100117-short':doc('2026100117',23,'overcast'),'2026092517-short':doc('2026092517',21,'partly')};
  const idx={schema:1,issues:Object.values(data).map(d=>({...entry(d.issue,'short'),file:d.issue+'-short',rev:'1'}))};
  let fail=true;
  const fetch=async url=>{if(url.includes('2026092517')&&fail)return {ok:false,status:503};return {ok:true,json:async()=>url.includes('index.json')?idx:data[url.split('/').at(-1).split('?')[0]]};};
  const sandbox={document,fetch,console,Date,Map,Set,URLSearchParams};sandbox.window={document};
  vm.runInNewContext(fs.readFileSync(require.resolve('../site/forecast-compare.js'),'utf8'),sandbox);
  const settle=()=>new Promise(resolve=>setImmediate(resolve));await settle();await settle();
  let html=elements['fc-timeline'].innerHTML;
  assert.equal((html.match(/data-series=/g)||[]).length,4);
  assert.ok(!html.includes('NaN'));assert.match(html,/#cbd0d6/);
  elements['fc-start'].value='20261003';elements['fc-start'].onchange();
  assert.equal(elements['fc-timeline'].buttons.length,1);
  elements['fc-swap'].onclick();await settle();
  assert.match(elements['fc-timeline'].innerHTML,/#fff6d5/);
  elements['fc-a-date'].value='20260925';elements['fc-a-date'].onchange();await settle();
  assert.equal(elements['fc-timeline'].innerHTML,'');assert.match(elements['fc-status'].innerHTML,/다시 시도/);
  fail=false;elements['fc-retry'].onclick();await settle();
  assert.equal((elements['fc-timeline'].innerHTML.match(/data-series=/g)||[]).length,4);
});
