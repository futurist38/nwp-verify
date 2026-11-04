const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
const raw=fs.readFileSync(__dirname+'/../site/energy-weather.js','utf8');const source=raw.slice(0,raw.lastIndexOf("(async()=>{try{const r=await reportFetch('energy/index.json'"));
function setup(fetcher){
 const calls={events:{},exports:0,draws:[],downloads:[],texts:[],rects:[]},nodes={},saved=new Map();let created=0;
 function makeCanvas(id){const ctx=new Proxy({measureText(text){return {width:[...text].length*32};},fillText(text){calls.texts.push({canvas:id,text,color:this.fillStyle,font:this.font});},fillRect(){calls.rects.push({canvas:id,kind:'fill',color:this.fillStyle});},strokeRect(){calls.rects.push({canvas:id,kind:'stroke',color:this.strokeStyle});},drawImage(im,...rest){calls.draws.push({canvas:id,source:im.id||im._src,...rest});}},{get:(obj,k)=>obj[k]??(()=>{})});return {id,style:{},hidden:true,width:1920,height:1080,getContext:()=>ctx,focus(){},addEventListener(){},setPointerCapture(){},getBoundingClientRect:()=>({left:0,top:0,width:1920,height:1080}),toDataURL:()=> 'data:image/png;base64,AA',toBlob(cb){calls.exports++;cb(new Blob(['PNG'],{type:'image/png'}));}};}
 function node(id){return nodes[id]??=(id.startsWith('editorCanvas')?makeCanvas(id):{id,style:{},classList:{add(){},toggle(){}},setAttribute(){},remove(){},prepend(...items){this.children.unshift(...items);},children:[],value:'',disabled:false,hidden:false,textContent:'',focus(){},addEventListener(){},click(){if(this.download)calls.downloads.push(this.download);return this.onclick?.({preventDefault(){}});},replaceChildren(){this.value='';},append(...options){this.children.push(...options);for(const option of options){if(option.id)nodes[option.id]=option;if(!this.value)this.value=option.value;}}});}
 class Image{constructor(){this.width=678;this.height=663;}set src(x){this._src=x;queueMicrotask(()=>this.onload());}get src(){return this._src;}}
 const sandbox={document:{addEventListener(type,handler){calls.events[type]=handler;},querySelectorAll:()=>[],getElementById:node,querySelector:()=>({content:'https://example.workers.dev'}),createElement:tag=>tag==='canvas'?makeCanvas('export'):node('created-'+tag+'-'+(++created))},Image,TextEncoder,console,Intl,Date,Map,Promise,Number,JSON,Error,Boolean,AbortSignal,Blob,URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},setTimeout:()=>0,localStorage:{getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v),removeItem:k=>saved.delete(k)},window:{addEventListener(){},print(){}},fetch:fetcher};
 const context=vm.createContext(sandbox);vm.runInContext(source,context);vm.runInContext(fs.readFileSync(__dirname+'/../site/inline-edit.js','utf8'),context);node('date').value=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul'}).format(new Date()).replaceAll('-','');
 vm.runInContext("for(const ed of Object.values(editors)){ed.day=el('date').value;ed.original={revision:1,background:'bg'+ed.page,groups:[{id:'moved',x:ed.page===2?240:777,y:ed.page===2?260:200,w:100,h:100,src:'icon'}],boundaries:ed.page===2?[]:[{points:[[1,2],[3,4],[5,6],[7,8]],color:'blue',width:2}],panels:ed.page===2?[]:[{id:'radar',src:'old-radar',time:'old'},{id:'satellite',src:'old-satellite',time:'old'}],palette:{clear:'clear-icon',rain:'rain-icon'},forecastMarker:14.5};ed.scene=clone(ed.original);ed.background={id:'fixed-background-'+ed.page};}refreshControls();",context);
 return {nodes,calls,saved,context,run:s=>vm.runInContext(s,context)};
}
const panel=kind=>({ok:true,json:async()=>({id:kind,src:'data:image/png;base64,AA',time:new Date(Date.now()-300000).toISOString()})});
test('both pages add and edit readable text boxes with independent undo, delete and reset',()=>{
 for(const page of [1,2]){
  const t=setup(),suffix=page===2?'2':'',ed='editors['+page+']';
  const original=t.run('JSON.stringify('+ed+'.scene)'),other=t.run('JSON.stringify(editors['+(3-page)+'].scene)');
  t.nodes['textInput'+suffix].value='   ';t.nodes['addText'+suffix].click();assert.equal(t.run(ed+'.history.length'),0);
  t.nodes['textInput'+suffix].value='늦은 오후';t.nodes['addText'+suffix].click();
  assert.equal(t.run(ed+'.scene.texts[0].text'),'늦은 오후');assert.equal(t.nodes['replaceIcon'+suffix].disabled,true);assert.equal(t.nodes['size'+suffix].disabled,false);
  assert.ok(t.calls.texts.some(d=>d.text==='늦은 오후'&&d.color==='#0653b8'&&d.font.startsWith('700')));
  assert.ok(t.calls.rects.some(d=>d.kind==='fill'&&d.color==='#ffffff'));assert.ok(t.calls.rects.some(d=>d.kind==='stroke'&&d.color==='#000000'));
  t.nodes['textInput'+suffix].value='늦은 오후\n비 시작';t.nodes['updateText'+suffix].click();assert.equal(t.run(ed+'.scene.texts[0].text'),'늦은 오후\n비 시작');
  t.nodes['undo'+suffix].click();assert.equal(t.run(ed+'.scene.texts[0].text'),'늦은 오후');
  t.run(ed+".selected={type:'text',index:0}");t.nodes['remove'+suffix].click();assert.equal(t.run(ed+'.scene.texts.length'),0);
  t.nodes['undo'+suffix].click();assert.equal(t.run(ed+'.scene.texts.length'),1);
  assert.equal(t.run('JSON.stringify(editors['+(3-page)+'].scene)'),other);
  t.nodes['reset'+suffix].click();assert.equal(t.run('JSON.stringify('+ed+'.scene)'),original);
 }
});
test('text boxes drag beyond page 2 weather strip, resize at corners and remain on page',()=>{
 const t=setup();t.nodes.edit2.click();t.nodes.textInput2.value='늦은 오후';t.nodes.addText2.click();
 t.run('editors[2].pointerDown({clientX:850,clientY:330,pointerId:1,preventDefault(){}});editors[2].pointerMove({clientX:1400,clientY:850})');
 let g=JSON.parse(t.run('JSON.stringify(editors[2].scene.texts[0])'));assert.ok(g.y>444);
 const history=t.run('editors[2].history.length');
 t.run('editors[2].pointerDown({clientX:'+(g.x+g.w)+',clientY:'+(g.y+g.h)+',pointerId:1,preventDefault(){}});editors[2].pointerMove({clientX:'+(g.x+g.w*1.5)+',clientY:'+(g.y+g.h*1.5)+'})');
 let resized=JSON.parse(t.run('JSON.stringify(editors[2].scene.texts[0])'));assert.equal(resized.x,g.x);assert.equal(resized.y,g.y);assert.ok(Math.abs(resized.w/g.w-1.5)<1e-9);assert.equal(t.run('editors[2].history.length'),history+1);
 t.nodes.undo2.click();assert.deepEqual(JSON.parse(t.run('JSON.stringify(editors[2].scene.texts[0])')),g);
 t.run('editors[2].pointerDown({clientX:'+(g.x+40)+',clientY:'+(g.y+30)+',pointerId:1,preventDefault(){}});editors[2].pointerMove({clientX:3000,clientY:3000})');
 g=JSON.parse(t.run('JSON.stringify(editors[2].scene.texts[0])'));assert.ok(g.x+g.w<=1912&&g.y+g.h<=1072);
});
test('saved annotations reload outside weather strip, export and ignore malformed text objects',async()=>{
 const scene={background:'bg',groups:[],boundaries:[],palette:{},revision:1};
 const t=setup(async()=>({ok:true,json:async()=>({...scene})}));
 t.nodes.textInput2.value='늦은 오후';t.nodes.addText2.click();t.run('editors[2].scene.texts[0].y=800');t.nodes.saveLayout2.click();
 const key=t.run('editors[2].storageKey()'),stored=JSON.parse(t.saved.get(key));stored.texts.push(null,{text:'bad',w:-1,h:10,x:0,y:0});t.saved.set(key,JSON.stringify(stored));
 await t.run("editors[2].load(el('date').value,'v',loadToken)");assert.equal(t.run('editors[2].scene.texts.length'),1);assert.equal(t.run('editors[2].scene.texts[0].y'),800);
 t.nodes.edit2.click();t.nodes.edit2.click();assert.equal(t.nodes.editorCanvas2.hidden,false);
 t.calls.texts.length=0;await t.nodes.save2.click();assert.ok(t.calls.texts.some(d=>d.text==='늦은 오후'));assert.match(t.calls.downloads.at(-1),/_02_edited\.png$/);
});
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
 const t=setup();const before=t.run('JSON.stringify(editors[1].scene)');t.nodes.edit2.click();t.run('editors[2].pointerDown({clientX:250,clientY:270,pointerId:1,preventDefault(){}});editors[2].pointerMove({clientX:1900,clientY:900});editors[2].resize(1.5)');const g=JSON.parse(t.run('JSON.stringify(editors[2].scene.groups[0])'));assert.ok(g.y+g.h<=444&&g.x+g.w<=1836);assert.equal(t.run('JSON.stringify(editors[1].scene)'),before);assert.equal(t.nodes.addBoundary2,undefined);
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

test('corner drag resizes both pages with fixed aspect ratio and one undo step',()=>{
 for(const page of [1,2]){
  const t=setup(),other=page===1?2:1;
  const unchanged=t.run('JSON.stringify(editors['+other+'].scene)');
  t.nodes[page===1?'edit':'edit2'].click();
  const start=JSON.parse(t.run('JSON.stringify(editors['+page+'].scene.groups[0])'));
  t.run('editors['+page+'].pointerDown({clientX:'+(start.x+50)+',clientY:'+(start.y+50)+',pointerId:1,preventDefault(){}})');
  const history=t.run('editors['+page+'].history.length');
  t.run('editors['+page+'].pointerDown({clientX:'+(start.x+start.w)+',clientY:'+(start.y+start.h)+',pointerId:1,preventDefault(){}})');
  assert.equal(t.run('editors['+page+'].drag.type'),'multiResize');
  for(const size of [130,160])t.run('editors['+page+'].pointerMove({clientX:'+(start.x+size)+',clientY:'+(start.y+size)+'})');
  const end=JSON.parse(t.run('JSON.stringify(editors['+page+'].scene.groups[0])'));
  assert.equal(end.x,start.x);assert.equal(end.y,start.y);assert.equal(end.w,160);assert.equal(end.h,160);
  assert.equal(t.run('editors['+page+'].history.length'),history+1);
  assert.equal(t.run('JSON.stringify(editors['+other+'].scene)'),unchanged);
  t.nodes[page===1?'undo':'undo2'].click();
  assert.deepEqual(JSON.parse(t.run('JSON.stringify(editors['+page+'].scene.groups[0])')),start);
 }
});


test('custom satellite and radar uploads restore independently and survive save/export',async()=>{
 const t=setup();
 for(const kind of ['satellite','radar']){
  t.nodes[kind+'Time'].value='09:00 KST';
  await t.run("editors[1].uploadPanel('"+kind+"',{files:[{size:100,type:'image/png'}],value:'test'})");
  assert.equal(t.run("editors[1].scene.panels.find(p=>p.id==='"+kind+"').custom"),true);
  assert.equal(t.run("editors[1].scene.panels.find(p=>p.id==='"+kind+"').timeText"),'09:00 KST');
 }
 t.nodes.saveLayout.click();assert.ok([...t.saved.values()].some(s=>JSON.parse(s).panels.every(p=>p.custom)));
 const button=Object.values(t.nodes).find(n=>n.textContent==='기존 위성 복원');button.click();
 assert.equal(t.run("editors[1].scene.panels.find(p=>p.id==='satellite').src"),'old-satellite');
 assert.equal(t.run("editors[1].scene.panels.find(p=>p.id==='radar').custom"),true);
 t.nodes.undo.click();assert.equal(t.run("editors[1].scene.panels.find(p=>p.id==='satellite').custom"),true);
 await t.nodes.save1.click();assert.ok(t.calls.downloads.at(-1).endsWith('_01_edited.png'));
});

test('Ctrl selection copies, moves and deletes a set with one undo and keeps text input native',async()=>{
 const t=setup();t.nodes.edit.click();
 t.run("editors[1].scene.groups=[{id:'a',src:'one',x:650,y:300,w:100,h:100},{id:'b',src:'two',x:900,y:450,w:120,h:80}]");
 t.run("editors[1].pointerDown({clientX:700,clientY:350,pointerId:1,preventDefault(){}});editors[1].pointerDown({clientX:950,clientY:490,ctrlKey:true,pointerId:1,preventDefault(){}})");
 assert.equal(t.run('editors[1].selection().length'),2);
 let intercepted=0;const key=(key,ctrlKey=true,input=false)=>t.calls.events.keydown({key,ctrlKey,preventDefault(){intercepted++},target:{closest(){return input?{}:null}}});
 key('c');key('v');await new Promise(r=>setImmediate(r));
 assert.equal(t.run('editors[1].scene.groups.length'),4);
 assert.equal(t.run('editors[1].scene.groups[3].x-editors[1].scene.groups[2].x'),250);
 assert.equal(t.run('editors[1].selection().length'),2);
 t.run("editors[1].pointerDown({clientX:724,clientY:374,pointerId:1,preventDefault(){}});editors[1].pointerMove({clientX:774,clientY:404})");
 assert.equal(t.run('editors[1].scene.groups[3].x-editors[1].scene.groups[2].x'),250);
 assert.equal(t.run('editors[1].scene.groups[3].y-editors[1].scene.groups[2].y'),150);
 key('Delete',false);assert.equal(t.run('editors[1].scene.groups.length'),2);
 key('z');assert.equal(t.run('editors[1].scene.groups.length'),4);
 const before=intercepted;key('c',true,true);key('Delete',false,true);assert.equal(intercepted,before);
});
test('automatic and edited publication labels use identical original font and size',()=>{
 const t=setup();t.run("editors[1].scene.labels=[{x:1880,y:63,text:'발표시점: 07시 기준',size:24,bold:true,color:'black',anchor:'rm'}];editors[1].draw()");
 const auto=t.calls.texts.find(x=>x.text==='발표시점: 07시 기준');
 t.run("editors[1].scene.publicationText='발표시점: 09시 기준';editors[1].draw()");
 const edited=t.calls.texts.find(x=>x.text==='발표시점: 09시 기준');
 assert.equal(auto.font,edited.font);assert.match(auto.font,/700 24px.*Malgun Gothic/);
});

test('all label overrides persist, undo, and forecast dates render red',()=>{
 const t=setup();t.run("editors[1].scene.labels=[{x:880,y:176,text:'오늘예보(11/4, 수)',size:29.3333,bold:true,color:'#00235b',anchor:'mm'},{x:1880,y:1053,text:'출처',size:23,color:'black',anchor:'rm'}];editors[1].remember();editors[1].setLabel(1,'출처 수정');editors[1].draw()");
 assert.equal(t.run('editors[1].labelValue(1)'),'출처 수정');
 assert.ok(t.calls.texts.some(x=>x.text==='(11/4, 수)'&&x.color==='#e60012'));
 assert.ok(t.calls.texts.some(x=>x.text==='오늘예보'&&x.color==='#00235b'));
 t.nodes.saveLayout.click();assert.ok([...t.saved.values()].some(x=>JSON.parse(x).labelOverrides?.[1]==='출처 수정'));
 t.nodes.undo.click();assert.equal(t.run('editors[1].labelValue(1)'),'출처');
});
test('PDF serializer builds exactly one 16:9 page with valid xref offsets',async()=>{
 const t=setup();const pdf=await t.run('reportPDF(new Uint8Array([255,216,255,217])).text()');
 assert.match(pdf,/\/MediaBox \[0 0 1920 1080\]/);assert.match(pdf,/\/Count 1/);
 const offset=Number(pdf.match(/startxref\n(\d+)/)[1]);assert.equal(pdf.slice(offset,offset+4),'xref');
});
test('four allowed text colors support partial ranges, undo and annotation persistence',()=>{
 const t=setup();assert.equal(t.run('TEXT_COLORS.length'),4);
 assert.equal(t.run("JSON.stringify(applyTextColor([], 'abcd',1,3,'#e60012'))"),'[null,"#e60012","#e60012"]');
 assert.equal(t.run("JSON.stringify(applyTextColor([], 'abcd',1,3,'purple'))"),'[]');
 t.nodes.textInput.value='기온 설명';t.nodes.addText.click();t.run("editors[1].colorText('#666666')");
 assert.ok(t.run("editors[1].scene.texts[0].colors.every(c=>c==='#666666')"));t.nodes.saveLayout.click();
 assert.ok([...t.saved.values()].some(s=>JSON.parse(s).texts?.[0]?.colors?.[0]==='#666666'));
 t.nodes.undo.click();assert.equal(t.run('editors[1].scene.texts[0].colors'),undefined);
});


test('reset restores deleted original sprites and removes only this page saved edits across reload',async()=>{
 for(const page of [1,2]){
  const scene={background:'bg',groups:[{x:240,y:250,w:70,h:70,src:'original-icon'}],boundaries:[],panels:[],palette:{clear:'original-icon'},revision:1};
  const t=setup(async()=>({ok:true,json:async()=>JSON.parse(JSON.stringify(scene))})),ed='editors['+page+']',suffix=page===2?'2':'';
  const key=t.run(ed+'.storageKey()');t.saved.set(key,JSON.stringify({...scene,groups:[],labelOverrides:{0:'edited'}}));t.saved.set('other-date-page','untouched');
  await t.run(ed+".load(el('date').value,'v',loadToken)");
  assert.equal(t.run(ed+'.scene.groups.length'),0);assert.equal(t.run(ed+".sprites.has('original-icon')"),true);
  t.run(ed+".setSelection([{type:'group',index:0}])");t.nodes['reset'+suffix].click();
  assert.equal(t.run(ed+'.scene.groups.length'),1);assert.equal(t.run(ed+'.selection().length'),0);assert.equal(t.saved.has(key),false);assert.equal(t.saved.get('other-date-page'),'untouched');
  assert.ok(t.calls.draws.some(d=>d.source==='original-icon'));
  t.nodes['undo'+suffix].click();assert.equal(t.run(ed+'.scene.groups.length'),0);
  await t.run(ed+".load(el('date').value,'v',loadToken)");assert.equal(t.run(ed+'.scene.groups.length'),1);assert.equal(t.run(ed+'.scene.labelOverrides'),undefined);
 }
});
