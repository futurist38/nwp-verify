"use strict";

(() => {
  const STATUS = {
    success: {label:"정상", cls:"ok"},
    partial: {label:"부분수신", cls:"warn"},
    failed: {label:"실패", cls:"bad"},
    missed: {label:"미수신", cls:"missed"}
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
  function matrix(j){
    const hours=j.hours||[], mat=j.matrix||{}, detail=j.matrix_detail||{}, expected=j.expected||{}, sched=j.schedule_meta||{};
    const latest=j.latest||[];
    if(!hours.length || !latest.length) return '<p class="note">시간별 이력이 아직 없습니다.</p>';
    const dayMarks=hours.map((h,i)=>{
      const d=new Date(h);
      const prev=i?new Date(hours[i-1]):null;
      const day=new Intl.DateTimeFormat("ko-KR",{month:"numeric",day:"numeric",timeZone:"Asia/Seoul"}).format(d);
      const show=!prev || new Intl.DateTimeFormat("ko-KR",{day:"numeric",timeZone:"Asia/Seoul"}).format(d)!==new Intl.DateTimeFormat("ko-KR",{day:"numeric",timeZone:"Asia/Seoul"}).format(prev);
      return `<span class="ing-daymark">${show?day:""}</span>`;
    }).join("");
    const rows=latest.map(e=>{
      const cells=hours.map(h=>{
        const due=!!expected[e.source]?.[h];
        const st=mat[e.source]?.[h]||(due?"expected":"none");
        const d=detail[e.source]?.[h];
        const cls=st==="success"?"ok":st==="partial"?"warn":st==="failed"?"bad":st==="missed"?"missed":st==="expected"?"expected":"none";
        let title;
        if(d) title=`${e.label} · 예정 슬롯 ${fmtKst(h)} · 실제 완료 ${fmtKst(d.ended_kst)} · ${STATUS[d.status]?.label||d.status}${d.issue?" · "+fmtIssue(d.issue,d.source):""}`;
        else if(st==="missed") title=`${e.label} · ${fmtKst(h)} 예정 · 유예시간 경과 후 미수신`;
        else if(st==="expected") title=`${e.label} · ${fmtKst(h)} 예정 · 아직 대기/유예시간`;
        else title=`${e.label} · 이 시간은 정규 수신 예정 슬롯 아님`;
        return `<button type="button" class="ing-cell ${cls}" data-source="${e.source}" data-hour="${h}" data-state="${st}" title="${title}" aria-label="${title}"></button>`;
      }).join("");
      const sl=sched[e.source]?.label ? `<small>${sched[e.source].label}</small>` : "";
      return `<div class="ing-rowlabel"><span>${e.label}</span>${sl}</div>${cells}`;
    }).join("");
    return `<div class="ing-matrix-wrap"><div class="ing-matrix" style="--cols:${hours.length}">
      <div class="ing-corner"></div>${dayMarks}
      ${rows}
    </div></div>
    <div class="ing-legend"><span><i class="expected"></i>수신 예정</span><span><i class="ok"></i>정상</span><span><i class="warn"></i>부분수신/지연</span><span><i class="bad"></i>실패</span><span><i class="missed"></i>예정시간 미수신</span><span><i class="none"></i>예정 없음</span></div>
    <div id="ingestCellDetail" class="ing-cell-detail">네모를 누르면 해당 시각의 상세 상태를 표시합니다.</div>`;
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
      $("ingestMatrix").innerHTML=matrix(j);
      $("ingestRows").innerHTML=events.length?events.slice(0,120).map(row).join(""):'<tr><td colspan="6">아직 기록이 없습니다.</td></tr>';
      $("ingestMatrix").querySelectorAll(".ing-cell").forEach(btn=>btn.addEventListener("click",()=>{
        const e=j.matrix_detail?.[btn.dataset.source]?.[btn.dataset.hour];
        const box=$("ingestCellDetail"); if(!box) return;
        if(!e){
          if(btn.dataset.state==="missed") box.textContent="원래 수신 예정 슬롯이지만 유예시간 안에 성공/부분수신 기록이 없어 미수신으로 판정했습니다.";
          else if(btn.dataset.state==="expected") box.textContent="원래 수신 예정 슬롯입니다. 아직 예정시각 전이거나 유예시간 안이라 미수신 판정을 내리지 않았습니다.";
          else box.textContent="이 시간은 이 자료의 정규 수신 예정 시간이 아닙니다.";
          return;
        }
        const st=STATUS[e.status]||STATUS.failed;
        box.innerHTML=`<strong>${e.label||e.source}</strong> · ${fmtKst(e.ended_kst)} · <span class="ing-badge ${st.cls}">${st.label}</span> · 자료/발표 ${fmtIssue(e.issue,e.source)} · 소요 ${e.duration_s==null?"—":Math.round(e.duration_s)+"초"}${e.summary?" · "+e.summary:""}`;
      }));
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