/* Map-first overview. Only real archived KMA hourly records; never interpolate,
   substitute a neighbouring city, or skip missing values to find an older issue. */
(function (root) {
  "use strict";
  const CITIES = [
    {name:"서울",stn:108,point:[273.4,214.6],label:[348,183]},
    {name:"인천",stn:112,point:[226.8,230.1],label:[157,285]},
    {name:"원주",stn:114,point:[407.3,254.7],label:[460,300]},
    {name:"강릉",stn:105,point:[535.3,182.4],label:[590,175],reference:true},
    {name:"대전",stn:133,point:[328.5,420.4],label:[328,421]},
    {name:"대구",stn:143,point:[507.6,504.2],label:[526,497]},
    {name:"광주",stn:156,point:[260.1,626.3],label:[234,638]},
    {name:"부산",stn:159,point:[563.1,636.3],label:[591,663]},
    {name:"제주",stn:184,point:[205.6,912.3],label:[205,895]},
  ];
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
  function latestObservation(obs,stn) {
    const arr=obs?.vars?.ta?.[stn]||[];
    for(let h=arr.length-1;h>=0;h--) if(finite(arr[h])) return {temp:arr[h],hour:String(h).padStart(2,"0")};
    return null;
  }
  const api={CITIES,latestPair,hours,record,compare,summary,emoji,currentKey,latestObservation};
  if(typeof module!=="undefined" && module.exports) module.exports=api;
  root.WeatherOverview=api;
  if(!root.document) return;

  let generation=0;
  async function json(path) {
    const response=await fetch(path,{cache:"no-cache"});
    if(!response.ok) throw new Error(`수신 실패 (${response.status})`);
    return response.json();
  }
  api.mount=async function(manifest) {
    const host=document.getElementById("weatherOverview");
    if(!host) return;
    const ticket=++generation;
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
      host.innerHTML=`<div class="ov-intro"><div><span class="ov-badge">KMA FORECAST</span><h2>날씨, 그리고 달라진 예보.</h2><p>전국 날씨를 보고, 직전 저장 발표와 달라진 곳을 확인하세요.</p></div><div class="ov-source"><strong>${stamp(latest.issue)} 발표</strong><br>이전 ${previousLabel}<br>모든 시각 KST · 저장 자료 기준</div></div>
        <p class="ov-notice" id="ov-notice" role="status">${allPast?"최신 저장 예보의 유효기간이 지났습니다. 마지막 자료를 표시합니다. ":""}${previousError?"직전 발표 수신 실패 — 최신 예보만 표시합니다. 다시 시도하면 재수신합니다.":!previous?"직전 저장 발표가 없어 변화는 비교 불가입니다.":"최신·직전 저장 단기예보의 동일 유효시각 비교입니다."}</p>
        <div class="ov-status"><div><small>선택 시각 · 주요 8도시 + 강릉 참조</small><strong id="ov-status-time"></strong></div><div><small>이전 발표 대비 기온 변화</small><strong id="ov-temp-summary"></strong></div><div><small>날씨 개황이 바뀐 곳</small><strong id="ov-sky-summary"></strong></div></div>
        <div class="ov-content"><section class="ov-panel"><div class="ov-map-top"><h3>전국 예보 지도</h3><div class="ov-seg"><button id="ov-changes" type="button" aria-pressed="true">이전 예보 대비</button><button id="ov-weather" type="button" aria-pressed="false">날씨만 보기</button></div></div><div class="ov-map"><img src="overview-map.svg" alt="" aria-hidden="true"><span class="ov-map-stamp">최신 기상청 단기예보 · 관측값 아님</span><svg viewBox="35 75 710 905" role="group" aria-label="도시를 선택하는 대한민국 예보 지도"><g id="ov-markers"></g></svg></div><div class="ov-legend">아래 굵은 숫자 = 이전 대비 기온 변화 · ● = 개황 변경<br>점선 카드 = 강릉 참조 (요약 제외)</div><div class="ov-timeline"><div><strong id="ov-selected-time"></strong><span><button id="ov-prev" type="button" aria-label="이전 시각">←</button><button id="ov-next" type="button" aria-label="다음 시각">→</button></span></div><input id="ov-slider" type="range" min="0" step="1" aria-label="예보 유효시각"><p id="ov-range"></p></div></section><aside class="ov-panel ov-detail" id="ov-detail" aria-live="polite"></aside></div>
        <details class="ov-help"><summary>자료와 비교 기준</summary><p>기상청 단기예보 TMP·SKY·PTY·POP 시간별 원자료를 표시합니다. 지도는 최신 발표와 바로 전 <b>저장된</b> 단기 발표를 비교합니다. 수신하지 않은 발표를 추정하거나, 한 도시의 누락을 더 오래된 발표·인근 도시로 대신하지 않습니다. 발표 간격은 수신 상황에 따라 다릅니다.</p><p>변화는 관측 오차나 예측 정확도가 아닙니다. 누락은 ‘— / 비교 불가’로 표시하고 요약에서 제외합니다. 강릉은 참조이며 요약에서는 제외하되 모든 상세 탭에 자료를 유지합니다. 지도 점은 대표 지점이며 카드는 겹침 방지를 위해 이동했습니다. 관측값은 선택 도시 상세에서 시각과 함께 별도로 표시합니다.</p><p>예보 비교 탭의 어제·오늘 비교 기본값과 NWP·예보-관측 탭은 그대로 사용할 수 있습니다.</p></details><button type="button" id="ov-retry" class="ov-retry">최신 자료 다시 불러오기</button>`;
      const $=id=>document.getElementById("ov-"+id);
      function renderDetail(time) {
        const city=CITIES.find(c=>c.name===selected),b=record(latest,selected,time),a=record(previous,selected,time),cmp=compare(a,b);
        const observation=latestObservation(obs,city.stn);
        $("detail").innerHTML=`<div class="ov-city-head"><div><small>${city.reference?"참조 도시 · 요약 제외":"선택한 주요 도시"}</small><h3>${selected}</h3></div><span class="ov-emoji" aria-hidden="true">${emoji(b?.wx)}</span></div><p class="ov-detail-time">${stamp(time)} 예보</p><div class="ov-temp">${temp(b?.temp)}<small>C</small></div><p>${esc(b?.wx?.label||"개황 자료 없음")}</p>${!b?"<p class='ov-missing'>이 발표·시각의 자료가 없습니다. 다른 도시나 과거 발표로 대신하지 않습니다.</p>":""}<div class="ov-change"><small>직전 저장 발표보다 무엇이 달라졌나요?</small><div><span>기온</span><strong class="ov-${tone(cmp.delta)}">${cmp.delta===null?"비교 불가":`${temp(a.temp)} → ${temp(b.temp)} · ${signed(cmp.delta)}°`}</strong></div><div><span>날씨 개황</span><strong>${cmp.changed===null?"비교 불가":cmp.changed?`${esc(a.wx.label)} → ${esc(b.wx.label)}`:"변화 없음"}</strong></div><p>${previousLabel}<br>→ ${stamp(latest.issue)} 발표</p></div><div class="ov-rain"><span>강수확률</span><strong>${finite(b?.pop)?b.pop+"%":"—"}</strong></div><div class="ov-bar"><span style="width:${finite(b?.pop)?Math.max(0,Math.min(100,b.pop)):0}%"></span></div><h4>이후 시간대</h4><div class="ov-hours">${times.slice(step,step+4).map(t=>{const r=record(latest,selected,t);return `<div><small>${t.slice(6,8)}일 ${t.slice(8)}시</small><span aria-label="${esc(r?.wx?.label||"개황 자료 없음")}">${emoji(r?.wx)}</span><strong>${temp(r?.temp)}</strong></div>`;}).join("")}</div><div class="ov-observation"><strong>최근 ASOS 관측 · ${city.stn}</strong><p>${observation?`${stamp(obsDay+observation.hour)} · ${temp(observation.temp)}C`:"이 도시의 최신 관측 자료 없음"}</p><small>예보 변화와 별개인 실측값</small></div>`;
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
          const b=record(latest,c.name,time),cmp=compare(record(previous,c.name,time),b),p=c.label;
          const change=cmp.delta===null?"비교 불가":cmp.delta===0?"변화 없음":signed(cmp.delta)+"°";
          return `<g class="ov-marker ${selected===c.name?"ov-selected":""} ${c.reference?"ov-reference":""}" data-city="${c.name}" tabindex="0" role="button" aria-pressed="${selected===c.name}" aria-label="${c.name}${c.reference?" 참조":""}, ${esc(b?.wx?.label||"개황 자료 없음")}, ${temp(b?.temp)}, 이전 대비 ${change}"><line x1="${c.point[0]}" y1="${c.point[1]}" x2="${p[0]}" y2="${p[1]}"/><circle cx="${c.point[0]}" cy="${c.point[1]}" r="4" fill="#43877e"/><g transform="translate(${p[0]-73},${p[1]-44})"><rect width="146" height="88" rx="15"/><text x="15" y="24" fill="#425c68" font-size="17" font-weight="650">${c.name}${c.reference?'<tspan font-size="12"> · 참조</tspan>':""}</text>${cmp.changed&&mode==="changes"?'<circle cx="129" cy="19" r="4" fill="#ce9f4a"/>':""}<text x="15" y="56" font-size="26">${emoji(b?.wx)}</text><text x="60" y="56" fill="#173044" font-size="29" font-weight="700">${temp(b?.temp)}</text><text x="73" y="78" text-anchor="middle" class="ov-${tone(cmp.delta)}" font-size="${mode==="changes"?"19":"13"}" font-weight="${mode==="changes"?"800":"400"}">${esc(mode==="changes"?change:b?.wx?.label||"자료 없음")}</text></g></g>`;
        }).join("");
        host.querySelectorAll(".ov-marker").forEach(el=>{
          const choose=()=>{selected=el.dataset.city;render();};
          el.onclick=choose;
          el.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();choose();host.querySelector(`[data-city="${selected}"]`).focus();}};
        });
        renderDetail(time);
      }
      $("slider").oninput=e=>{step=Number(e.target.value);render();};
      $("prev").onclick=()=>{step=Math.max(0,step-1);render();};
      $("next").onclick=()=>{step=Math.min(times.length-1,step+1);render();};
      ["changes","weather"].forEach(id=>$(id).onclick=()=>{mode=id;["changes","weather"].forEach(x=>$(x).setAttribute("aria-pressed",x===mode));render();});
      $("retry").onclick=()=>api.mount(manifest);
      render();
    } catch(error) {
      if(ticket!==generation) return;
      host.innerHTML=`<h2>날씨 한눈에</h2><p role="status">예보 자료를 표시할 수 없습니다: ${esc(error.message)}</p><button type="button" id="ov-retry">다시 시도</button><p>관측·예보-관측·예보 비교 탭은 계속 사용할 수 있습니다.</p>`;
      document.getElementById("ov-retry").onclick=()=>api.mount(manifest);
    } finally { if(ticket===generation) host.setAttribute("aria-busy","false"); }
  };
})(typeof window!=="undefined"?window:globalThis);
