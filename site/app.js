/* NWP 모델 아카이브 뷰어 — 정적, 프레임워크 없음.
   manifest.json 이 유일한 진입점. 이미지는 현재 스텝 ±1만 프리로드(셀룰러 절약). */
"use strict";

const PANEL_LABEL = { t2m: "기온", tcc: "전운량", cloud3: "3층운량" };
let MF = null;
let state = { date: null, model: null, panel: null, stepIdx: 0, runs: {} };

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

const CMP = "모델비교";
let firstChart = true;   // 첫 진입 시 현재 시각에 가장 가까운 스텝으로
function cmpModels() { return Object.keys(entry().models); }
function runOf(m) {
  // 선택된 런(드롭다운) 우선, 없거나 그 날짜에 없는 런이면 최신
  const e = entry().models[m];
  const r = state.runs[m];
  return (r && e.runs[r]) ? r : e.latest;
}
function runEntry(m) { const e = entry().models[m]; const r = runOf(m); return { run: r, ...e.runs[r] }; }
function cmpSteps() {
  // 모델 공통 유효시각(KST epoch) — 런이 달라도 같은 시각끼리 비교
  const sets = cmpModels().map((m) => {
    const e = runEntry(m);
    return new Set(e.steps.map((s) => validEpoch(e.run, s)));
  });
  return [...sets[0]].filter((t) => sets.every((st) => st.has(t))).sort((a, b) => a - b);
}
function validEpoch(run10, stepH) {
  return Date.UTC(+run10.slice(0, 4), +run10.slice(4, 6) - 1, +run10.slice(6, 8),
                  +run10.slice(8, 10)) + stepH * 3600e3;
}
function fmtRun(run10) { return `${run10.slice(4, 6)}-${run10.slice(6, 8)} ${run10.slice(8)}z`; }
function relNow(epochUTC) {
  // 현재 시각 기준 상대 표시 — 순수 클라이언트 계산(부하 없음)
  const dh = (epochUTC - Date.now()) / 3600e3;
  if (Math.abs(dh) < 0.75) return "지금";
  const h = Math.round(Math.abs(dh));
  const d = Math.floor(h / 24);
  const s = d >= 1 ? `${d}일 ${h - d * 24}시간` : `${h}시간`;
  return dh > 0 ? `${s} 후` : `${s} 전`;
}

function renderModelBtns() {
  const models = Object.keys(entry().models);
  if (!models.length) {  // 관측 지도만 있는 날짜 (예: PC 꺼진 날 백필)
    $("modelBtns").innerHTML = "";
    $("panelBtns").innerHTML = "";
    $("chartStack").innerHTML = "";
    $("stepLabel").textContent = "이 날짜엔 모델 차트 없음 (관측 탭 참조)";
    return;
  }
  const opts = models.length > 1 ? [CMP, ...models] : models;
  if (!opts.includes(state.model)) state.model = opts[0];
  $("modelBtns").innerHTML = opts.map((m) =>
    `<button data-m="${m}" class="${m === state.model ? "on" : ""}">${m}</button>`).join("");
  $("modelBtns").querySelectorAll("button").forEach((b) => {
    b.onclick = () => { state.model = b.dataset.m; renderModelBtns(); };
  });
  renderPanelBtns();
}
function renderRunSel() {
  const compare = state.model === CMP;
  const models = compare ? cmpModels() : [state.model];
  $("runSel").innerHTML = models.map((m) => {
    const e = entry().models[m];
    const runs = Object.keys(e.runs).sort().reverse();
    if (runs.length < 2 && !compare) return "";
    const cur = runOf(m);
    return `<label class="run-label">${compare ? m + " 런" : "런"}
      <select data-m="${m}">` + runs.map((r) =>
        `<option value="${r}" ${r === cur ? "selected" : ""}>${fmtRun(r)}</option>`).join("")
      + `</select></label>`;
  }).join("");
  $("runSel").querySelectorAll("select").forEach((s) => {
    s.onchange = () => { state.runs[s.dataset.m] = s.value; renderPanelBtns(); };
  });
}
function renderPanelBtns() {
  const compare = state.model === CMP;
  renderRunSel();
  let panels;
  if (compare) {
    // 2개 이상 모델이 가진 패널만 비교 대상 (KIM 합류로 3층운량도 GFS+KIM 비교 가능)
    const cnt = {};
    cmpModels().forEach((m) => runEntry(m).panels.forEach((p) => { cnt[p] = (cnt[p] || 0) + 1; }));
    panels = ["t2m", "tcc", "cloud3"].filter((p) => cnt[p] >= 2);
  } else {
    panels = runEntry(state.model).panels;
  }
  if (!panels.includes(state.panel)) state.panel = panels[0];
  $("panelBtns").innerHTML = panels.map((p) =>
    `<button data-p="${p}" class="${p === state.panel ? "on" : ""}">${PANEL_LABEL[p] || p}</button>`).join("");
  $("panelBtns").querySelectorAll("button").forEach((b) => {
    b.onclick = () => { state.panel = b.dataset.p; renderPanelBtns(); };
  });
  const epochs = compare ? cmpSteps()
    : runEntry(state.model).steps.map((s) => validEpoch(runEntry(state.model).run, s));
  $("stepSlider").max = Math.max(0, epochs.length - 1);
  if (firstChart && epochs.length) {
    // 첫 진입: 현재 시각에 가장 가까운 유효시각으로
    const now = Date.now();
    state.stepIdx = epochs.reduce((bi, t, i) =>
      Math.abs(t - now) < Math.abs(epochs[bi] - now) ? i : bi, 0);
    firstChart = false;
  }
  if (state.stepIdx > epochs.length - 1) state.stepIdx = 0;
  renderChart();
}
function imgPathFor(model, stepH) {
  const run = runOf(model);
  return `archive/${state.date}/${model.toLowerCase()}_${run}_f${String(stepH).padStart(3, "0")}_${state.panel}.png`;
}
function renderChart() {
  $("stepSlider").value = state.stepIdx;
  if (state.model === CMP) {
    const ts = cmpSteps();
    if (!ts.length) { $("stepLabel").textContent = "공통 유효시각 없음"; return; }
    const t = ts[state.stepIdx];
    const d = new Date(t + 9 * 3600e3);
    const p = (n) => String(n).padStart(2, "0");
    $("stepLabel").textContent =
      `유효 ${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}시 KST (${relNow(t)}) — 전 모델 동시 표시`;
    $("chartStack").innerHTML = cmpModels().map((m) => {
      const e = runEntry(m);
      const stepH = (t - validEpoch(e.run, 0)) / 3600e3;
      if (!e.steps.includes(stepH) || !e.panels.includes(state.panel)) return "";
      return `<div class="cmp-item">`
           + `<div class="cmp-name">${m} <span>(런 ${fmtRun(e.run)} +${stepH}h)</span></div>`
           + `<img src="${imgPathFor(m, stepH)}" alt="${m}" loading="lazy"></div>`;
    }).join("");
    return;
  }
  const e = runEntry(state.model);
  const step = e.steps[state.stepIdx];
  const t = validEpoch(e.run, step);
  $("stepLabel").textContent =
    `+${step}h → 유효 ${validKST(e.run, step)} (${relNow(t)}) — 런 ${fmtRun(e.run)}`;
  $("chartStack").innerHTML = `<img id="chartImg" src="${imgPathFor(state.model, step)}" alt="차트">`;
  [state.stepIdx - 1, state.stepIdx + 1].forEach((i) => {
    if (i >= 0 && i < e.steps.length) new Image().src = imgPathFor(state.model, e.steps[i]);
  });
}
function maxStepIdx() {
  return (state.model === CMP ? cmpSteps().length : runEntry(state.model).steps.length) - 1;
}
$("stepSlider").oninput = (ev) => { state.stepIdx = +ev.target.value; renderChart(); };
$("stepPrev").onclick = () => { if (state.stepIdx > 0) { state.stepIdx--; renderChart(); } };
$("stepNext").onclick = () => {
  if (state.stepIdx < maxStepIdx()) { state.stepIdx++; renderChart(); }
};

// ── 관측 탭 ──
const OBS_LABEL = { ta: "기온", feel: "체감온도", si: "일사" };
const OBS_ORDER = ["ta", "feel", "si"];   // 탭 순서 (사용자 지정)
let firstObs = true;
function obsEpoch(ymd, hour) {  // 관측일(KST)+시 → UTC epoch
  return Date.UTC(+ymd.slice(0, 4), +ymd.slice(4, 6) - 1, +ymd.slice(6, 8), hour) - 9 * 3600e3;
}
let obsState = { date: null, v: null, idx: 0 };

function obsEntry() { return MF.dates[obsState.date].obs || {}; }
function renderObsVarBtns() {
  const present = Object.keys(obsEntry());
  const vars = OBS_ORDER.filter((v) => present.includes(v))
    .concat(present.filter((v) => !OBS_ORDER.includes(v)));
  if (!vars.length) {
    $("obsVarBtns").innerHTML = "";
    $("obsImg").removeAttribute("src");
    $("obsLabel").textContent = "이 날짜엔 관측 지도 없음";
    return;
  }
  if (!vars.includes(obsState.v)) obsState.v = vars.includes("ta") ? "ta" : vars[0];
  $("obsVarBtns").innerHTML = vars.map((v) =>
    `<button data-v="${v}" class="${v === obsState.v ? "on" : ""}">${OBS_LABEL[v] || v}</button>`).join("");
  $("obsVarBtns").querySelectorAll("button").forEach((b) => {
    b.onclick = () => { obsState.v = b.dataset.v; renderObsVarBtns(); };
  });
  const hours = obsEntry()[obsState.v];
  $("obsSlider").max = hours.length - 1;
  if (firstObs && hours.length) {
    // 첫 진입: 현재 시각에 가장 가까운 관측 시각으로
    const now = Date.now();
    obsState.idx = hours.reduce((bi, h, i) =>
      Math.abs(obsEpoch(obsState.date, h) - now) <
      Math.abs(obsEpoch(obsState.date, hours[bi]) - now) ? i : bi, 0);
    firstObs = false;
  }
  if (obsState.idx > hours.length - 1) obsState.idx = hours.length - 1;
  renderObs();
}
function obsPath(i) {
  const h = String(obsEntry()[obsState.v][i]).padStart(2, "0");
  return `archive/${obsState.date}/obs_${obsState.v}_${h}.png`;
}
function renderObs() {
  const hours = obsEntry()[obsState.v];
  $("obsSlider").value = obsState.idx;
  const h = hours[obsState.idx];
  $("obsLabel").textContent =
    `${fmtDate(obsState.date)} ${String(h).padStart(2, "0")}시 KST 실황 (${relNow(obsEpoch(obsState.date, h))})`;
  $("obsImg").src = obsPath(obsState.idx);
  [obsState.idx - 1, obsState.idx + 1].forEach((i) => {
    if (i >= 0 && i < hours.length) new Image().src = obsPath(i);
  });
}
$("obsSlider").oninput = (ev) => { obsState.idx = +ev.target.value; renderObs(); };
$("obsPrev").onclick = () => { if (obsState.idx > 0) { obsState.idx--; renderObs(); } };
$("obsNext").onclick = () => {
  if (obsState.idx < obsEntry()[obsState.v].length - 1) { obsState.idx++; renderObs(); }
};

// ── 검증 탭: 오차 지도 ──
let vmState = { v: "t2m", w: "d" };
function renderVm() {
  $("vmImg").src = vmState.w === "sm"
    ? `verif/verifmap_sm_${vmState.v}.png`
    : `verif/verifmap_${vmState.v}_${vmState.w}.png`;
}
document.querySelectorAll("#vmVarBtns button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll("#vmVarBtns button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on"); vmState.v = b.dataset.v; renderVm();
  };
});
document.querySelectorAll("#vmWinBtns button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll("#vmWinBtns button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on"); vmState.w = b.dataset.w; renderVm();
  };
});

// ── Meteogram 탭 ──
const METEO_ORDER = ["서울", "대전", "대구", "광주", "부산"];  // 사용자 지정 순서
function renderMeteo() {
  const d = $("dateSelM").value;
  const files = (MF.dates[d].meteograms || []).slice().sort((a, b) => {
    const ia = METEO_ORDER.findIndex((c) => a.includes(c));
    const ib = METEO_ORDER.findIndex((c) => b.includes(c));
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  $("meteoList").innerHTML = files.map((fn) =>
    `<img src="archive/${d}/${fn}" alt="${fn}" loading="lazy">`).join("");
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
      html += `<tr class="city-sep"><th>${city} 관측</th>` + hours.map((h) =>
        `<td><b>${fmt(c.obs[h])}</b></td>`).join("") + "</tr>";
      for (const m of models.filter((m) => c.models[m])) {
        html += `<tr><th>　${m}</th>` + hours.map((h) => {
          const fe = c.models[m][h];
          if (!fe) return "<td>-</td>";
          const [f, e] = fe;
          if (e === null) return `<td>${fmt(f)} (-)</td>`;
          // 배경 진하기 = |오차| (임계값에서 포화), 색상 = 부호(+빨강 과대 / −초록 저평가)
          const frac = Math.min(Math.abs(e) / big, 1);
          const bg = e > 0 ? `rgba(200,30,30,${(frac * 0.9).toFixed(2)})`
                           : `rgba(20,130,60,${(frac * 0.9).toFixed(2)})`;
          const fg = frac >= 0.55 ? "#fff" : "#111";
          return `<td style="background:${bg};color:${fg}">${fmt(f)}` +
                 `<span style="font-size:11px;color:${fg};opacity:.85"> (${e > 0 ? "+" : ""}${e.toFixed(nd)})</span></td>`;
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

  obsState.date = dates[0];
  fillDateSel($("dateSelO"), (ev) => { obsState.date = ev.target.value; renderObsVarBtns(); });
  renderObsVarBtns();
  renderVm();

  // 예보-관측 탭 (kmafcst 있는 날짜만)
  const kdates = Object.keys(MF.dates).filter((d) => MF.dates[d].kmafcst).sort().reverse();
  if (kdates.length) {
    $("dateSelK").innerHTML = kdates.map((d) => `<option value="${d}">${fmtDate(d)}</option>`).join("");
    const renderK = () => { $("kmafImg").src = `archive/${$("dateSelK").value}/kmafcst_vs_obs.png?${Date.now()}`; };
    $("dateSelK").onchange = renderK;
    renderK();
  }

  const vdates = (MF.verif_dates || []).slice().reverse();
  $("dateSelV").innerHTML = vdates.map((d) => `<option value="${d}">${fmtDate(d)}</option>`).join("");
  $("dateSelV").onchange = renderVerifDaily;

  renderModelBtns();
  renderMeteo();
  renderVerif();
  if (vdates.length) renderVerifDaily();
  $("genInfo").textContent =
    `마지막 갱신(UTC): ${MF.generated_utc} · 지도 보존 ${MF.max_days}일`;
})();
