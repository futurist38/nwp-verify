const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname,'../site/digital-mid.js'),'utf8');
class Element {
  constructor(){ this.children=[];this.elements={};this.events={};this.textContent='';this.value='';this.html=''; }
  set innerHTML(s){ this.html=s; const option=s.match(/<option value="([^"]*)"/); if(option) this.value=option[1]; }
  get innerHTML(){ return this.html; }
  appendChild(e){this.children.push(e);}
  querySelector(s){return this.elements[s] ||= new Element();}
  addEventListener(event, fn){this.events[event]=fn;}
}
async function load(payload){
  const host=new Element();
  vm.runInNewContext(source,{
    document:{readyState:'complete',getElementById:()=>host,createElement:()=>new Element()},
    fetch:async()=>({ok:true,json:async()=>payload}), console
  });
  await new Promise(r=>setImmediate(r));
  return host;
}
function issue(key, tmn, tmx){
  const wx={raw:60,label:'60% · 보통'};
  return {issue:key,cities:{'서울':{sample:{lat:37.5,lon:127},daily:{'20261118':{TMN:tmn,TMX:tmx,TMX_quantiles:{p10:10,p25:12,p75:18,p90:20}}},hourly:{'2026111812':{TMP:16,SKY:{raw:4,label:'흐림'},PTY:{raw:1,label:'비'},RPOS:wx,RVAR:{raw:2,label:'공식 변동성 설명'}}}}}};
}
test('off and shadow do not expose digital forecasts',async()=>{
  for(const mode of ['off','shadow']) assert.equal((await load({schema:1,mode,issues:[issue('2026111218',5,15)]})).children.length,0);
});
test('active missing data explicitly reports unavailable',async()=>{
  const h=await load({schema:1,mode:'active',issues:[]});
  assert.match(h.children[0].textContent,/검증을 통과한 수신 자료가 없습니다/);
});
test('active daily ranges are absolute values, and changes use previous digital issue',async()=>{
  const h=await load({schema:1,mode:'active',issues:[issue('2026111218',5,15),issue('2026111318',7,16)]});
  const panel=h.children[0];
  assert.match(panel.querySelector('.dm-daily').innerHTML,/>\+2.0</);
  assert.match(panel.querySelector('.dm-daily').innerHTML,/12.0~18.0 \/ 10.0~20.0/);
  assert.match(panel.querySelector('.dm-hourly').innerHTML,/60% · 보통/);
  const select=panel.querySelector('.dm-issue');select.value='0';select.events.change();
  assert.match(panel.querySelector('.dm-status').textContent,/이전 발표 없음/);
  assert.doesNotMatch(panel.querySelector('.dm-daily').innerHTML,/>\+2.0</);
});
test('weather labels are escaped rather than interpreted as markup',async()=>{
  const d=issue('2026111218',5,15);d.cities['서울'].hourly['2026111812'].RVAR.label='<img src=x onerror=alert(1)>';
  const h=await load({schema:1,mode:'active',issues:[d]});
  assert.match(h.children[0].querySelector('.dm-hourly').innerHTML,/&lt;img/);
  assert.doesNotMatch(h.children[0].querySelector('.dm-hourly').innerHTML,/<img/);
});
