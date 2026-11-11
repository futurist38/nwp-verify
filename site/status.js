"use strict";

(() => {
  const STATUS = {
    unknown: {label:"판정 불가", cls:"unknown"},
    delayed: {label:"지연 수신", cls:"warn"},
    success: {label:"정상", cls:"ok"},
    partial: {label:"부분수신", cls:"warn"},
    failed: {label:"실패", cls:"bad"},
    missed: {label:"수신 기록 없음", cls:"missed"}
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
  function matrix(j, selectedDay){
    const allHours=j.hours||[], days=[...new Set(allHours.map(h=>h.slice(0,10)))];
    selectedDay=selectedDay||days[days.length-1];
    const hours=allHours.filter(h=>h.startsWith(selectedDay)), mat=j.matrix||{}, detail=j.matrix_detail||{}, expected=j.expected||{}, sched=j.schedule_meta||{};
    const latest=j.latest||[];
    if(!hours.length || !latest.length) return '<p class="note">시간별 이력이 아직 없습니다.</p>';
    const dayMarks=hours.map(h=>`<span class="ing-daymark">${h.slice(11,13)}</span>`).join("");
    const picker=`<div class="ing-daypicker" role="group" aria-label="수신현황 날짜">${days.map(day=>`<button type="button" data-day="${day}" aria-pressed="${day===selectedDay}">${day.slice(5).replace('-', '/')}</button>`).join('')}<span>시간(KST) · 한 칸 1시간</span></div>`;
    const rows=latest.map(e=>{
      const cells=hours.map(h=>{
        const due=!!expected[e.source]?.[h];
        const st=mat[e.source]?.[h]||(due?"expected":"none");
        const d=detail[e.source]?.[h];
        const cls=st==="success"?"ok":(st==="partial"||st==="delayed")?"warn":st==="failed"?"bad":st==="missed"?"missed":st==="expected"?"expected":st==="unknown"?"unknown":"none";
        let title;
        if(d) title=`${e.label} · ${due?"예정 슬롯":"추가 실행"} ${fmtKst(h)} · 실제 완료 ${fmtKst(d.ended_kst)} · ${STATUS[d.status]?.label||d.status}${d.issue?" · "+fmtIssue(d.issue,d.source):""}`;
        else if(st==="unknown") title=`${e.label} · ${fmtKst(h)} · 기록 시작 전 / 판정 불가`;
        else if(st==="missed") title=`${e.label} · ${fmtKst(h)} 예정 · 유예시간 경과 후 수신 기록 없음`;
        else if(st==="expected") title=`${e.label} · ${fmtKst(h)} 예정 · 아직 대기/유예시간`;
        else title=`${e.label} · 이 시간은 정규 수신 예정 슬롯 아님`;
        if(st==="none") return `<span class="ing-cell none" aria-label="${title}"></span>`;
        return `<button type="button" class="ing-cell ${cls}" data-source="${e.source}" data-hour="${h}" data-state="${st}" title="${title}" aria-label="${title}"></button>`;
      }).join("");
      const sl=sched[e.source]?.label ? `<small>${sched[e.source].label} · 유예 ${sched[e.source].grace_h}시간</small>` : "";
      return `<div class="ing-rowlabel"><span>${e.label}</span>${sl}</div>${cells}`;
    }).join("");
    return `${picker}<div class="ing-matrix-wrap"><div class="ing-matrix" style="--cols:${hours.length}">
      <div class="ing-corner">자료 / 수집 주기</div>${dayMarks}
      ${rows}
    </div></div>
    <div class="ing-legend"><span><i class="expected"></i>수신 예정</span><span><i class="ok"></i>정상</span><span><i class="warn"></i>부분수신/지연</span><span><i class="bad"></i>실패</span><span><i class="missed"></i>수신 기록 없음</span><span><i class="unknown"></i>판정 불가</span><span>빈칸: 예정 없음</span></div>
    <div id="ingestCellDetail" class="ing-cell-detail" aria-live="polite">네모를 누르면 해당 시각의 상세 상태를 표시합니다.</div>`;
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
      const draw=(day)=>{
      $("ingestMatrix").innerHTML=matrix(j,day);
      $("ingestMatrix").querySelectorAll("[data-day]").forEach(btn=>btn.addEventListener("click",()=>draw(btn.dataset.day)));
      $("ingestRows").innerHTML=events.length?events.slice(0,120).map(row).join(""):'<tr><td colspan="6">아직 기록이 없습니다.</td></tr>';
      $("ingestMatrix").querySelectorAll(".ing-cell").forEach(btn=>btn.addEventListener("click",()=>{
        const e=j.matrix_detail?.[btn.dataset.source]?.[btn.dataset.hour];
        const box=$("ingestCellDetail"); if(!box) return;
        if(!e){
          if(btn.dataset.state==="unknown") box.textContent="기록 수집을 시작하기 전이므로 수신 상태를 판정할 수 없습니다.";
          else if(btn.dataset.state==="missed") box.textContent="수신 예정시각과 유예시간이 지났지만 이 슬롯에 작업 결과가 기록되지 않았습니다. 작업 미실행·지연·기록 누락 가능성이 있으며, 실제 자료 부재를 확정한 것은 아닙니다.";
          else if(btn.dataset.state==="expected") box.textContent="원래 수신 예정 슬롯입니다. 아직 예정시각 전이거나 유예시간 안이므로 대기 상태입니다.";
          else box.textContent="이 시간은 이 자료의 정규 수신 예정 시간이 아닙니다.";
          return;
        }
        const st=STATUS[e.status]||STATUS.failed;
        box.innerHTML=`<strong>${e.label||e.source}</strong> · ${fmtKst(e.ended_kst)} · <span class="ing-badge ${st.cls}">${st.label}</span> · 자료/발표 ${fmtIssue(e.issue,e.source)} · 소요 ${e.duration_s==null?"—":Math.round(e.duration_s)+"초"}${e.summary?" · "+e.summary:""}`;
      }));
      };
      draw();
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