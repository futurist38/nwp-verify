/* Map-first overview. Only real archived KMA hourly records; never interpolate,
   substitute a neighbouring city, or skip missing values to find an older issue. */
(function (root) {
  "use strict";
  const CITIES = [
    {name:"서울",stn:108,point:[273.4,214.6]},
    {name:"인천",stn:112,point:[226.8,230.1]},
    {name:"수원",stn:119,point:[280,270]},
    {name:"원주",stn:114,point:[407.3,254.7]},
    {name:"강릉",stn:105,point:[535.3,182.4],reference:true},
    {name:"대전",stn:133,point:[328.5,420.4]},
    {name:"청주",stn:131,point:[350,365]},
    {name:"전주",stn:146,point:[285,514]},
    {name:"광주",stn:156,point:[260.1,626.3]},
    {name:"대구",stn:143,point:[507.6,504.2]},
    {name:"부산",stn:159,point:[563.1,636.3]},
    {name:"제주",stn:184,point:[205.6,912.3]},
  ];
  const CITY_NAMES=CITIES.map(c=>c.name);
  const POINTS=Object.fromEntries(CITIES.map(c=>[c.name,c.point]));
// Preferred directions are relative to each unchanged geographic station point.
const DIRECTIONS={서울:[0,-1],인천:[-1,0],수원:[0,1],원주:[1,0],강릉:[1,-1],대전:[-1,0],청주:[1,-1],전주:[-1,0],광주:[-1,0],대구:[1,0],부산:[1,1],제주:[0,-1]};
const MOBILE_LANES={서울:[19,8],인천:[19,24.8],수원:[19,41.6],원주:[81,24.8],강릉:[81,8],대전:[19,58.4],청주:[81,41.6],전주:[19,75.2],광주:[19,92],대구:[81,58.4],부산:[81,75.2],제주:[81,92]};
let lastMapLayout=null;
function mapLayout(w,h,narrow=false){
 if(lastMapLayout&&lastMapLayout.w===w&&lastMapLayout.h===h&&lastMapLayout.narrow===narrow)return lastMapLayout.boxes;
 const compact=w<700,cw=compact?104:128,ch=compact?78:84,gap=6;
 const scale=Math.min(w/710,h/905),ox=(w-710*scale)/2,oy=(h-905*scale)/2;
 const points=Object.fromEntries(CITY_NAMES.map(name=>[name,{x:ox+(POINTS[name][0]-35)*scale,y:oy+(POINTS[name][1]-75)*scale}]));
 if(narrow){const cw=w<334?104:112,ch=96;
  const boxes=CITY_NAMES.map(name=>{const [xp,yp]=MOBILE_LANES[name],p=points[name],x=w*xp/100,y=h*yp/100,l=x-cw/2,r=x+cw/2,t=y-ch/2,b=y+ch/2,endX=Math.max(l,Math.min(r,p.x)),endY=Math.max(t,Math.min(b,p.y));return {name,x,y,l,r,t,b,px:p.x,py:p.y,endX,endY,leader:Math.hypot(endX-p.x,endY-p.y),cw,ch};});
  lastMapLayout={w,h,narrow,boxes};return boxes;
 }
 const placed=[];
 // The crowded capital-region labels are placed first. Candidate search minimizes
 // leader length, then favors each city's geographic direction; no fixed lanes.
 for(const name of CITY_NAMES){const p=points[name],[dx,dy]=DIRECTIONS[name];let best=null;
  for(let y=ch/2+5;y<=h-ch/2-5;y+=6)for(let x=cw/2+5;x<=w-cw/2-5;x+=6){
   const l=x-cw/2,r=x+cw/2,t=y-ch/2,b=y+ch/2;
   if(placed.some(a=>!(r+gap<=a.l||a.r+gap<=l||b+gap<=a.t||a.b+gap<=t)))continue;
   if(Object.values(points).some(a=>a.x>l-3&&a.x<r+3&&a.y>t-3&&a.y<b+3))continue;
   if(name==='서울'&&b>p.y-4)continue;
   if(name==='인천'&&r>p.x-4)continue;
   const endX=Math.max(l,Math.min(r,p.x)),endY=Math.max(t,Math.min(b,p.y));
   const leader=Math.hypot(endX-p.x,endY-p.y),distance=Math.hypot(x-p.x,y-p.y);
   const direction=((x-p.x)*dx+(y-p.y)*dy)/(distance||1);
   const score=leader*3+distance*.16+(1-direction)*12;
   if(!best||score<best.score)best={name,x,y,l,r,t,b,px:p.x,py:p.y,endX,endY,leader,score,cw,ch};
  }
  if(!best)throw new Error('Map labels need a larger canvas: '+name);placed.push(best);
 }
 lastMapLayout={w,h,narrow,boxes:placed};
 return placed;
}
  const finite = x => typeof x === "number" && Number.isFinite(x);
  const esc = s => String(s ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const stamp = t => /^\d{10}$/.test(t||"") ? `${t.slice(0,4)}.${t.slice(4,6)}.${t.slice(6,8)} ${t.slice(8)}:00` : "없음";
  const signed = d => (d > 0 ? "+" : "") + Number(d.toFixed(1));
  const temp = v => finite(v) ? `${Number(v.toFixed(1))}°` : "—";
  const tone = d => d > 0 ? "warm" : d < 0 ? "cool" : "flat";
  function emoji(wx) {
    if (!wx) return "—";
    if ((wx.label||"").includes("비/눈")) return "🌨️";
    if ((wx.label||"").includes("눈")) return "❄️";
    if ((wx.label||"").includes("소나기")) return "🌦️";
    return {clear:"☀️",partly:"⛅",overcast:"☁️",rain:"🌧️"}[wx.code] || "—";
  }
  function latestPair(entries) {
    const sorted = [...entries].filter(e=>e.kind==="short" && /^\d{10}$/.test(e.issue))
      .sort((a,b)=>b.issue.localeCompare(a.issue));
    const latest = sorted[0] || null;
    return {latest, previous: sorted.find(e=>e.issue!==latest?.issue) || null};
  }
  function hours(doc) {
    return [...new Set(Object.values(doc?.cities||{}).flatMap(days=>Object.values(days)
      .flatMap(day=>Object.keys(day.hourly||{}))))].filter(t=>/^\d{10}$/.test(t) && t>doc.issue).sort();
  }
  const record = (doc,city,time) => doc?.cities?.[city]?.[time?.slice(0,8)]?.hourly?.[time] || null;
  function compare(a,b) {
    return {delta:finite(a?.temp)&&finite(b?.temp) ? Math.round((b.temp-a.temp)*10)/10 : null,
      changed:a?.wx?.key && b?.wx?.key ? a.wx.key!==b.wx.key : null};
  }
  function summary(latest, previous, time) {
    const comparisons=CITIES.filter(c=>!c.reference).map(c=>compare(record(previous,c.name,time),record(latest,c.name,time)));
    const ds=comparisons.map(c=>c.delta).filter(finite);
    const skies=comparisons.filter(c=>c.changed!==null);
    return {min:ds.length?Math.min(...ds):null,max:ds.length?Math.max(...ds):null,
      tempCount:ds.length,skyCount:skies.length,changed:skies.filter(c=>c.changed).length};
  }
  function currentKey(ms=Date.now()) {
    return new Date(ms+9*3600e3).toISOString().slice(0,13).replace(/[-T:]/g,"");
  }
  // Pick one observation hour for the whole view, never a different old hour
  // for each city. A missing value at that hour remains explicitly missing.
  function observationHour(obs) {
    const arrays=Object.values(obs?.vars?.ta||{});
    for(let h=Math.max(0,...arrays.map(a=>a.length))-1;h>=0;h--)
      if(arrays.some(a=>finite(a[h]))) return h;
    return null;
  }
  function latestObservation(obs,stn,hour=observationHour(obs)) {
    const value=hour===null?null:obs?.vars?.ta?.[stn]?.[hour];
    return finite(value)?{temp:value,hour:String(hour).padStart(2,"0")}:null;
  }
  function forecastObservation(latest,obs,obsDay,city,hour=observationHour(obs)) {
    const observed=latestObservation(obs,city.stn,hour);
    const valid=hour===null?null:obsDay+String(hour).padStart(2,"0");
    const forecast=record(latest,city.name,valid);
    return {valid,observed,forecast,error:finite(forecast?.temp)&&finite(observed?.temp)
      ?Math.round((forecast.temp-observed.temp)*10)/10:null};
  }
  const api={CITIES,CITY_NAMES,POINTS,mapLayout,latestPair,hours,record,compare,summary,emoji,currentKey,observationHour,latestObservation,forecastObservation};
  if(typeof module!=="undefined" && module.exports) module.exports=api;
  root.WeatherOverview=api;
  if(!root.document) return;

  let generation=0,disconnectLayout=null;
  async function json(path) {
    const response=await fetch(path,{cache:"no-cache"});
    if(!response.ok) throw new Error(`수신 실패 (${response.status})`);
    return response.json();
  }
  api.mount=async function(manifest) {
    const host=document.getElementById("weatherOverview");
    if(!host) return;
    const ticket=++generation;
    if(disconnectLayout) {disconnectLayout();disconnectLayout=null;}
    host.setAttribute("aria-busy","true");
    let latest,previous=null,previousError=false,obs=null;
    const obsDay=(manifest?.obs_dates||[]).slice().sort().at(-1);
    try {
      const index=await json("forecast_compare/index.json");
      const pair=latestPair(index.issues||[]);
      if(!pair.latest) throw new Error("저장된 단기예보가 없습니다");
      const load=e=>json("forecast_compare/"+e.file+"?v="+encodeURIComponent(e.rev||""));
      [latest,previous,obs]=await Promise.all([
        load(pair.latest),
        pair.previous?load(pair.previous).catch(()=>{previousError=true;return null;}):null,
        obsDay?json(`obs/${obsDay}.json`).catch(()=>null):null,
      ]);
      if(ticket!==generation) return;
      if(latest.issue!==pair.latest.issue || latest.kind!=="short") throw new Error("발표 자료가 목록과 일치하지 않습니다");
      if(previous && (previous.issue!==pair.previous.issue || previous.kind!=="short")) {previous=null;previousError=true;}
      const times=hours(latest);
      if(!times.length) throw new Error("최신 발표에 시간별 예보가 없습니다");
      let step=Math.max(0,times.findIndex(t=>t>=currentKey())),selected="원주",mode="changes";
      const allPast=times.at(-1)<currentKey();
      if(allPast) step=times.length-1;
      const previousLabel=pair.previous?stamp(pair.previous.issue):"저장된 이전 발표 없음";
      host.innerHTML=`<div class="ov-intro"><div><span class="ov-badge">KMA FORECAST</span><h2>전국 날씨, 넓게 한눈에.</h2><p>12개 도시 · 최신 발표 중심 · 직전 저장 발표와 같은 시각 비교</p></div><div class="ov-source"><strong>${stamp(latest.issue)} 발표</strong><br>이전 ${previousLabel}<br>모든 시각 KST · 저장 자료 기준</div></div>
        <p class="ov-notice" id="ov-notice" role="status">${allPast?"최신 저장 예보의 유효기간이 지났습니다. 마지막 자료를 표시합니다. ":""}${previousError?"직전 발표 수신 실패 — 최신 예보만 표시합니다. 다시 시도하면 재수신합니다.":!previous?"직전 저장 발표가 없어 변화는 비교 불가입니다.":"최신·직전 저장 단기예보의 동일 유효시각 비교입니다."}</p>
        <div class="ov-status"><div><small>선택 시각 · 주요 11도시 + 강릉 참조</small><strong id="ov-status-time"></strong></div><div><small>이전 발표 대비 기온 변화</small><strong id="ov-temp-summary"></strong></div><div><small>날씨 개황이 바뀐 곳</small><strong id="ov-sky-summary"></strong></div></div>
        <div class="ov-content"><section class="ov-panel"><div class="ov-map-top"><h3>전국 예보 지도</h3><div class="ov-seg"><button id="ov-changes" type="button" aria-pressed="true">이전 예보 대비</button><button id="ov-weather" type="button" aria-pressed="false">날씨만 보기</button></div></div><div class="ov-map" id="ov-map" role="group" aria-label="도시를 선택하는 대한민국 예보 지도"><img src="overview-map.svg" alt="대한민국 해안선 및 시도 경계"><span class="ov-map-stamp">최신 기상청 단기예보 · 관측값 아님</span><svg id="ov-leaders" aria-hidden="true"></svg><div id="ov-markers"></div></div><div class="ov-legend">아래 굵은 숫자 = 직전 대비 기온 변화 · ● = 개황 변경 · 점은 실제 대표 지점<br>점선 카드 = 강릉 참조 (요약 제외)</div><div class="ov-timeline"><div><strong id="ov-selected-time"></strong><span><button id="ov-prev" type="button" aria-label="이전 시각">←</button><button id="ov-next" type="button" aria-label="다음 시각">→</button></span></div><input id="ov-slider" type="range" min="0" step="1" aria-label="예보 유효시각"><p id="ov-range"></p></div></section><aside class="ov-panel ov-detail" id="ov-detail" aria-live="polite"></aside></div>
        <details class="ov-help"><summary>자료와 비교 기준</summary><p>기상청 단기예보 TMP·SKY·PTY·POP 시간별 원자료를 표시합니다. 지도는 최신 발표와 바로 전 <b>저장된</b> 단기 발표를 비교합니다. 수신하지 않은 발표를 추정하거나, 한 도시의 누락을 더 오래된 발표·인근 도시로 대신하지 않습니다. 발표 간격은 수신 상황에 따라 다릅니다.</p><p>변화는 관측 오차나 예측 정확도가 아닙니다. 누락은 ‘— / 비교 불가’로 표시하고 요약에서 제외합니다. 강릉은 참조이며 요약에서는 제외하되 모든 상세 탭에 자료를 유지합니다. 지도 점은 대표 지점이며 카드는 겹침 방지를 위해 이동했습니다. 관측값은 선택 도시 상세에서 시각과 함께 별도로 표시합니다.</p><p>예보 비교 탭의 어제·오늘 바로가기와 날짜·시각 직접 선택, NWP·예보-관측 탭도 그대로 사용할 수 있습니다.</p></details><button type="button" id="ov-retry" class="ov-retry">최신 자료 다시 불러오기</button>`;
      const $=id=>document.getElementById("ov-"+id);
      function renderDetail(time) {
        const city=CITIES.find(c=>c.name===selected),b=record(latest,selected,time),a=record(previous,selected,time),cmp=compare(a,b);
        const matched=forecastObservation(latest,obs,obsDay,city),observation=matched.observed;
        $("detail").innerHTML=`<div class="ov-city-head"><div><small>${city.reference?"참조 도시 · 요약 제외":"선택한 주요 도시"}</small><h3>${selected}</h3></div><span class="ov-emoji" aria-hidden="true">${emoji(b?.wx)}</span></div><p class="ov-detail-time">${stamp(time)} 예보</p><div class="ov-temp">${temp(b?.temp)}<small>C</small></div><p>${esc(b?.wx?.label||"개황 자료 없음")}</p>${!b?"<p class='ov-missing'>이 발표·시각의 자료가 없습니다. 다른 도시나 과거 발표로 대신하지 않습니다.</p>":""}<div class="ov-change"><small>직전 저장 발표보다 무엇이 달라졌나요?</small><div><span>기온</span><strong class="ov-${tone(cmp.delta)}">${cmp.delta===null?"비교 불가":`${temp(a.temp)} → ${temp(b.temp)} · ${signed(cmp.delta)}°`}</strong></div><div><span>날씨 개황</span><strong>${cmp.changed===null?"비교 불가":cmp.changed?`${esc(a.wx.label)} → ${esc(b.wx.label)}`:"변화 없음"}</strong></div><p>${previousLabel}<br>→ ${stamp(latest.issue)} 발표</p></div><div class="ov-rain"><span>강수확률</span><strong>${finite(b?.pop)?b.pop+"%":"—"}</strong></div><div class="ov-bar"><span style="width:${finite(b?.pop)?Math.max(0,Math.min(100,b.pop)):0}%"></span></div><h4>이후 시간대</h4><div class="ov-hours">${times.slice(step,step+4).map(t=>{const r=record(latest,selected,t);return `<div><small>${t.slice(6,8)}일 ${t.slice(8)}시</small><span aria-label="${esc(r?.wx?.label||"개황 자료 없음")}">${emoji(r?.wx)}</span><strong>${temp(r?.temp)}</strong></div>`;}).join("")}</div><div class="ov-observation"><strong>최신 ASOS 관측 · ${city.stn}</strong><p>${observation?`${stamp(obsDay+observation.hour)} · ${temp(observation.temp)}C`:`${matched.valid?stamp(matched.valid)+" · ":""}이 도시의 해당 시각 자료 없음`}</p><small>모든 도시 동일 관측시각 · 과거 값으로 채우지 않음</small><div class="ov-observation-error"><span>최신 발표 예보 − 관측</span><strong class="ov-${tone(matched.error)}">${matched.error===null?"비교 불가":signed(matched.error)+"°"}</strong></div><small>${matched.error===null?"동일 유효시각 자료 없음":"동일 유효시각 · "+stamp(matched.valid)}</small></div>`;
      }
      function drawLayout() {
        if(ticket!==generation) return;
        const stage=$("map"),w=stage.clientWidth,h=stage.clientHeight;
        if(!w||!h) return; // Hidden tab: ResizeObserver lays out when shown again.
        const narrow=typeof root.matchMedia==="function"&&root.matchMedia("(max-width: 700px)").matches;
        stage.setAttribute("data-layout",narrow?"lanes":"geographic");
        const boxes=mapLayout(w,h,narrow);
        boxes.forEach(p=>{const el=host.querySelector(`[data-city="${p.name}"]`);if(el?.style){
          el.style.left=p.x+"px";el.style.top=p.y+"px";el.style.width=p.cw+"px";el.style.height=p.ch+"px";
        }});
        $("leaders").setAttribute("viewBox",`0 0 ${w} ${h}`);
        $("leaders").innerHTML=boxes.map(p=>`<line x1="${p.px}" y1="${p.py}" x2="${p.endX}" y2="${p.endY}"/><circle cx="${p.px}" cy="${p.py}" r="4"/>`).join("");
      }
      function render() {
        const time=times[step],s=summary(latest,previous,time);
        $("status-time").textContent=stamp(time);
        $("temp-summary").innerHTML=s.tempCount?`${signed(s.min)} ~ ${signed(s.max)}° <small>/ 비교 ${s.tempCount}도시</small>`:"비교 불가";
        $("sky-summary").innerHTML=s.skyCount?`${s.changed?s.changed+"개 도시":"변경 없음"} <small>/ 비교 ${s.skyCount}도시</small>`:"비교 불가";
        $("selected-time").textContent=stamp(time)+" 예보";
        $("slider").max=times.length-1;$("slider").value=step;$("slider").setAttribute("aria-valuetext",stamp(time));
        $("prev").disabled=step===0;$("next").disabled=step===times.length-1;
        $("range").textContent=stamp(times[0])+" ~ "+stamp(times.at(-1));
        $("markers").innerHTML=CITIES.map(c=>{
          const b=record(latest,c.name,time),cmp=compare(record(previous,c.name,time),b);
          const change=cmp.delta===null?"비교 자료 없음":signed(cmp.delta)+"° 직전 대비";
          return `<button type="button" class="ov-marker ${selected===c.name?"ov-selected":""} ${c.reference?"ov-reference":""}" data-city="${c.name}" aria-pressed="${selected===c.name}" aria-label="${c.name}${c.reference?" 참조":""}, ${esc(b?.wx?.label||"개황 자료 없음")}, ${temp(b?.temp)}, ${change}"><span class="ov-marker-name">${c.name}${c.reference?'<small> · 참조</small>':""}${cmp.changed&&mode==="changes"?'<i aria-label="개황 변경">●</i>':""}</span><span class="ov-marker-weather">${finite(b?.temp)?`<span aria-hidden="true">${emoji(b?.wx)}</span> ${temp(b.temp)}`:'<span class="ov-marker-missing">자료 없음</span>'}</span><span class="ov-marker-delta ov-${tone(cmp.delta)}">${esc(mode==="changes"?change:b?.wx?.label||"자료 없음")}</span></button>`;
        }).join("");
        host.querySelectorAll(".ov-marker").forEach(el=>{
          el.onclick=()=>{selected=el.dataset.city;render();host.querySelector(`[data-city="${selected}"]`)?.focus();};
        });
        drawLayout();
        renderDetail(time);
      }
      $("slider").oninput=e=>{step=Number(e.target.value);render();};
      $("prev").onclick=()=>{step=Math.max(0,step-1);render();};
      $("next").onclick=()=>{step=Math.min(times.length-1,step+1);render();};
      ["changes","weather"].forEach(id=>$(id).onclick=()=>{mode=id;["changes","weather"].forEach(x=>$(x).setAttribute("aria-pressed",x===mode));render();});
      $("retry").onclick=()=>api.mount(manifest);
      render();
      const observer=typeof root.ResizeObserver==="function"?new root.ResizeObserver(drawLayout):null;
      observer?.observe($("map"));
      root.addEventListener?.("resize",drawLayout);
      disconnectLayout=()=>{observer?.disconnect();root.removeEventListener?.("resize",drawLayout);};
    } catch(error) {
      if(ticket!==generation) return;
      host.innerHTML=`<h2>날씨 한눈에</h2><p role="status">예보 자료를 표시할 수 없습니다: ${esc(error.message)}</p><button type="button" id="ov-retry">다시 시도</button><p>관측·예보-관측·예보 비교 탭은 계속 사용할 수 있습니다.</p>`;
      document.getElementById("ov-retry").onclick=()=>api.mount(manifest);
    } finally { if(ticket===generation) host.setAttribute("aria-busy","false"); }
  };
})(typeof window!=="undefined"?window:globalThis);
