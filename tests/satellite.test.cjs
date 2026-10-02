const test = require('node:test');
const assert = require('node:assert/strict');
const {imageURL,kst,timeline,latestCandidates,catalogFrames,ImageCache} = require('../site/satellite.js');
const now = Date.parse('2026-10-02T00:32:00Z');
test('KST midnight and UTC filename refer to the same observation', () => {
  const t = Date.parse('2026-10-01T15:02:00Z');
  assert.equal(kst(t),'2026.10.02 00:02');
  assert.match(imageURL('rgb-s-daynight',t),/rgb-s-daynight_ko020lc_202610011502\.png$/);
  assert.throws(()=>imageURL('vi006',t));
  assert.throws(()=>imageURL('ir105',t+60000));
});
test('2-minute six-hour timeline crosses midnight without dropping an endpoint', () => {
  const frames = timeline(now,6,2);
  assert.equal(frames.length,181);
  assert.equal(frames[0],now-6*3600000);
  assert.equal(frames.at(-1),now);
  assert.equal(timeline(now,1,10).length,7);
});
test('metadata cannot request another host, channel, future, or expired frame', () => {
  const goodTime=now-4*60000;
  const frame=t=>({time:new Date(t).toISOString(),url:imageURL('ir105',t)});
  const good=frame(goodTime);
  const catalog={channels:{ir105:{frames:[good,good,{...good,url:good.url.replace('www.weather.go.kr','example.com')},frame(now+120000),frame(now-7*3600000),{...good,url:imageURL('rgb-cs',goodTime)}]}}};
  assert.deepEqual(catalogFrames(catalog,'ir105',now),[goodTime]);
});
test('latest discovery has a small fixed window and avoids known older frames', () => {
  const candidates=latestCandidates(now,null);
  assert.equal(candidates.length,5);
  assert.equal(candidates[0],now-4*60000);
  assert.deepEqual(latestCandidates(now,now-6*60000),[now-4*60000]);
});
test('cache shares pending requests, retries failures, and bounds retained frames', async () => {
  let calls=0;let release;
  const cache=new ImageCache(2,url=>{calls++;return url==='pending'?new Promise(r=>{release=r}):url==='bad'?Promise.reject(new Error('missing')):url;});
  const a=cache.get('pending'),b=cache.get('pending');assert.equal(a,b);
  await Promise.resolve();release('ok');await a;assert.equal(calls,1);
  await assert.rejects(cache.get('bad'));assert.equal(cache.entries.has('bad'),false);
  await assert.rejects(cache.get('bad'));assert.equal(calls,3);
  await cache.get('one');await cache.get('two');assert.equal(cache.entries.size,2);
  assert.equal(cache.entries.has('pending'),false);
});

test('late image responses cannot overwrite a new channel or a hidden tab', async () => {
  const vm=require('node:vm'),fs=require('node:fs');
  class Element {
    constructor(id=''){this.id=id;this.hidden=false;this.value='';this.dataset={};this.attrs={};this.listeners={};this.children=[];this.textContent='';this.src='';const set=new Set();this.classList={contains:k=>set.has(k),add:k=>set.add(k),remove:k=>set.delete(k),toggle:(k,on)=>on?set.add(k):set.delete(k)};}
    addEventListener(k,fn){(this.listeners[k]??=[]).push(fn);}
    fire(k){for(const fn of this.listeners[k]||[])fn({target:this});}
    click(){this.fire('click');}
    setAttribute(k,v){this.attrs[k]=v;}
    replaceChildren(){this.children=[];}
    append(el){this.children.push(el);}
    focus(){}
  }
  const html=fs.readFileSync(require('node:path').join(__dirname,'../site/index.html'),'utf8');
  const elements=Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element(m[1])]));
  elements.obsSatellite.hidden=true;elements['tab-obs'].classList.add('on');
  elements.satelliteHours.value='1';elements.satelliteStep.value='10';elements.satelliteSpeed.value='800';
  const channels=['rgb-cs','rgb-s-daynight','ir105'].map(key=>{const e=new Element();e.dataset.satelliteChannel=key;return e;});
  const nav=new Element();nav.dataset.tab='obs';
  const doc={hidden:false,getElementById:id=>elements[id],createElement:()=>new Element(),addEventListener(){},querySelectorAll:s=>s==='#tabs button'?[nav]:s==='[data-satellite-channel]'?channels:[]};
  const pending=[];
  class FakeImage {
    constructor(){this.naturalWidth=600;}
    set src(url){this._src=url;if(url)pending.push(this);}
    get src(){return this._src;}
  }
  class FixedDate extends Date {static now(){return now;}}
  const seed=now-4*60000;
  const catalog={channels:Object.fromEntries(channels.map(c=>[c.dataset.satelliteChannel,{frames:[{time:new Date(seed).toISOString(),url:imageURL(c.dataset.satelliteChannel,seed)}]}]))};
  const context={module:{exports:{}},document:doc,location:{search:''},Image:FakeImage,Date:FixedDate,URLSearchParams,AbortController,fetch:async()=>({ok:true,json:async()=>catalog}),setTimeout,clearTimeout,setInterval:()=>0,console};
  vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../site/satellite.js'),'utf8'),context);
  const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
  try {
    elements.obsSatelliteTab.click();await flush();
    const initial=pending.find(im=>im.src===imageURL('rgb-cs',seed));assert.ok(initial);
    channels[2].click();await flush();
    const current=pending.find(im=>im.src===imageURL('ir105',seed));assert.ok(current);
    current.onload();await flush();assert.match(elements.satelliteImage.alt,/적외 10.5/);
    initial.onload();await flush();assert.match(elements.satelliteImage.alt,/적외 10.5/);
    elements.satellitePrev.click();await flush();
    const older=pending.find(im=>im.src===imageURL('ir105',seed-10*60000));assert.ok(older);
    elements.obsGroundTab.click();const before=elements.satelliteTimestamp.textContent;
    older.onload();await flush();assert.equal(elements.satelliteTimestamp.textContent,before);
    assert.equal(elements.obsSatellite.hidden,true);
  } finally {for(const im of pending)if(im.onerror)im.onerror();await flush();}
});
