import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const code=fs.readFileSync(new URL('../supabase/functions/energy-imagery/index.ts',import.meta.url),'utf8');
const {parseTime,requestTime,satelliteFrame,warningChoices,warningImage,pm10Rows,handle}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const now=parseTime('202611041600');
test('KST query validates calendar, past range and each source cadence',()=>{
 assert.throws(()=>parseTime('202602300700'));
 assert.throws(()=>requestTime('forest_fire','202611040700',now));
 assert.throws(()=>requestTime('radar','202611041700',now));
 assert.throws(()=>requestTime('pm10','202609010700',now));
 for(const [kind,expected] of [['satellite','202611040706'],['radar','202611040705'],['warning','202611040707'],['pm10','202611040700'],['fog','202611040700']])assert.equal(requestTime(kind,'202611040707',now).at,parseTime(expected));
});
test('satellite time comes from KST metadata while image filename remains UTC',()=>{
 const row={tm:'202611040900',url:'/w/repositary/image/sat/gk2a/KO/gk2a_ami_le1b_rgb-s-daynight_ko020lc_202611040000.png'};
 assert.equal(satelliteFrame([row],parseTime(row.tm)).ms,parseTime(row.tm));
 assert.equal(satelliteFrame([row],parseTime('202611040902')),null);
 assert.equal(satelliteFrame([{...row,url:'https://invalid.example/image.png'}],parseTime(row.tm)),null);
});
test('fog uses ten-minute KST frames and rejects RGB images or missing requested frames',()=>{
 const row={tm:'202611050700',url:'/w/repositary/image/sat/gk2a/KO/gk2a_ami_le2_fog_ko020lc_202611042200.png'},at=parseTime(row.tm);
 assert.equal(requestTime('fog','202611050707',at+3600000).at,at);
 assert.equal(satelliteFrame([row],at,'fog').ms,at);
 assert.equal(satelliteFrame([row],at),null);
 assert.equal(satelliteFrame([row],at+600000,'fog'),null);
 assert.equal(satelliteFrame([{...row,url:row.url.replace('le2_fog','le1b_rgb-s-daynight')}],at,'fog'),null);
});
test('warning selects only preceding published notices and keeps effective times separate',()=>{
 const html='<option value="pwn:202611030100:9"><option value="met:202611030200:13"><option value="met:202611030000:12">';
 const [issue]=warningChoices(html,parseTime('202611030100'));assert.equal(issue.id,'met:202611030000:12');
 const graphic='<img src="/w/repositary/image/wrn/img/KTKO50_202611030000_108_12a.png"><img src="/w/repositary/image/wrn/img/KTKO50_202611030000_108_12.png"><strong>□ 발효시각</strong><p>2026년 11월 03일 05시 00분</p><strong>□ 해당구역</strong>';
 const result=warningImage(graphic,issue);assert.ok(result.url.endsWith('_12.png'));assert.deepEqual(result.effective,['2026-11-03T05:00:00+09:00']);
 assert.throws(()=>warningImage(graphic,{...issue,serial:'14'}));
});
function table(day,values){return '<table><thead><tr><th>[ PM10 : 1시간 평균값 ] '+day+'</th></tr></thead><tbody>'+Array.from({length:12},(_,i)=>'<tr><th scope="row">'+(108+i)+' 서울</th>'+values.map(v=>'<td>'+v+'</td>').join('')+'</tr>').join('')+'</tbody></table>';}
test('PM10 uses exact day/hour and midnight selects previous day 24:00',()=>{
 const values=Array.from({length:24},(_,i)=>i+1);values[5]='&nbsp;';
 const markup=table('2026년 11월 03일',values)+table('2026년 11월 02일',Array(24).fill(99));
 assert.equal(pm10Rows(markup,parseTime('202611030700'))[0].value,7);
 assert.equal(pm10Rows(markup,parseTime('202611040000'))[0].value,24);
 assert.throws(()=>pm10Rows(markup,parseTime('202611040700')));
 assert.throws(()=>pm10Rows(markup,parseTime('202611030600'))); // all stations missing, not zeros
 const mixed=markup.replace('<td>&nbsp;</td>','<td>42</td>');const rows=pm10Rows(mixed,parseTime('202611030600'));assert.equal(rows[0].value,42);assert.equal(rows[1].value,null);
});
test('request handler rejects unsupported methods/origins and missing auth before fetching sources',async()=>{
 assert.equal((await handle(new Request('https://example.test',{method:'GET'}),{})).status,405);
 assert.equal((await handle(new Request('https://example.test',{method:'POST',headers:{Origin:'https://elsewhere.example'}}),{})).status,403);
 assert.equal((await handle(new Request('https://example.test',{method:'POST'}),{})).status,401);
});

