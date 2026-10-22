/* Separate digital product: never silently combine regional legacy and grid values. */
(function () {
  'use strict';
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const val = v => typeof v === 'number' && Number.isFinite(v) ? v.toFixed(1) : '—';
  const when = s => `${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)} ${s.slice(8,10)}시`;
  const range = q => q ? `${val(q.p25)}~${val(q.p75)} / ${val(q.p10)}~${val(q.p90)}` : '미제공';
  const delta = (a,b) => typeof a === 'number' && typeof b === 'number' ? `${b-a>0?'+':''}${(b-a).toFixed(1)}` : '—';
  async function init() {
    const host = document.getElementById('tab-compare');
    if (!host) return;
    let data;
    try {
      const res = await fetch(`digital_mid/index.json?${Date.now()}`);
      if (!res.ok) return;
      data = await res.json();
    } catch (_) { return; }
    if (data.schema !== 1 || data.mode !== 'active') return;
    const box = document.createElement('section');
    box.className = 'dm-panel';
    host.appendChild(box);
    if (!data.issues.length) {
      box.textContent = '디지털 중기예보: 검증을 통과한 수신 자료가 없습니다. 기존 예보를 확인하세요.';
      return;
    }
    const issues = data.issues.slice().sort((a,b)=>a.issue.localeCompare(b.issue));
    box.innerHTML = '<h3>디지털 중기예보 · 도시 격자</h3><p>기존 광역 중기예보와 별도 자료입니다. 기본 기온과 백분위 범위를 구분하며, 변화량은 이 자료의 직전 발표와 비교합니다.</p><div class="dm-controls"><label>발표 <select class="dm-issue"></select></label><label>도시 <select class="dm-city"></select></label></div><p class="dm-status" role="status"></p><div class="dm-daily dm-scroll"></div><details><summary>3~6시간 상세 · 강수가능성 및 변동성</summary><div class="dm-hourly dm-scroll"></div></details>';
    const sel = box.querySelector('.dm-issue'), city = box.querySelector('.dm-city');
    sel.innerHTML = issues.map((d,i)=>`<option value="${i}">${esc(when(d.issue))}</option>`).join('');
    sel.value = String(issues.length-1);
    const table = (heads,rows) => `<table><thead><tr>${heads.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(v=>`<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
    function render() {
      const index = Number(sel.value), d = issues[index], c = d.cities[city.value];
      if (!c) return;
      const prev = issues[index-1], before = prev && prev.cities[city.value];
      const t = new Date(`${d.issue.slice(0,4)}-${d.issue.slice(4,6)}-${d.issue.slice(6,8)}T${d.issue.slice(8,10)}:00:00+09:00`);
      const age = (Date.now()-t.getTime())/3600000;
      box.querySelector('.dm-status').textContent = `${when(d.issue)} KST · ${age>30?'이전 발표 자료 — 최신 수신 여부 확인 필요 · ':''}${prev?'비교: '+when(prev.issue):'이전 발표 없음'} · 격자 ${c.sample.lat.toFixed(3)}, ${c.sample.lon.toFixed(3)} · 백분위: 25~75 / 10~90 (℃)`;
      box.querySelector('.dm-daily').innerHTML = table(['대상일','최저','최고','최저 변화','최고 변화','최저 백분위','최고 백분위'],Object.entries(c.daily).sort().map(([day,r])=>{
        const b = before && before.daily[day];
        return [day, val(r.TMN),val(r.TMX),delta(b&&b.TMN,r.TMN),delta(b&&b.TMX,r.TMX),range(r.TMN_quantiles),range(r.TMX_quantiles)];
      }));
      box.querySelector('.dm-hourly').innerHTML = table(['유효시각 KST','기온','기온 백분위','하늘상태','강수형태','강수가능성','강수변동성'],Object.entries(c.hourly).sort().map(([hour,r])=>[when(hour),val(r.TMP),range(r.TMP_quantiles),r.SKY.label,r.PTY.label,r.RPOS.label,r.RVAR.label]));
    }
    function selectIssue() {
      const old = city.value;
      const names = Object.keys(issues[Number(sel.value)].cities);
      city.innerHTML = names.map(n=>`<option value="${esc(n)}">${esc(n)}</option>`).join('');
      if (names.includes(old)) city.value = old;
      render();
    }
    sel.addEventListener('change',selectIssue);
    city.addEventListener('change',render);
    selectIssue();
  }
  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',init); else init();
})();
