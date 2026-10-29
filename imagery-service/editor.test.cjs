const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
const raw=fs.readFileSync(__dirname+'/../site/energy-weather.js','utf8');const source=raw.slice(0,raw.lastIndexOf("(async()=>{try{const r=await fetch('energy/index.json'"));
function setup(fetcher){
 const calls={exports:0,draws:[],downloads:[]},nodes={},saved=new Map();
 function makeCanvas(id){const ctx=new Proxy({drawImage(im,...rest){calls.draws.push({canvas:id,source:im.id||im._src,...rest});}},{get:(obj,k)=>obj[k]??(()=>{})});return {id,hidden:true,width:1920,height:1080,getContext:()=>ctx,addEventListener(){},setPointerCapture(){},getBoundingClientRect:()=>({left:0,top:0,width:1920,height:1080}),toDataURL:()=> 'data:image/png;base64,AA',toBlob(cb){calls.exports++;cb(new Blob(['PNG'],{type:'image/png'}));}};}
 function node(id){return nodes[id]??=(id.startsWith('editorCanvas')?makeCanvas(id):{id,value:'',disabled:false,hidden:false,textContent:'',addEventListener(){},click(){if(this.download)calls.downloads.push(this.download);return this.onclick?.({preventDefault(){}});},replaceChildren(){this.value='';},append(option){if(!this.value)this.value=option.value;}});}
 class Image{constructor(){this.width=678;this.height=663;}set src(x){this._src=x;queueMicrotask(()=>this.onload());}get src(){return this._src;}}
 const sandbox={document:{getElementById:node,querySelector:()=>({content:'https://example.workers.dev'}),createElement:tag=>tag==='canvas'?makeCanvas('export'):node('created-'+tag)},Image,console,Intl,Date,Map,Promise,Number,JSON,Error,Boolean,AbortSignal,Blob,URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},setTimeout:()=>0,localStorage:{getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v)},window:{addEventListener(){},print(){}},fetch:fetcher};
 const context=vm.createContext(sandbox);vm.runInContext(source,context);node('date').value=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul'}).format(new Date()).replaceAll('-','');
 vm.runInContext("for(const ed of Object.values(editors)){ed.day=el('date').value;ed.original={revision:1,background:'bg'+ed.page,groups:[{id:'moved',x:ed.page===2?240:777,y:ed.page===2?260:200,w:100,h:100,src:'icon'}],boundaries:ed.page===2?[]:[{points:[[1,2],[3,4],[5,6],[7,8]],color:'blue',width:2}],panels:ed.page===2?[]:[{id:'radar',src:'old-radar',time:'old'},{id:'satellite',src:'old-satellite',time:'old'}],palette:{clear:'clear-icon',rain:'rain-icon'},forecastMarker:14.5};ed.scene=clone(ed.original);ed.background={id:'fixed-background-'+ed.page};}refreshControls();",context);
 return {nodes,calls,saved,context,run:s=>vm.runInContext(s,context)};
}
const panel=kind=>({ok:true,json:async()=>({id:kind,src:'data:image/png;base64,AA',time:new Date(Date.now()-300000).toISOString()})});
test('refresh preserves map edits and page 2; closing editor and normal PNG keep updates',async()=>{
 const t=setup(async url=>panel(url.split('/').at(-1)));const before=t.run('JSON.stringify([editors[1].scene.groups,editors[1].scene.boundaries,editors[2].scene])');await t.nodes.refreshImages.click();assert.equal(t.run('JSON.stringify([editors[1].scene.groups,editors[1].scene.boundaries,editors[2].scene])'),before);assert.equal(t.run('editors[1].scene.panels.every(p=>p.updated)'),true);assert.equal(t.nodes.editorCanvas.hidden,false);
 t.nodes.edit.click();t.nodes.edit.click();assert.equal(t.nodes.editorCanvas.hidden,false);await t.nodes.save1.click();assert.equal(t.calls.exports,1);
});
test('partial and total imagery failures preserve existing content',async()=>{
 const t=setup(async url=>url.endsWith('/radar')?{ok:false}:panel('satellite'));await t.nodes.refreshImages.click();assert.equal(t.run("editors[1].scene.panels.find(p=>p.id==='radar').src"),'old-radar');
 const fail=setup(async()=>{throw Error('unavailable');});const before=fail.run('JSON.stringify(editors[1].scene)');await fail.nodes.refreshImages.click();assert.equal(fail.run('JSON.stringify(editors[1].scene)'),before);assert.equal(fail.run('editors[1].history.length'),0);
});
test('date switch while refreshing discards the old response',async()=>{
 let release;const gate=new Promise(r=>release=r);const t=setup(async url=>{await gate;return panel(url.split('/').at(-1));});const before=t.run('JSON.stringify(editors[1].scene)');const pending=t.nodes.refreshImages.click();t.run('loadToken++');release();await pending;assert.equal(t.run('JSON.stringify(editors[1].scene)'),before);
});
test('page 2 drag and resize stay inside weather area and leave page 1 unchanged',()=>{
 const t=setup();const before=t.run('JSON.stringify(editors[1].scene)');t.nodes.edit2.click();t.run('editors[2].pointerDown({clientX:250,clientY:270,pointerId:1});editors[2].pointerMove({clientX:1900,clientY:900});editors[2].resize(1.5)');const g=JSON.parse(t.run('JSON.stringify(editors[2].scene.groups[0])'));assert.ok(g.y+g.h<=444&&g.x+g.w<=1836);assert.equal(t.run('JSON.stringify(editors[1].scene)'),before);assert.equal(t.nodes.addBoundary2,undefined);
});
test('page 2 replacement, add, delete, undo and reset affect weather groups only',async()=>{
 const t=setup();const initial=t.run('JSON.stringify(editors[2].scene)');t.run("editors[2].selected={type:'group',index:0};editors[2].node('iconChoice').value='rain'");await t.nodes.replaceIcon2.click();assert.equal(t.run('editors[2].scene.groups[0].src'),'rain-icon');assert.equal(t.run('editors[2].scene.forecastMarker'),14.5);t.nodes.undo2.click();assert.equal(t.run('JSON.stringify(editors[2].scene)'),initial);await t.nodes.addIcon2.click();assert.equal(t.run('editors[2].scene.groups.length'),2);t.nodes.remove2.click();assert.equal(t.run('editors[2].scene.groups.length'),1);t.nodes.reset2.click();assert.equal(t.run('JSON.stringify(editors[2].scene)'),initial);
});
test('page-specific storage and page 2 PNG preserve edits after closing',async()=>{
 const t=setup();t.run("editors[2].selected={type:'group',index:0};editors[2].resize(1.25)");t.nodes.saveLayout.click();t.nodes.saveLayout2.click();assert.equal(t.saved.size,2);assert.ok([...t.saved.keys()].some(k=>k.endsWith('-page2')));t.nodes.edit2.click();t.nodes.edit2.click();assert.equal(t.nodes.editorCanvas2.hidden,false);await t.nodes.save2.click();assert.match(t.calls.downloads.at(-1),/_02_edited\.png$/);assert.ok(t.calls.draws.some(d=>d.canvas==='export'&&d.source==='editorCanvas2'));
});
test('page 2 loads saved icons without accepting saved boundary or graph objects',async()=>{
 const scene={background:'background2.webp',groups:[{x:240,y:250,w:70,h:70,src:'icon'}],boundaries:[],panels:[],palette:{clear:'icon'},revision:1};const t=setup(async()=>({ok:true,json:async()=>scene}));const key=t.run('editors[2].storageKey()');t.saved.set(key,JSON.stringify({...scene,groups:[{x:240,y:900,w:70,h:70,src:'icon'}],boundaries:[{points:[]}],panels:[{updated:true}]}));await t.run("editors[2].load(el('date').value,'v',loadToken)");assert.equal(t.run('editors[2].scene.boundaries.length'),0);assert.equal(t.run('editors[2].scene.panels.length'),0);assert.ok(t.run('editors[2].scene.groups[0].y+editors[2].scene.groups[0].h<=444'));assert.equal(t.nodes.edit2.disabled,false);
});
test('date switch during page 2 metadata loading cannot restore stale layout',async()=>{
 let release;const gate=new Promise(r=>release=r);const scene={background:'bg',groups:[],boundaries:[],palette:{}};const t=setup(async()=>{await gate;return {ok:true,json:async()=>scene};});const pending=t.run("editors[2].load('20261029','v',loadToken)");t.run("loadToken++;editors[2].clear()");release();await pending;assert.equal(t.run('editors[2].scene'),null);assert.equal(t.nodes.edit2.disabled,true);
});
