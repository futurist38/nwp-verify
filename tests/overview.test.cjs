const test=require('node:test');
const assert=require('node:assert/strict');
const {CITIES,latestPair,hours,record,compare,summary,emoji,currentKey,latestObservation,observationHour,forecastObservation,mapLayout,POINTS}=require('../site/overview.js');
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
 assert.equal(CITIES.filter(c=>!c.reference).length,11);
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
  constructor(){this.attributes={};this.dataset={};this.value='';this.style={};this.clientWidth=800;this.clientHeight=760;}
  focus(){}
  setAttribute(k,v){this.attributes[k]=v;}
  set innerHTML(v){this.html=v;this.markers=[...v.matchAll(/data-city="([^"]+)"/g)].map(m=>{const e=new Element();e.dataset.city=m[1];return e;});}
  get innerHTML(){return this.html||'';}
  querySelectorAll(){return els['ov-markers']?.markers||[];}
  querySelector(s){return els['ov-markers']?.markers.find(e=>s.includes(e.dataset.city))||{focus(){}};}
 }
 const document={getElementById:id=>els[id]||(els[id]=new Element())};
 const a=doc('2026102523','원주','2026102606',{temp:0,wx:wx(),pop:0});
 const b=doc('2026102605','원주','2026102606',{temp:1,wx:wx(),pop:10});
 b.cities.원주['20261026'].hourly['2026102607']={temp:2,wx:wx(),pop:20};
 const idx={issues:[entry(a.issue),entry(b.issue)]};let failPrevious=true,failIndex=false;
 const FixedDate=class extends Date {static now(){return Date.UTC(2026,9,25,21);}};
 const listeners={},win={document,innerWidth:960,matchMedia:()=>({matches:win.innerWidth<=700}),addEventListener:(name,fn)=>{listeners[name]=fn;},removeEventListener:(name,fn)=>{if(listeners[name]===fn)delete listeners[name];}};
 const context={window:win,document,console,Date:FixedDate,fetch:async url=>{
  if(failIndex || failPrevious&&url.includes(a.issue)) return {ok:false,status:503};
  return {ok:true,json:async()=>url.includes('index.json')?idx:url.includes(a.issue)?a:b};
 }};
 vm.runInNewContext(fs.readFileSync('site/overview.js','utf8'),context);
 const mount=context.window.WeatherOverview.mount;
 await mount({});
 assert.equal(els.weatherOverview.attributes['aria-busy'],'false');
 assert.equal(els['ov-map'].attributes['data-layout'],'geographic');
 assert.equal(els['ov-markers'].markers.length,12);
 const before=els['ov-markers'].markers.map(e=>({...e.style}));
 win.innerWidth=390;els['ov-map'].clientWidth=360;els['ov-map'].clientHeight=720;listeners.resize();
 assert.equal(els['ov-map'].attributes['data-layout'],'lanes');assert.equal(new Set(els['ov-markers'].markers.map(e=>e.style.left)).size,2);
 win.innerWidth=960;els['ov-map'].clientWidth=800;els['ov-map'].clientHeight=760;listeners.resize();
 assert.equal(els['ov-map'].attributes['data-layout'],'geographic');assert.deepEqual(els['ov-markers'].markers.map(e=>({...e.style})),before);
 for(const name of CITIES.map(c=>c.name)){els['ov-markers'].markers.find(e=>e.dataset.city===name).onclick();assert.match(els['ov-detail'].innerHTML,new RegExp(name));}
 els['ov-markers'].markers.find(e=>e.dataset.city==='원주').onclick();
 assert.match(els.weatherOverview.innerHTML,/직전 발표 수신 실패/);
 assert.match(els['ov-detail'].innerHTML,/비교 불가/);
 els['ov-prev'].onclick();assert.match(els['ov-selected-time'].textContent,/06:00/);
 els['ov-next'].onclick();els['ov-next'].onclick();assert.match(els['ov-selected-time'].textContent,/07:00/);
 els['ov-slider'].oninput({target:{value:'0'}});assert.match(els['ov-selected-time'].textContent,/06:00/);
 els['ov-weather'].onclick();assert.equal(els['ov-weather'].attributes['aria-pressed'],true);
 assert.match(els['ov-markers'].innerHTML,/맑음<\/span>/);
 const gangneung=els['ov-markers'].markers.find(e=>e.dataset.city==='강릉');gangneung.onclick();
 assert.match(els['ov-detail'].innerHTML,/참조 도시 · 요약 제외/);
 failPrevious=false;await els['ov-retry'].onclick();
 assert.match(els['ov-detail'].innerHTML,/\+1°/);
 failIndex=true;await els['ov-retry'].onclick();assert.match(els.weatherOverview.innerHTML,/표시할 수 없습니다/);
 failIndex=false;await els['ov-retry'].onclick();assert.match(els.weatherOverview.innerHTML,/전국 예보 지도/);
});

test('twelve configured cities are always in approved order, including missing new cities',()=>{
 assert.deepEqual(CITIES.map(c=>c.name),['서울','인천','수원','원주','강릉','대전','청주','전주','광주','대구','부산','제주']);
 assert.deepEqual(CITIES.map(c=>c.stn),[108,112,119,114,105,133,131,146,156,143,159,184]);
 assert.equal(CITIES.filter(c=>c.reference).map(c=>c.name).join(','),'강릉');
});
test('latest observation chooses one global hour and never fills a missing city from earlier hours',()=>{
 const obs={vars:{ta:{108:[3,4,5],112:[7,8,null],119:[null,null,0]}}};
 assert.equal(observationHour(obs),2);
 assert.deepEqual(latestObservation(obs,108),{temp:5,hour:'02'});
 assert.deepEqual(latestObservation(obs,119),{temp:0,hour:'02'});
 assert.equal(latestObservation(obs,112),null);
 assert.equal(observationHour({vars:{ta:{108:[null]}}}),null);
});
test('forecast-minus-observation requires exactly matching valid time in the latest issue',()=>{
 const obs={vars:{ta:{108:[null,null,0],112:[8,9,null]}}};
 const d=doc('2026102523','서울','2026102602',{temp:1});
 d.cities.서울['20261026'].hourly['2026102603']={temp:30};
 const city=CITIES[0];
 assert.equal(forecastObservation(d,obs,'20261026',city).error,1);
 delete d.cities.서울['20261026'].hourly['2026102602'];
 assert.equal(forecastObservation(d,obs,'20261026',city).error,null,'future forecast never subtracts current observation');
 assert.equal(forecastObservation(d,obs,'20261026',CITIES[1]).error,null);
});
test('responsive map has twelve collision-free cards, unchanged dots and short geographic leaders',()=>{
 for(const viewport of [320,360,390,699,700,701,960,1100,1101,1280,1440,1700,1920,2560,3440]){
  const narrow=viewport<=700,pad=Math.max(14,Math.min(56,viewport*.025));
  const inner=viewport-pad*2,w=viewport<=1100?inner-2:(inner-24)*2/3-2,h=narrow?720:viewport>=1700?810:760;
  const boxes=mapLayout(w,h,narrow),scale=Math.min(w/710,h/905),ox=(w-710*scale)/2,oy=(h-905*scale)/2;
  assert.equal(boxes.length,12);
  for(const b of boxes){
   assert(b.l>=0&&b.r<=w&&b.t>=0&&b.b<=h,`${viewport}: ${b.name} overflow`);
   assert.equal(b.px,ox+(POINTS[b.name][0]-35)*scale);assert.equal(b.py,oy+(POINTS[b.name][1]-75)*scale);
   for(const a of boxes)if(a!==b)assert(a.r<=b.l||b.r<=a.l||a.b<=b.t||b.b<=a.t,`${viewport}: ${a.name}/${b.name} overlap`);
   if(!narrow){assert(b.leader<=55,`${viewport}: ${b.name} long leader ${b.leader}`);for(const a of boxes)assert(!(a.px>b.l&&a.px<b.r&&a.py>b.t&&a.py<b.b),`${b.name} hides ${a.name} dot`);}
  }
  if(narrow){assert.equal(new Set(boxes.map(b=>b.x)).size,2);assert.equal(boxes.filter(b=>b.x<w/2).length,6);}
  else {const seoul=boxes.find(b=>b.name==='서울'),incheon=boxes.find(b=>b.name==='인천');assert(seoul.b<seoul.py);assert(incheon.r<incheon.px);}
 }
});
test('geometry is cached and viewport layout mode changes restore wide→narrow→wide geometry',()=>{
 const wide=mapLayout(660,760,false);assert.strictEqual(mapLayout(660,760,false),wide);
 const narrow=mapLayout(660,760,true);assert.notDeepEqual(narrow,wide);
 assert.deepEqual(mapLayout(660,760,false),wide);assert.notStrictEqual(mapLayout(661,760,false),wide);
 const fs=require('node:fs'),js=fs.readFileSync('site/overview.js','utf8'),css=fs.readFileSync('site/overview.css','utf8');
 assert.ok(js.includes('matchMedia("(max-width: 700px)")'));assert.ok(!js.includes('userAgent'));
 assert.ok(css.includes('height:720px'));assert.ok(css.includes('@media(max-width:1100px)'));
 assert.ok(!fs.readFileSync('site/style.css','utf8').includes('max-width: 1240px'));
});
