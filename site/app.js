/* NWP 모델 아카이브 뷰어 — 정적, 프레임워크 없음.
   manifest.json 이 유일한 진입점. 이미지는 현재 스텝 ±1만 프리로드(셀룰러 절약). */
"use strict";

const PANEL_LABEL = { t2m: "기온", tcc: "전운량", cloud3: "3층운량" };
let MF = null;
let state = { date: null, model: null, panel: null, stepIdx: 0 };

const $ = (id) => document.getElementById(id);

// ── 탭 전환 ──
document.querySelectorAll("#tabs button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll("#tabs button").forEach((x) => x.classList.remove("on"));
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    $("tab-" + b.dataset.tab).classList.add("on");
  };
});

// ── 유틸 ──
function fmtDate(ymd) {
  return `${ymd.slice(0, 4)}-${ymd.slice(4, 6)}-${ymd.slice(6, 8)}`;
}
function validKST(run10, stepH) {
  // run10 = YYYYMMDDHH (UTC) → 유효시각 KST
  const t = Date.UTC(+run10.slice(0, 4), +run10.slice(4, 6) - 1, +run10.slice(6, 8),
                     +run10.slice(8, 10)) + (stepH + 9) * 3600e3;
  const d = new Date(t);
  const p = (n) => String(n).padStart(2, "0");
  const yo = "일월화수목금토"[d.getUTCDay()];
  return `${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}(${yo}) ${p(d.getUTCHours())}시 KST`;
}
function fillDateSel(sel, onchange) {
  const dates = Object.keys(MF.dates).sort().reverse();
  sel.innerHTML = dates.map((d) => `<option value="${d}">${fmtDate(d)}</option>`).join("");
  sel.onchange = onchange;
}

// ── 차트 탭 ──
function entry() { return MF.dates[state.date]; }
function modelEntry() { return entry().models[state.model]; }

function renderModelBtns() {
  const models = Object.keys(entry().models);
  if (!models.includes(state.model)) state.model = models[0];
  $("modelBtns").innerHTML = models.map((m) =>
    `<button data-m="${m}" class="${m === state.model ? "on" : ""}">${m}</button>`).join("");
  $("modelBtns").querySelectorAll("button").forEach((b) => {
    b.onclick = () => { state.model = b.dataset.m; renderModelBtns(); };
  });
  renderPanelBtns();
}
function renderPanelBtns() {
  const panels = modelEntry().panels;
  if (!panels.includes(state.panel)) state.panel = panels[0];
  $("panelBtns").innerHTML = panels.map((p) =>
    `<button data-p="${p}" class="${p === state.panel ? "on" : ""}">${PANEL_LABEL[p] || p}</button>`).join("");
  $("panelBtns").querySelectorAll("button").forEach((b) => {
    b.onclick = () => { state.panel = b.dataset.p; renderPanelBtns(); };
  });
  const steps = modelEntry().steps;
  $("stepSlider").max = steps.length - 1;
  if (state.stepIdx > steps.length - 1) state.stepIdx = 0;
  renderChart();
}
function imgPath(stepIdx) {
  const e = modelEntry();
  const s = String(e.steps[stepIdx]).padStart(3, "0");
  return `archive/${state.date}/${state.model.toLowerCase()}_${e.run}_f${s}_${state.panel}.png`;
}
function renderChart() {
  const e = modelEntry();
  const step = e.steps[state.stepIdx];
  $("stepSlider").value = state.stepIdx;
  $("stepLabel").textContent =
    `+${step}h → 유효 ${validKST(e.run, step)} (런 ${e.run.slice(4, 8)} ${e.run.slice(8)}UTC)`;
  $("chartImg").src = imgPath(state.stepIdx);
  // 인접 스텝 프리로드 (±1)
  [state.stepIdx - 1, state.stepIdx + 1].forEach((i) => {
    if (i >= 0 && i < e.steps.length) new Image().src = imgPath(i);
  });
}
$("stepSlider").oninput = (ev) => { state.stepIdx = +ev.target.value; renderChart(); };
$("stepPrev").onclick = () => { if (state.stepIdx > 0) { state.stepIdx--; renderChart(); } };
$("stepNext").onclick = () => {
  if (state.stepIdx < modelEntry().steps.length - 1) { state.stepIdx++; renderChart(); }
};

// ── 미티오그램 탭 ──
function renderMeteo() {
  const d = $("dateSelM").value;
  $("meteoList").innerHTML = (MF.dates[d].meteograms || []).map((fn) =>
    `<img src="archive/${d}/${fn}" alt="${fn}" loading="lazy">`).join("");
}

// ── 도시표 탭 ──
async function renderTable() {
  const d = $("dateSelT").value;
  const info = MF.dates[d];
  if (!info.daily_json) { $("cityTable").innerHTML = "<p>수치 자료 없음</p>"; return; }
  const data = await (await fetch(info.daily_json)).json();
  const col = Object.fromEntries(data.columns.map((c, i) => [c, i]));
  const cities = [...new Set(data.rows.map((r) => r[col.city]))];
  const citySel = $("citySel");
  if (!citySel.options.length || citySel.dataset.date !== d) {
    const cur = citySel.value;
    citySel.innerHTML = cities.map((c) => `<option>${c}</option>`).join("");
    citySel.dataset.date = d;
    if (cities.includes(cur)) citySel.value = cur;
  }
  const city = citySel.value;
  const rows = data.rows.filter((r) => r[col.city] === city);
  const cols = ["model", "valid_kst", "step_h", "t2m_C", "tcc_pct",
                "lcc_pct", "mcc_pct", "hcc_pct", "dswrf_avg_Wm2"];
  const head = ["모델", "유효(KST)", "+h", "기온℃", "전운%", "하층", "중층", "상층", "일사W/㎡"];
  let html = "<table><tr>" + head.map((h) => `<th>${h}</th>`).join("") + "</tr>";
  for (const r of rows) {
    html += "<tr>" + cols.map((c) =>
      `<td>${r[col[c]] === null || r[col[c]] === undefined ? "-" : r[col[c]]}</td>`).join("") + "</tr>";
  }
  $("cityTable").innerHTML = html + "</table>";
}

// ── 검증 탭: 일별 검증표 ──
const CITY_ORDER = ["서울", "대전", "대구", "광주", "부산",
                    "인천", "수원", "전주", "강릉", "제주"];
async function renderVerifDaily() {
  const d = $("dateSelV").value;
  const data = await (await fetch(`verif/daily/${d}.json`)).json();
  for (const [vr, elId, nd, big] of [["t2m", "verifDailyT", 1, 3], ["tcc", "verifDailyC", 0, 40]]) {
    const vd = data[vr];
    if (!vd) { $(elId).innerHTML = "<p>자료 없음</p>"; continue; }
    const hours = [...new Set(Object.values(vd).flatMap((c) =>
      [...Object.keys(c.obs), ...Object.values(c.models).flatMap((m) => Object.keys(m))]
    ))].map(Number).sort((a, b) => a - b);
    const models = [...new Set(Object.values(vd).flatMap((c) => Object.keys(c.models)))].sort();
    const fmt = (v) => v === null || v === undefined ? "-" : v.toFixed(nd);
    let html = "<table><tr><th>지점</th>" +
      hours.map((h) => `<th>${String(h).padStart(2, "0")}시</th>`).join("") + "</tr>";
    for (const city of CITY_ORDER.filter((c) => vd[c])) {
      const c = vd[city];
      html += `<tr><th>${city} 관측</th>` + hours.map((h) =>
        `<td><b>${fmt(c.obs[h])}</b></td>`).join("") + "</tr>";
      for (const m of models.filter((m) => c.models[m])) {
        html += `<tr><th>　${m}</th>` + hours.map((h) => {
          const fe = c.models[m][h];
          if (!fe) return "<td>-</td>";
          const [f, e] = fe;
          if (e === null) return `<td>${fmt(f)} (-)</td>`;
          const col = Math.abs(e) >= big ? "#c00" : "#888";
          return `<td>${fmt(f)}<span style="color:${col};font-size:11px"> (${e > 0 ? "+" : ""}${e.toFixed(nd)})</span></td>`;
        }).join("") + "</tr>";
      }
    }
    $(elId).innerHTML = html + "</table>";
  }
}

// ── 검증 탭 ──
async function renderVerif() {
  try {
    const data = await (await fetch("verif/summary.json")).json();
    let html = "<table><tr>" + data.columns.map((c) => `<th>${c}</th>`).join("") + "</tr>";
    for (const r of data.rows) {
      html += "<tr>" + r.map((v) => `<td>${v === null ? "-" : v}</td>`).join("") + "</tr>";
    }
    $("verifTable").innerHTML = html + "</table>";
  } catch { $("verifTable").innerHTML = "<p>검증 요약 없음</p>"; }
  $("caseList").innerHTML = (MF.cases || []).slice().reverse().map((fn) =>
    `<li><a href="verif/cases/${fn}" target="_blank">${fn.replace(".md", "")}</a></li>`).join("");
}

// ── 초기화 ──
(async function init() {
  MF = await (await fetch("manifest.json?" + Date.now())).json();
  const dates = Object.keys(MF.dates).sort().reverse();
  if (!dates.length) { document.body.innerHTML += "<p>아카이브가 비어 있습니다</p>"; return; }
  state.date = dates[0];

  fillDateSel($("dateSel"), (ev) => { state.date = ev.target.value; renderModelBtns(); });
  fillDateSel($("dateSelM"), renderMeteo);
  fillDateSel($("dateSelT"), renderTable);
  $("citySel").onchange = renderTable;

  const vdates = (MF.verif_dates || []).slice().reverse();
  $("dateSelV").innerHTML = vdates.map((d) => `<option value="${d}">${fmtDate(d)}</option>`).join("");
  $("dateSelV").onchange = renderVerifDaily;

  renderModelBtns();
  renderMeteo();
  renderTable();
  renderVerif();
  if (vdates.length) renderVerifDaily();
  $("genInfo").textContent =
    `마지막 갱신(UTC): ${MF.generated_utc} · 지도 보존 ${MF.max_days}일`;
})();
