const {chromium}=require('playwright'),{spawn}=require('node:child_process'),assert=require('node:assert/strict');
(async()=>{
 const server=spawn('python',['-m','http.server','8766','--bind','127.0.0.1','--directory','energy_editor_stage'],{stdio:'ignore'});let browser;
 try{
  for(let i=0;i<50;i++){try{await fetch('http://127.0.0.1:8766/energy/index.json');break;}catch{await new Promise(r=>setTimeout(r,100));}}
  browser=await chromium.launch();const rows=new Map(),images=new Map(),errors=[];
  async function client(){const context=await browser.newContext(),page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept(d.type()==='prompt'?'energy':undefined));
   await page.route('https://lfxajxconibunipejdjz.supabase.co/**',async route=>{
    const req=route.request(),u=new URL(req.url()),path=u.pathname,headers={'access-control-allow-origin':'*'};
    const reply=(v,status=200)=>route.fulfill({status,headers,contentType:'application/json',body:JSON.stringify(v)});
    if(req.method()==='OPTIONS')return route.fulfill({headers:{...headers,'access-control-allow-headers':'*','access-control-allow-methods':'*'}});
    if(path.startsWith('/auth/'))return reply({access_token:'test',refresh_token:'test',expires_at:9999999999,user:{id:'11111111-1111-4111-8111-111111111111'}});
    if(path.endsWith('/energy_unlock'))return reply(true);
    if(path.endsWith('/energy_edits')){const k=u.searchParams.get('day')+':'+u.searchParams.get('page');return reply(rows.has(k)?[rows.get(k)]:[]);}
    if(path.endsWith('/energy_save_edit')){const p=req.postDataJSON(),k='eq.'+p.p_day+':eq.'+p.p_page,old=rows.get(k);if((old?.version||0)!==p.p_expected_version)return reply({message:'edit_conflict'},409);const row={version:(old?.version||0)+1,payload:p.p_payload};rows.set(k,row);return reply(row);}
    if(path.startsWith('/storage/v1/object/public/'))return route.fulfill({headers,contentType:'image/png',body:images.get(path.replace('/public',''))});
    if(path.startsWith('/storage/v1/object/')){images.set(path,req.postDataBuffer());return reply({Key:'ok'});}
    return reply({message:'unexpected'},500);
   });
   await page.goto('http://127.0.0.1:8766/energy-weather.html');await page.waitForFunction(()=>document.getElementById('editStatus').textContent.includes('공유된 편집이 없습니다')||document.getElementById('editStatus').textContent.includes('공유된 편집 내용을'));return page;
  }
  const a=await client(),b=await client();await a.click('#edit');await a.waitForFunction(()=>editors[1].editing);
  await a.evaluate(()=>{editors[1].remember();editors[1].setLabel(0,'공유 저장 검증');const c=document.createElement('canvas');c.width=c.height=8;c.getContext('2d').fillRect(0,0,8,8);const p=editors[1].scene.panels[0];p.src=c.toDataURL();p.updated=true;p.custom=true;});
  await a.click('#saveLayout');await a.waitForFunction(()=>document.getElementById('editStatus').textContent.includes('공유 저장 완료'));
  await b.click('#edit');await b.waitForFunction(()=>editors[1].editing);await b.evaluate(()=>editors[1].setLabel(0,'충돌하면 보존'));await b.click('#saveLayout');await b.waitForFunction(()=>document.getElementById('editStatus').textContent.includes('다른 사람이 먼저'));
  assert.equal(await b.evaluate(()=>editors[1].labelValue(0)),'충돌하면 보존');assert.ok(await b.evaluate(()=>localStorage.getItem(editors[1].storageKey()).includes('충돌하면 보존')));
  await b.getByRole('button',{name:'공유본 다시 불러오기',exact:true}).first().click();await b.waitForFunction(()=>editors[1].labelValue(0)==='공유 저장 검증');
  assert.match(await b.evaluate(()=>editors[1].scene.panels[0].src),/^https:/);
  const download=b.waitForEvent('download');await b.click('#pdfAll');assert.ok((await download).suggestedFilename().endsWith('_01-02.pdf'));
  await b.click('#reset');await b.click('#saveLayout');await b.waitForFunction(()=>document.getElementById('editStatus').textContent.includes('공유 저장 완료'));
  await a.reload();await a.waitForFunction(()=>document.getElementById('editStatus').textContent.includes('공유된 편집 내용을'));assert.equal(await a.evaluate(()=>editors[1].labelValue(0)===editors[1].original.labels[0].text),true);
  assert.deepEqual(errors,[]);console.log('Shared browser: two clients, conflict preservation, image CORS/PDF and shared reset passed');
 }finally{await browser?.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
