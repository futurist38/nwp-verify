/* 발표 시점 A/B의 같은 대상일 비교. 외부 라이브러리 없이 동작. */
(function (root) {
  "use strict";
  const COLORS = {same: "#ffffff", clear: "#fff6d5", partly: "#ebedef", overcast: "#cbd0d6", rain: "#dceffc"};
  const finite = v => typeof v === "number" && Number.isFinite(v);
  const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const dayLabel = d => `${d.slice(4,6)}/${d.slice(6,8)}`;
  const stamp = s => s ? `${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)} ${s.slice(8,10)}시` : "자료 없음";
  const dateKey = d => d.toISOString().slice(0,10).replace(/-/g, "");
  const asDate = d => new Date(`${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}T00:00:00Z`);
  const offsetDay = (d, n) => { const t = asDate(d); t.setUTCDate(t.getUTCDate()+n); return dateKey(t); };
  const kstToday = () => dateKey(new Date(Date.now()+9*3600000));
  const lastFriday = d => { const w=asDate(d).getUTCDay(); return offsetDay(d, -((w+2)%7 || 7)); };
  function range(a, b) { const out=[]; for(let d=a;d<=b;d=offsetDay(d,1)) out.push(d); return out; }
  function selectEntries(entries, cutoff, city) {
    const list = entries.filter(e => e.issue <= cutoff && e.cities.includes(city)).sort((a,b)=>b.issue.localeCompare(a.issue));
    const chosen = [list.find(e=>e.kind==="short"),
      list.find(e=>e.kind==="mid" && e.temperature_cities.includes(city)),
      list.find(e=>e.kind==="mid" && e.weather_cities.includes(city))].filter(Boolean);
    return [...new Map(chosen.map(e=>[e.file,e])).values()];
  }
  function assemble(docs, city) {
    const ordered = [...docs].sort((a,b)=>b.issue.localeCompare(a.issue));
    const dates = [...new Set(ordered.flatMap(d=>Object.keys(d.cities[city]||{})))].sort();
    const output={};
    for(const day of dates) {
      const get = (kind, field) => {
        for(const d of ordered.filter(x=>x.kind===kind)) {
          const v=d.cities[city]?.[day]?.[field];
          if(v) return {...v,issue:d.issue,kind:d.kind};
        }
        return null;
      };
      const pick = field => get("short",field) || get("mid",field);
      const wx = {am:pick("wx_am"),pm:pick("wx_pm"),day:null};
      if(!wx.am && !wx.pm) wx.day=get("mid","wx_day");
      output[day]={tmin:pick("tmin"),tmax:pick("tmax"),wx};
    }
    return output;
  }
  function compareWeather(a, b) {
    a=a?.wx||{}; b=b?.wx||{};
    const segment = (slot, before, after, resolution=false) => ({slot,a:before,b:after,
      state:resolution ? "resolution" : !before||!after ? "missing" : before.key===after.key ? "same":"changed",
      color:!resolution && before && after ? (before.key===after.key ? COLORS.same : COLORS[after.code]) : null});
    if(a.day || b.day) return [segment("day",a.day,b.day,Boolean((a.day && (b.am||b.pm)) || (b.day && (a.am||a.pm))))];
    return [segment("am",a.am,b.am),segment("pm",a.pm,b.pm)];
  }
  const delta = (a,b) => finite(a?.value)&&finite(b?.value) ? Math.round((b.value-a.value)*10)/10 : null;
  const api={COLORS,selectEntries,assemble,compareWeather,delta,lastFriday,range};
  if(typeof module!=="undefined" && module.exports) module.exports=api;
  if(!root.document) return;

  const $=id=>document.getElementById("fc-"+id);
  let index, refs=[], records={a:{},b:{}}, available=[], selected="", serial=0, initialized=false;
  const cache=new Map();
  async function json(url) {
    const r=await fetch(url,{cache:"no-cache"});
    if(!r.ok) throw new Error(`자료 요청 실패 (${r.status})`);
    return r.json();
  }
  async function load(e) {
    const key=e.file+"?v="+e.rev;
    if(!cache.has(key)) cache.set(key,json("forecast_compare/"+key).catch(err=>{cache.delete(key);throw err;}));
    return cache.get(key);
  }
  function options(el, values, format, want) {
    el.innerHTML=values.map(v=>`<option value="${esc(v)}">${esc(format(v))}</option>`).join("");
    if(values.includes(want)) el.value=want;
  }
  const refValue = side => $(side+"-date").value+$(side+"-time").value;
  function fillTimes(side, want) {
    const times=refs.filter(r=>r.startsWith($(side+"-date").value)).map(r=>r.slice(8));
    options($(side+"-time"),times,t=>`${t}시 기준`,times.includes(want)?want:times.at(-1));
  }
  function setRef(side, ref) {
    $(side+"-date").value=ref.slice(0,8); fillTimes(side,ref.slice(8));
  }
  function preset(mode) {
    const today=kstToday(), todayRefs=refs.filter(r=>r.startsWith(today));
    if(!todayRefs.length) { $("status").textContent="오늘 저장된 예보가 없습니다. 날짜 목록에서 저장된 시점을 선택해 주세요.";return; }
    const b=todayRefs.at(-1), ad=mode==="friday"?lastFriday(today):offsetDay(today,-1);
    const ar=refs.filter(r=>r.startsWith(ad) && r.slice(8)<=b.slice(8));
    if(!ar.length) { $("status").textContent=`${dayLabel(ad)}에 선택 가능한 예보가 없습니다.`; return; }
    setRef("a",ar.at(-1));setRef("b",b);update(true);
  }
  function source(rec) {
    if(!rec) return "자료 없음";
    const basis={TMN:"공식 최저",TMX:"공식 최고",TMP24:"24시간 기온 극값",MID:"공식 일 기온"}[rec.basis]||rec.basis;
    return `${rec.kind==="short"?"단기":"중기"} ${stamp(rec.issue)} · ${basis}`;
  }
  const temp = r => finite(r?.value)?`${r.value.toFixed(1).replace(/\.0$/, "")}℃`:"—";
  const deltaText = (a,b) => {const v=delta(a,b);return v===null?"비교 불가":v===0?"유지":`${v>0?"+":""}${v.toFixed(1).replace(/\.0$/, "")}℃`;};
  function wxText(w) {return w?.label||"자료 없음";}
  function labelState(s) {return s.state==="same"?"유지":s.state==="changed"?"변경":s.state==="resolution"?"일/오전·오후 단위 다름":"비교 자료 없음";}
  function showDetails(day) {
    selected=day;
    document.querySelectorAll("#fc-timeline [data-day]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.day===day)));
    const a=records.a[day]||{}, b=records.b[day]||{};
    let out=`<h3>${esc(dayLabel(day))} 상세 · ${esc($("city").value)}</h3><div class="fc-details-grid">`;
    for(const [key,name,cls] of [["tmax","최고기온","max"],["tmin","최저기온","min"]]) {
      out+=`<div class="fc-detail"><strong class="fc-${cls}">${name}</strong><div class="fc-values">${temp(a[key])} → ${temp(b[key])} <b>${deltaText(a[key],b[key])}</b></div><p>A ${esc(source(a[key]))}</p><p>B ${esc(source(b[key]))}</p></div>`;
    }
    out+="</div>";
    for(const s of compareWeather(a,b)) {
      const before=s.state==="resolution"?(a.wx?.day?wxText(a.wx.day):`오전 ${wxText(a.wx?.am)} / 오후 ${wxText(a.wx?.pm)}`):wxText(s.a);
      const after=s.state==="resolution"?(b.wx?.day?wxText(b.wx.day):`오전 ${wxText(b.wx?.am)} / 오후 ${wxText(b.wx?.pm)}`):wxText(s.b);
      const sourceText=w=>w?`${source(w)}${w.pop!==null ? ` · 강수확률 ${w.pop}%` : ""}`:"자료 없음";
      const sources=(r,w)=>s.state==="resolution"?[r.wx?.day,r.wx?.am,r.wx?.pm].filter(Boolean).map(sourceText).join(" / "):sourceText(w);
      out+=`<div class="fc-weather-detail" style="background:${s.color||"#f6f7f9"}"><strong>${s.slot==="am"?"오전":s.slot==="pm"?"오후":"하루"} · ${labelState(s)}</strong><span>${esc(before)} → ${esc(after)}</span><small>A ${esc(sources(a,s.a))}<br>B ${esc(sources(b,s.b))}</small></div>`;
    }
    $("detail").innerHTML=out;
  }
  function render() {
    if(!available.length) return;
    const days=range($("start").value,$("end").value);
    if(!days.length) {$("timeline").innerHTML="<p class='fc-empty'>종료일을 시작일 이후로 선택해 주세요.</p>";$("detail").innerHTML="";return;}
    const W=Math.max(700,days.length*110+72),L=56,R=16,T=32,B=266,H=306,cw=(W-L-R)/days.length;
    const values=days.flatMap(d=>[records.a[d]?.tmax?.value,records.a[d]?.tmin?.value,records.b[d]?.tmax?.value,records.b[d]?.tmin?.value]).filter(finite);
    const lo=values.length?Math.floor((Math.min(...values)-3)/5)*5:0;
    const hi=values.length?Math.ceil((Math.max(...values)+3)/5)*5:30;
    const y=v=>B-(v-lo)/(hi-lo)*(B-T), x=i=>L+(i+.5)*cw;
    let svg=`<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="최고 빨강, 최저 파랑. A 점선, B 실선. 날짜별 수치는 아래 상세에서 확인할 수 있습니다."><defs><pattern id="fc-missing" width="8" height="8" patternUnits="userSpaceOnUse"><rect width="8" height="8" fill="#fff"/><path d="M0 8L8 0" stroke="#e4e7eb" stroke-width="1"/></pattern></defs>`;
    days.forEach((d,i)=>{
      const segments=compareWeather(records.a[d],records.b[d]);
      segments.forEach((s,j)=>{const width=cw/segments.length;svg+=`<rect x="${L+i*cw+j*width}" y="${T}" width="${width}" height="${B-T}" fill="${s.color||"url(#fc-missing)"}"><title>${dayLabel(d)} ${s.slot==="am"?"오전":s.slot==="pm"?"오후":"하루"}: ${labelState(s)} · ${esc(wxText(s.a))} → ${esc(wxText(s.b))}</title></rect>`;});
      svg+=`<line x1="${L+i*cw}" x2="${L+i*cw}" y1="${T}" y2="${B}" stroke="#dde2e7" stroke-width=".6"/><text x="${x(i)}" y="291" text-anchor="middle">${dayLabel(d)}</text>`;
    });
    for(let v=lo;v<=hi;v+=5) svg+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="#c7cfd8" stroke-dasharray="2 4"/><text x="${L-10}" y="${y(v)+4}" text-anchor="end">${v}</text>`;
    svg+=`<text x="${L-10}" y="16" text-anchor="end">℃</text>`;
    for(const side of ["a","b"]) for(const metric of ["tmax","tmin"]) {
      const color=metric==="tmax"?"#be3543":"#216caa";
      let path="",active=false;
      days.forEach((d,i)=>{const v=records[side][d]?.[metric]?.value;if(finite(v)){path+=`${active?"L":"M"}${x(i)},${y(v)} `;active=true;}else active=false;});
      svg+=`<path data-series="${side}-${metric}" d="${path}" fill="none" stroke="${color}" stroke-width="${side==="a"?1.7:2.6}" ${side==="a"?'stroke-dasharray="6 5" opacity=".65"':""}/>`;
      days.forEach((d,i)=>{const rec=records[side][d]?.[metric];if(!finite(rec?.value))return;
        svg+=`<circle cx="${x(i)}" cy="${y(rec.value)}" r="${side==="a"?3:4}" stroke="${color}" stroke-width="1.5" fill="${side==="a"?"white":color}"><title>${dayLabel(d)} ${side.toUpperCase()} ${metric==="tmax"?"최고":"최저"} ${temp(rec)} · ${esc(source(rec))}</title></circle>`;
        if(side==="b") {const av=records.a[d]?.[metric]?.value;const anchor=finite(av)?(metric==="tmax"?Math.max(av,rec.value):Math.min(av,rec.value)):rec.value;svg+=`<text class="fc-temp-label" x="${x(i)}" y="${y(anchor)+(metric==="tmax"?-10:18)}" fill="${color}" text-anchor="middle">${rec.value}</text>`;}
      });
    }
    if(!values.length) svg+=`<text x="${W/2}" y="150" text-anchor="middle">선택 기간의 기온 자료 없음</text>`;
    svg+="</svg>";
    let rows="";
    for(const side of ["a","b"]) {
      rows+=`<div class="fc-weather-row" style="grid-template-columns:56px repeat(${days.length},1fr) 16px"><strong>${side.toUpperCase()} 개황</strong>`;
      for(const d of days) {
        const wx=records[side][d]?.wx||{}, segments=compareWeather(records.a[d],records.b[d]);
        const slots=wx.day?[["day",wx.day]]:[["am",wx.am],["pm",wx.pm]];
        rows+='<div class="fc-weather-cell">';
        for(const [slot,w] of slots) {
          const s=segments.find(t=>t.slot===slot);
          const fill=side==="b"&&s?s.color: w?"#fff":null;
          rows+=`<span class="${fill?"":"fc-missing"}" style="${fill?`background:${fill}`:""}" title="${esc(source(w))}"><small>${slot==="am"?"오전":slot==="pm"?"오후":"하루"}</small>${esc(wxText(w))}${side==="b"&&s?`<small>${labelState(s)}</small>`:""}</span>`;
        }
        rows+="</div>";
      }
      rows+="<span></span></div>";
    }
    rows+=`<div class="fc-day-buttons" style="grid-template-columns:56px repeat(${days.length},1fr) 16px"><span></span>`+days.map(d=>`<button type="button" data-day="${d}" aria-pressed="false" aria-label="${dayLabel(d)} 상세 보기">${dayLabel(d)} 상세</button>`).join("")+"<span></span></div>";
    $("timeline").innerHTML=`<div style="width:${W}px">${svg}${rows}</div>`;
    $("timeline").querySelectorAll("[data-day]").forEach(b=>b.onclick=()=>showDetails(b.dataset.day));
    showDetails(days.includes(selected)?selected:days[0]);
    const changes=days.flatMap(d=>compareWeather(records.a[d],records.b[d]));
    $("summary").textContent=`${days.length}일 비교 · 개황 변경 ${changes.filter(s=>s.state==="changed").length}구간 · 유지 ${changes.filter(s=>s.state==="same").length}구간 · 비교 불가 ${changes.filter(s=>["missing","resolution"].includes(s.state)).length}구간`;
  }
  async function update(resetRange=false) {
    const ticket=++serial;
    $("status").textContent="발표별 자료를 불러오는 중…";
    $("timeline").setAttribute("aria-busy","true");
    $("timeline").innerHTML="";$("detail").innerHTML="";$("summary").textContent="";
    try {
      const a=refValue("a"),b=refValue("b"),city=$("city").value;
      const entriesA=selectEntries(index.issues,a,city),entriesB=selectEntries(index.issues,b,city);
      const [da,db]=await Promise.all([Promise.all(entriesA.map(load)),Promise.all(entriesB.map(load))]);
      if(ticket!==serial) return;
      records={a:assemble(da,city),b:assemble(db,city)};
      available=Object.keys(records.a).filter(d=>records.b[d]).sort();
      const oldStart=resetRange?null:$("start").value,oldEnd=resetRange?null:$("end").value;
      options($("start"),available,dayLabel,oldStart); options($("end"),available,dayLabel,oldEnd||available.at(-1));
      $("start").disabled=$("end").disabled=!available.length;
      if(!available.length) {$("status").textContent="두 시점에 공통으로 저장된 예보 대상일이 없습니다. A·B 날짜나 도시를 바꿔 주세요.";return;}
      const stale=[...entriesA.map(e=>[a,e]),...entriesB.map(e=>[b,e])].some(([r,e])=>(asDate(r.slice(0,8))-asDate(e.issue.slice(0,8)))>86400000);
      $("status").textContent=`A ${stamp(a)} ↔ B ${stamp(b)} · KST${stale?" · 일부 자료는 기준일보다 2일 이상 이전 발표입니다. 상세의 실제 발표 시각을 확인하세요.":""}`;
      render();
    } catch(e) {
      if(ticket!==serial) return;
      available=[];$("start").disabled=$("end").disabled=true;
      $("status").innerHTML=`자료를 불러오지 못했습니다. <button id="fc-retry" type="button">다시 시도</button>`;
      $("retry").onclick=()=>index?update():init();
    } finally {if(ticket===serial) $("timeline").setAttribute("aria-busy","false");}
  }
  async function init() {
    if(initialized) return;
    initialized=true;
    try {
      index=await json("forecast_compare/index.json");
      if(index.schema!==1) throw new Error("지원하지 않는 자료 형식");
      refs=[...new Set(index.issues.map(e=>e.issue))].sort();
      if(!refs.length) {$("status").textContent="아직 비교할 발표 자료가 없습니다. 다음 자료 수집 후 표시됩니다.";return;}
      const cities=[...new Set(index.issues.flatMap(e=>e.cities))];
      options($("city"),cities,c=>c,cities.includes("서울")?"서울":cities[0]);
      const dates=[...new Set(refs.map(r=>r.slice(0,8)))].reverse();
      for(const side of ["a","b"]) {
        options($(side+"-date"),dates,d=>`${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}`);
        $(side+"-date").onchange=()=>{fillTimes(side,$(side+"-time").value);update(true);};
        $(side+"-time").onchange=()=>update(true);
      }
      const b=refs.at(-1), previous=offsetDay(b.slice(0,8),-1)+b.slice(8);
      setRef("b",b);setRef("a",refs.filter(r=>r<=previous).at(-1)||refs[0]);
      $("city").onchange=()=>update(true);
      $("start").onchange=()=>{if($("start").value>$("end").value)$("end").value=$("start").value;render();};
      $("end").onchange=()=>{if($("end").value<$("start").value)$("start").value=$("end").value;render();};
      $("yesterday").onclick=()=>preset("yesterday");$("friday").onclick=()=>preset("friday");
      $("swap").onclick=()=>{const a=refValue("a"),b=refValue("b");setRef("a",b);setRef("b",a);update();};
      update(true);
    } catch(e) {
      initialized=false; index=null;
      $("status").innerHTML='비교 자료를 불러오지 못했습니다. <button id="fc-retry" type="button">다시 시도</button>';
      $("retry").onclick=init;
    }
  }
  document.querySelector('#tabs [data-tab="compare"]').addEventListener("click",init);
  if(document.getElementById("tab-compare").classList.contains("on")) init();
})(typeof window!=="undefined"?window:globalThis);
