const test=require('node:test');
const assert=require('node:assert/strict');
const {CITIES,latestPair,hours,record,compare,summary,emoji,currentKey,latestObservation}=require('../site/overview.js');
const wx=(key='clear|',label='맑음',code='clear')=>({key,label,code});
const entry=(issue,kind='short',cities=['서울'])=>({issue,kind,cities,file:`issues/${issue}-${kind}.json`});
const doc=(issue,city,hour,value)=>({issue,kind:'short',cities:{[city]:{[hour.slice(0,8)]:{hourly:{[hour]:value}}}}});
test('latest pair is two distinct stored short issues, not yesterday/scheduled/city fallback',()=>{
 const result=latestPair([entry('2026102517'),entry('2026102611','mid'),entry('2026102605'),entry('2026102523'),entry('2026102605')]);
 assert.equal(result.latest.issue,'2026102605');assert.equal(result.previous.issue,'2026102523');
 assert.equal(latestPair([entry('2026102605')]).previous,null);
 assert.equal(latestPair([]).latest,null);
});
test('hourly axis sorted unique and never fabricated; no issue-time or past-issue target',()=>{
 const d=doc('2026102605','서울','2026102606',{temp:0});
 d.cities.원주={'20261026':{hourly:{'2026102606':{temp:4},'2026102607':{temp:5},'2026102604':{temp:7},invalid:{temp:8}}}};
 assert.deepEqual(hours(d),['2026102606','2026102607']);assert.deepEqual(hours(null),[]);
});
test('exact city and valid time: Wonju never borrows Gangneung or another hour',()=>{
 const d=doc('2026102605','강릉','2026102606',{temp:8,wx:wx()});
 assert.equal(record(d,'원주','2026102606'),null);
 assert.equal(record(d,'강릉','2026102607'),null);
 assert.equal(record(d,'강릉','2026102606').temp,8);
});
test('first real Wonju reception displays but has no made-up previous delta',()=>{
 const b=doc('2026102605','원주','2026102606',{temp:0,wx:wx()});
 const a=doc('2026102523','강릉','2026102606',{temp:9,wx:wx()});
 assert.deepEqual(compare(record(a,'원주','2026102606'),record(b,'원주','2026102606')),{delta:null,changed:null});
 const s=summary(b,a,'2026102606');assert.equal(s.tempCount,0);assert.equal(s.min,null);assert.equal(s.skyCount,0);
});
test('zero/negative temperatures and independent missing weather remain correct',()=>{
 assert.deepEqual(compare({temp:0,wx:wx()},{temp:-1.2,wx:wx()}),{delta:-1.2,changed:false});
 assert.deepEqual(compare({temp:null,wx:wx()},{temp:0,wx:wx('overcast|','흐림','overcast')}),{delta:null,changed:true});
 assert.deepEqual(compare({temp:NaN},{temp:0}),{delta:null,changed:null});
 assert.deepEqual(compare({temp:1,pop:0,wx:wx()},{temp:1,pop:10,wx:wx()}),{delta:0,changed:false});
});
test('summary includes Wonju, excludes Gangneung reference, counts each available metric separately',()=>{
 const t='2026102606',a=doc('2026102523','원주',t,{temp:1,wx:wx()}),b=doc('2026102605','원주',t,{temp:3,wx:wx('overcast|','흐림','overcast')});
 a.cities.강릉=doc(a.issue,'강릉',t,{temp:-50,wx:wx()}).cities.강릉;
 b.cities.강릉=doc(b.issue,'강릉',t,{temp:50,wx:wx('rain|비','비','rain')}).cities.강릉;
 assert.deepEqual(summary(b,a,t),{min:2,max:2,tempCount:1,skyCount:1,changed:1});
 assert.equal(CITIES.filter(c=>!c.reference).length,8);
 assert.equal(CITIES.find(c=>c.name==='원주').stn,114);
});
test('weather icons retain snow/mixed/shower types and missing is not cloudy',()=>{
 assert.equal(emoji(null),'—');assert.equal(emoji(wx('x','흐림 · 눈','rain')),'❄️');
 assert.equal(emoji(wx('x','흐림 · 비/눈','rain')),'🌨️');assert.equal(emoji(wx('x','소나기','rain')),'🌦️');
});
test('KST clock is timezone independent and latest observation handles 0 without borrowing stations',()=>{
 assert.equal(currentKey(Date.UTC(2026,9,25,15,30)),'2026102600');
 assert.deepEqual(latestObservation({vars:{ta:{114:[4,null,0,null]}}},114),{temp:0,hour:'02'});
 assert.equal(latestObservation({vars:{ta:{105:[4]}}},114),null);
});
test('production source contains no frozen prototype snapshot or removed STRIP_ORDER dependency',()=>{
 const fs=require('node:fs');const source=fs.readFileSync('site/overview.js','utf8');
 assert.ok(source.includes('forecast_compare/index.json'));assert.ok(!source.includes('const DATA='));
 assert.ok(!fs.readFileSync('site/app.js','utf8').includes('STRIP_ORDER'));
 const html=fs.readFileSync('site/index.html','utf8');assert.ok(html.indexOf('overview.js')<html.indexOf('app.js'));
});
test('mounted overview supports repeated navigation, city choice, weather mode, failed previous and retry',async()=>{
 const fs=require('node:fs'),vm=require('node:vm');
 const els={};
 class Element {
  constructor(){this.attributes={};this.dataset={};this.value='';}
  setAttribute(k,v){this.attributes[k]=v;}
  set innerHTML(v){this.html=v;this.markers=[...v.matchAll(/data-city="([^"]+)"/g)].map(m=>{const e=new Element();e.dataset.city=m[1];return e;});}
  get innerHTML(){return this.html||'';}
  querySelectorAll(){return els['ov-markers']?.markers||[];}
  querySelector(){return {focus(){}};}
 }
 const document={getElementById:id=>els[id]||(els[id]=new Element())};
 const a=doc('2026102523','원주','2026102606',{temp:0,wx:wx(),pop:0});
 const b=doc('2026102605','원주','2026102606',{temp:1,wx:wx(),pop:10});
 b.cities.원주['20261026'].hourly['2026102607']={temp:2,wx:wx(),pop:20};
 const idx={issues:[entry(a.issue),entry(b.issue)]};let failPrevious=true,failIndex=false;
 const FixedDate=class extends Date {static now(){return Date.UTC(2026,9,25,21);}};
 const context={window:{document},document,console,Date:FixedDate,fetch:async url=>{
  if(failIndex || failPrevious&&url.includes(a.issue)) return {ok:false,status:503};
  return {ok:true,json:async()=>url.includes('index.json')?idx:url.includes(a.issue)?a:b};
 }};
 vm.runInNewContext(fs.readFileSync('site/overview.js','utf8'),context);
 const mount=context.window.WeatherOverview.mount;
 await mount({});
 assert.equal(els.weatherOverview.attributes['aria-busy'],'false');
 assert.match(els.weatherOverview.innerHTML,/직전 발표 수신 실패/);
 assert.match(els['ov-detail'].innerHTML,/비교 불가/);
 els['ov-prev'].onclick();assert.match(els['ov-selected-time'].textContent,/06:00/);
 els['ov-next'].onclick();els['ov-next'].onclick();assert.match(els['ov-selected-time'].textContent,/07:00/);
 els['ov-slider'].oninput({target:{value:'0'}});assert.match(els['ov-selected-time'].textContent,/06:00/);
 els['ov-weather'].onclick();assert.equal(els['ov-weather'].attributes['aria-pressed'],true);
 assert.match(els['ov-markers'].innerHTML,/맑음<\/text>/);
 const gangneung=els['ov-markers'].markers.find(e=>e.dataset.city==='강릉');gangneung.onclick();
 assert.match(els['ov-detail'].innerHTML,/참조 도시 · 요약 제외/);
 failPrevious=false;await els['ov-retry'].onclick();
 assert.match(els['ov-detail'].innerHTML,/\+1°/);
 failIndex=true;await els['ov-retry'].onclick();assert.match(els.weatherOverview.innerHTML,/표시할 수 없습니다/);
 failIndex=false;await els['ov-retry'].onclick();assert.match(els.weatherOverview.innerHTML,/전국 예보 지도/);
});
