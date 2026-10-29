const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
const raw=fs.readFileSync(__dirname+'/../site/energy-weather.js','utf8');const source=raw.slice(0,raw.lastIndexOf("(async()=>{try{const r=await fetch('energy/index.json'"));
function setup(fetcher){
 const calls={exports:0},nodes={};const ctx=new Proxy({},{get:()=>()=>{}});
 function node(id){return nodes[id]??=(id==='editorCanvas'?canvas:{value:'',disabled:false,hidden:false,textContent:'',addEventListener(){},click(){return this.onclick?.({preventDefault(){}});},replaceChildren(){},append(){}});}
 const canvas={hidden:true,width:1920,height:1080,getContext:()=>ctx,addEventListener(){},toDataURL:()=> 'data:image/png;base64,AA',toBlob(cb){calls.exports++;cb(new Blob(['PNG'],{type:'image/png'}));}};
 class Image{constructor(){this.width=678;this.height=663;}set src(x){this._src=x;queueMicrotask(()=>this.onload());}get src(){return this._src;}}
 const sandbox={document:{getElementById:node,querySelector:()=>({content:'https://example.workers.dev'}),createElement:tag=>tag==='canvas'?{...canvas}:node('created-'+tag)},Image,console,Intl,Date,Map,Promise,Number,JSON,Error,Boolean,AbortSignal,Blob,URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},setTimeout:()=>0,localStorage:{getItem:()=>null,setItem(){}},window:{addEventListener(){},print(){}},fetch:fetcher};
 const context=vm.createContext(sandbox);vm.runInContext(source,context);node('date').value=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul'}).format(new Date()).replaceAll('-','');
 vm.runInContext("original={revision:1,groups:[{id:'moved',x:777,y:200,w:100,h:100,src:'icon'}],boundaries:[{points:[[1,2],[3,4],[5,6],[7,8]],color:'blue',width:2}],panels:[{id:'radar',src:'old-radar',time:'old'},{id:'satellite',src:'old-satellite',time:'old'}],palette:{},forecastMarker:14.5};scene=clone(original);background={};refreshControls();",context);
 return {nodes,calls,context,run:s=>vm.runInContext(s,context)};
}
const panel=kind=>({ok:true,json:async()=>({id:kind,src:'data:image/png;base64,AA',time:new Date(Date.now()-300000).toISOString()})});
test('refresh preserves maps and forecast; closing editor and normal PNG keep updates',async()=>{
 const t=setup(async url=>panel(url.split('/').at(-1)));const before=t.run('JSON.stringify([scene.groups,scene.boundaries,scene.forecastMarker])');await t.nodes.refreshImages.click();assert.equal(t.run('JSON.stringify([scene.groups,scene.boundaries,scene.forecastMarker])'),before);assert.equal(t.run('scene.panels.every(p=>p.updated)'),true);assert.equal(t.nodes.editorCanvas?.hidden??t.run('canvas.hidden'),false);
 t.nodes.edit.click();t.nodes.edit.click();assert.equal(t.run('canvas.hidden'),false);await t.nodes.save1.click();assert.equal(t.calls.exports,1);
});
test('partial failure retains the original failed panel',async()=>{
 const t=setup(async url=>url.endsWith('/radar')?{ok:false}:panel('satellite'));await t.nodes.refreshImages.click();assert.equal(t.run("scene.panels.find(p=>p.id==='radar').src"),'old-radar');assert.equal(t.run("scene.panels.find(p=>p.id==='satellite').updated"),true);
});
test('total failure leaves entire scene and undo history unchanged',async()=>{
 const t=setup(async()=>{throw Error('unavailable');});const before=t.run('JSON.stringify(scene)');await t.nodes.refreshImages.click();assert.equal(t.run('JSON.stringify(scene)'),before);assert.equal(t.run('history.length'),0);
});
test('date switch while fetching discards the old response',async()=>{
 let release;const gate=new Promise(r=>release=r);const t=setup(async url=>{await gate;return panel(url.split('/').at(-1));});const before=t.run('JSON.stringify(scene)');const pending=t.nodes.refreshImages.click();t.run('loadToken++');release();await pending;assert.equal(t.run('JSON.stringify(scene)'),before);
});
