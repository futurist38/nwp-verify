"use strict";

(() => {
  const STATUS = {
    success: {label:"정상", cls:"ok"},
    partial: {label:"부분수신", cls:"warn"},
    failed: {label:"실패", cls:"bad"}
  };
  const KIND = {model:"수치모델", forecast:"기상청 예보", observation:"관측", satellite:"위성·초단기", system:"시스템"};

  function $(id){ return document.getElementById(id); }
  function fmtKst(s){
    if(!s) return "—";
    const d = new Date(s);
    if(Number.isNaN(d.getTime())) return s;
    return new Intl.DateTimeFormat("ko-KR",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false,timeZone:"Asia/Seoul"}).format(d);
  }
  function fmtIssue(issue, source){
    if(!issue) return "—";
    const s=String(issue);
    if(/^\d{10,12}$/.test(s)){
      const y=s.slice(0,4),m=s.slice(4,6),d=s.slice(6,8),h=s.slice(8,10),mi=s.length>=12?s.slice(10,12):"00";
      const utc=["ecmwf","gfs","kim","upper_global","kim_upper","nowcast"].includes(source);
      return `${m}/${d} ${h}:${mi}${utc?" UTC":" KST"}`;
    }
    return s;
  }
  function ageText(s){
    const d=new Date(s); if(Number.isNaN(d.getTime())) return "";
    const min=Math.floor((Date.now()-d.getTime())/60000);
    if(min<60) return `${Math.max(0,min)}분 전`;
    if(min<1440) return `${Math.floor(min/60)}시간 전`;
    return `${Math.floor(min/1440)}일 전`;
  }
  function card(e){
    const st=STATUS[e.status]||STATUS.failed;
    const issue=fmtIssue(e.issue,e.source);
    return `<article class="ing-card ${st.cls}">
      <div class="ing-card-head"><strong>${e.label||e.source}</strong><span class="ing-state">${st.label}</span></div>
      <div class="ing-meta"><span>${KIND[e.kind]||e.kind||""}</span><span>최근 3일 실패 ${e.failures_3d||0}회</span></div>
      <dl><dt>자료/발표시각</dt><dd>${issue}</dd><dt>수신완료</dt><dd>${fmtKst(e.ended_kst)} · ${ageText(e.ended_kst)}</dd><dt>소요</dt><dd>${e.duration_s==null?"—":Math.round(e.duration_s)+"초"}</dd></dl>
    </article>`;
  }
  function row(e){
    const st=STATUS[e.status]||STATUS.failed;
    return `<tr><td>${fmtKst(e.ended_kst)}</td><td>${e.label||e.source}</td><td>${fmtIssue(e.issue,e.source)}</td>
      <td><span class="ing-badge ${st.cls}">${st.label}</span></td><td>${e.duration_s==null?"—":Math.round(e.duration_s)+"초"}</td><td>${e.summary||""}</td></tr>`;
  }
  async function load(){
    const root=$("ingestDashboard");
    if(!root) return;
    root.setAttribute("aria-busy","true");
    try{
      const r=await fetch("ops/ingest-status.json?ts="+Date.now(),{cache:"no-store"});
      if(!r.ok) throw new Error("HTTP "+r.status);
      const j=await r.json();
      const latest=(j.latest||[]);
      const events=(j.events||[]);
      $("ingestGenerated").textContent="대시보드 생성 "+fmtKst(j.generated_kst);
      $("ingestCards").innerHTML=latest.length?latest.map(card).join(""):'<p class="note">아직 수신 기록이 없습니다.</p>';
      $("ingestRows").innerHTML=events.length?events.slice(0,120).map(row).join(""):'<tr><td colspan="6">아직 기록이 없습니다.</td></tr>';
    }catch(err){
      $("ingestCards").innerHTML=`<p class="note">수신현황을 불러오지 못했습니다: ${String(err.message||err)}</p>`;
    }finally{ root.setAttribute("aria-busy","false"); }
  }
  document.addEventListener("DOMContentLoaded",()=>{
    load();
    const btn=document.querySelector('#tabs button[data-tab="status"]');
    if(btn) btn.addEventListener("click",load);
  });
})();