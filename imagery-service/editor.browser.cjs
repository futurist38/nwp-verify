const {chromium}=require('playwright');const {spawn,execFileSync}=require('node:child_process');const assert=require('node:assert/strict');const fs=require('node:fs');
(async()=>{
 const server=spawn('python',['-m','http.server','8765','--bind','127.0.0.1','--directory','energy_editor_stage'],{stdio:'ignore'});let browser;
 try{
  for(let i=0;i<50;i++){try{await fetch('http://127.0.0.1:8765/energy/index.json');break;}catch{await new Promise(r=>setTimeout(r,100));}}
  browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8765/energy-weather.html');await page.waitForFunction(()=>!document.getElementById('edit').disabled);await page.click('#edit');
  assert.ok(await page.locator('#paletteGrid button').count()>10);
  const locate=async(index)=>{const t=await page.evaluate(i=>editors[1].scene.labels[i],index),b=await page.locator('#editorCanvas').boundingBox();return {x:b.x+t.x*b.width/1920-10,y:b.y+t.y*b.height/1080};};
  const title=await locate(0);await page.mouse.dblclick(title.x,title.y);const input=page.locator('.inline-report-text');await input.fill('KPX 검토 완료');await input.evaluate(e=>e.setSelectionRange(4,6));await page.getByRole('button',{name:'빨강',exact:true}).first().click();await input.press('Enter');
  assert.equal(await page.evaluate(()=>editors[1].labelValue(0)),'KPX 검토 완료');assert.equal(await page.evaluate(()=>editors[1].scene.labelColors[0][4]),'#e60012');assert.equal(await page.evaluate(()=>editors[1].scene.labelColors[0][0]||null),null);
  await page.click('#saveLayout');await page.reload();await page.waitForFunction(()=>!document.getElementById('edit').disabled);assert.equal(await page.evaluate(()=>editors[1].labelValue(0)),'KPX 검토 완료');await page.click('#edit');
  const before=await page.evaluate(()=>editors[1].scene.groups.length);await page.locator('#paletteGrid button').first().click();await page.waitForFunction(n=>editors[1].scene.groups.length===n+1,before);await page.click('#copyObjects');await page.click('#pasteObjects');await page.waitForFunction(n=>editors[1].scene.groups.length===n+2,before);
  await page.locator('#editorCanvas').focus();await page.keyboard.press('Delete');assert.equal(await page.evaluate(()=>editors[1].scene.groups.length),before+1);await page.keyboard.press('Control+z');assert.equal(await page.evaluate(()=>editors[1].scene.groups.length),before+2);
  await page.click('[data-page="2"]');await page.click('#edit2');await page.evaluate(()=>{editors[2].setSelection([{type:'group',index:0}]);editors[2].controls();});await page.click('#copyObjects2');await page.click('#pasteObjects2');
  fs.mkdirSync('energy-browser-results',{recursive:true});const event=page.waitForEvent('download');await page.click('#pdf');const download=await event;await download.saveAs('energy-browser-results/report.pdf');
  await page.pdf({path:'energy-browser-results/print.pdf',preferCSSPageSize:true,printBackground:true});
  execFileSync('python',['-c',"import fitz; a=fitz.open('energy-browser-results/report.pdf');b=fitz.open('energy-browser-results/print.pdf');assert len(a)==len(b)==1;assert abs(a[0].rect.width/a[0].rect.height-16/9)<.001;assert abs(b[0].rect.width/b[0].rect.height-16/9)<.01;print('PDF and browser print: one 16:9 page')"],{stdio:'inherit'});
  await page.screenshot({path:'energy-browser-results/page2.png',fullPage:true});assert.deepEqual(errors,[]);console.log('Browser editing, partial color, persistence, clipboard, PDF and print passed');
 }finally{await browser?.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
