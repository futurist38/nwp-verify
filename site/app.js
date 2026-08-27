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

// ── 방향키 탐색: 활성 탭의 이전/다음 버튼에 연결 ──
const ARROW_BTN = { "tab-charts": ["stepPrev", "stepNext"],
                    "tab-obs": ["obsPrev", "obsNext"],
                    "tab-nowcast": ["ncPrev", "ncNext"] };
document.addEventListener("keydown", (ev) => {
  if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
  const tag = (ev.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "select" || tag === "textarea") return;
  const sec = document.querySelector(".tab.on");
  const pair = sec && ARROW_BTN[sec.id];
  if (!pair) return;
  const btn = $(pair[ev.key === "ArrowLeft" ? 0 : 1]);
  if (btn) { btn.click(); ev.preventDefault(); }
});


// ── 시계열 차트 (공용) ────────────────────────────────
// 이미지 대신 데이터를 받아 SVG로 그린다 — 용량이 30배 작고 값을 마우스/터치로 읽을 수 있다.
// 예보-관측(실측 vs 예보)과 미티오그램(모델 3종)이 같은 렌더러를 쓴다 (2026-08-26).

function drawPanel(o) {
  // o: {title, series:[{color,dash,data}], i0,i1, ylo,yhi, t0ms, stepMs, vline}
  const W = o.w || 400, H = o.h || 210, ML = 38, MR = 10, MT = 16, MB = 24;
  const n = Math.max(1, o.i1 - o.i0);
  const X = (i) => ML + ((i - o.i0) / n) * (W - ML - MR);
  const Y = (v) => MT + ((o.yhi - v) / Math.max(1e-6, o.yhi - o.ylo)) * (H - MT - MB);
  const path = (arr) => {
    let out = "", pen = false;
    for (let i = o.i0; i <= o.i1; i++) {
      const v = arr && arr[i];
      if (v == null) { pen = false; continue; }
      out += (pen ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1) + " ";
      pen = true;
    }
    return out;
  };
  const dots = (arr, color) => {
    let out = "";
    for (let i = o.i0; i <= o.i1; i++) {
      const v = arr && arr[i];
      if (v != null) out += `<circle cx="${X(i).toFixed(1)}" cy="${Y(v).toFixed(1)}" r="2" fill="${color}"/>`;
    }
    return out;
  };
  const span = o.yhi - o.ylo;
  const gy = span > 60 ? 20 : span > 25 ? 10 : 5;
  let g = "";
  for (let v = Math.ceil(o.ylo / gy) * gy; v <= o.yhi; v += gy) {
    g += `<line x1="${ML}" y1="${Y(v)}" x2="${W - MR}" y2="${Y(v)}" stroke="#d5d5d5"/>`
       + `<text x="${ML - 4}" y="${Y(v) + 4}" text-anchor="end" font-size="10" fill="#666">${v}</text>`;
  }
  // 라벨 간격: 라벨끼리 60px 이상 떨어지도록 폭에 맞춰 자동 조절
  const perStep = (W - ML - MR) / n;
  const stepH = o.stepMs / 3600e3;
  let labH = 6;
  while (perStep * (labH / stepH) < 60) labH += stepH;
  for (let i = o.i0; i <= o.i1; i++) {
    const d = new Date(o.t0ms + i * o.stepMs + 9 * 3600e3);
    if (d.getUTCHours() % labH) continue;
    const lab = d.getUTCHours() === 0 ? `${d.getUTCMonth() + 1}/${d.getUTCDate()}` : d.getUTCHours() + "시";
    g += `<line x1="${X(i)}" y1="${MT}" x2="${X(i)}" y2="${H - MB}" stroke="#e2e2e2"/>`
       + `<text x="${X(i)}" y="${H - MB + 14}" text-anchor="middle" font-size="10" fill="#666">${lab}</text>`;
  }
  const vl = (o.vline != null && o.vline >= o.i0 && o.vline <= o.i1)
    ? `<line x1="${X(o.vline)}" y1="${MT}" x2="${X(o.vline)}" y2="${H - MB}" stroke="#1a5fb4" stroke-dasharray="3 3"/>` : "";
  const lines = o.series.map((se) =>
    `<path d="${path(se.data)}" fill="none" stroke="${se.color}" stroke-width="1.7"`
    + (se.dash ? ` stroke-dasharray="${se.dash}"` : "") + "/>").join("");
  const pts = o.series.map((se) => dots(se.data, se.color)).join("");
  return `<svg viewBox="0 0 ${W} ${H}" data-t="${o.title}" data-ml="${ML}" data-mr="${MR}"
    data-i0="${o.i0}" data-i1="${o.i1}" data-w="${W}">${g}${vl}${lines}${pts}
    <text x="${ML + 2}" y="${MT - 4}" font-size="12" font-weight="bold">${o.title}</text>
    <line class="cross" x1="0" y1="${MT}" x2="0" y2="${H - MB}" stroke="#e01b24" stroke-width="1" opacity="0"/>
  </svg>`;
}

function bindHover(container, lookup) {
  // lookup(title, i) → {when, rows:[[이름, 값문자열], ...]}
  const tip = $("chartTip");
  $(container).querySelectorAll("svg").forEach((svg) => {
    const title = svg.dataset.t, ML = +svg.dataset.ml, MR = +svg.dataset.mr;
    const i0 = +svg.dataset.i0, i1 = +svg.dataset.i1, W = +svg.dataset.w;
    const cross = svg.querySelector(".cross");
    const at = (cx, cy) => {
      const r = svg.getBoundingClientRect();
      const px = ((cx - r.left) / r.width) * W;
      const i = Math.round(i0 + ((px - ML) / (W - ML - MR)) * (i1 - i0));
      if (i < i0 || i > i1) { tip.hidden = true; cross.setAttribute("opacity", 0); return; }
      cross.setAttribute("x1", px); cross.setAttribute("x2", px);
      cross.setAttribute("opacity", 1);
      const info = lookup(title, i);
      tip.innerHTML = `<b>${title}</b> ${info.when}<br>`
        + info.rows.map((kv) => `${kv[0]} ${kv[1]}`).join(" · ");
      tip.hidden = false;
      tip.style.left = Math.min(Math.max(8, cx + 14), innerWidth - 210) + "px";
      tip.style.top = Math.max(8, cy - 70) + "px";
    };
    svg.onmousemove = (ev) => at(ev.clientX, ev.clientY);
    svg.onmouseleave = () => { tip.hidden = true; cross.setAttribute("opacity", 0); };
    // 터치: 짚은 채 좌우로 움직이면 값을 훑을 수 있게. 다만 **세로로 긋는 동작은
    // 페이지 스크롤로 넘긴다** — 안 그러면 휴대폰에서 아래로 내려갈 수가 없다(2026-08-27).
    let t0x = 0, t0y = 0, mode = 0;   // 0=미정 1=값읽기 2=스크롤
    svg.addEventListener("touchstart", (ev) => {
      const t = ev.touches[0];
      t0x = t.clientX; t0y = t.clientY; mode = 0;
      at(t.clientX, t.clientY);
    }, { passive: true });
    svg.addEventListener("touchmove", (ev) => {
      const t = ev.touches[0];
      if (!mode) {
        const dx = Math.abs(t.clientX - t0x), dy = Math.abs(t.clientY - t0y);
        if (dx + dy < 8) return;
        mode = dx > dy ? 1 : 2;
        if (mode === 2) { tip.hidden = true; cross.setAttribute("opacity", 0); }
      }
      if (mode === 1) { at(t.clientX, t.clientY); ev.preventDefault(); }
    }, { passive: false });
    svg.addEventListener("touchend", () => {
      setTimeout(() => { tip.hidden = true; cross.setAttribute("opacity", 0); }, 2500);
    });
  });
}

function keyToMs(key) {   // YYYYMMDDHH(KST) → epoch
  return Date.UTC(+key.slice(0, 4), +key.slice(4, 6) - 1, +key.slice(6, 8), +key.slice(8, 10))
         - 9 * 3600e3;
}
function fmtWhen(ms) {
  const d = new Date(ms + 9 * 3600e3), p2 = (x) => String(x).padStart(2, "0");
  return `${p2(d.getUTCMonth() + 1)}-${p2(d.getUTCDate())} ${p2(d.getUTCHours())}시`;
}

// ── 예보-관측 ──
let KMAF = { date: null, data: null };

function renderKmaf() {
  const d = KMAF.data, b = $("issueSelK").value;
  if (!d || !d.fcst[b]) { $("kmafCharts").innerHTML = ""; return; }
  const t0ms = keyToMs(d.t0);
  const iIss = Math.round((keyToMs(b) - t0ms) / 3600e3);
  // 창은 발표 -6h ~ **대상일 23시**까지 (2026-08-27 사용자 요청).
  // +24h로 끊으면 이른 발표(어제 11시)가 오늘 낮에서 잘려 하루를 다 못 본다.
  const ymd = $("dateSelK").value;
  const endMs = keyToMs(ymd + "23");
  const i0 = Math.max(0, iIss - 6);
  const i1 = Math.min(d.hours - 1, Math.max(iIss + 6, Math.round((endMs - t0ms) / 3600e3)));
  let lo = Infinity, hi = -Infinity;
  d.cities.forEach((c) => {
    for (let i = i0; i <= i1; i++) {
      [d.obs[c] && d.obs[c][i], d.fcst[b][c] && d.fcst[b][c][i]].forEach((v) => {
        if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
      });
    }
  });
  if (!isFinite(lo)) { $("kmafCharts").innerHTML = "<p class='note'>자료 없음</p>"; return; }
  const pad = Math.max(1, (hi - lo) * 0.12);
  $("kmafCharts").innerHTML = d.cities.map((c) => drawPanel({
    title: c, i0: i0, i1: i1, ylo: lo - pad, yhi: hi + pad,
    t0ms: t0ms, stepMs: 3600e3, vline: iIss,
    series: [{ color: "#1a5fb4", dash: "5 3", data: d.fcst[b][c] },
             { color: "#111", data: d.obs[c] }],
  })).join("");
  bindHover("kmafCharts", (city, i) => {
    const o = d.obs[city] && d.obs[city][i], f = d.fcst[b][city] && d.fcst[b][city][i];
    const rows = [["실측", o == null ? "—" : o.toFixed(1) + "℃"],
                  ["예보", f == null ? "—" : f.toFixed(1) + "℃"]];
    if (o != null && f != null) rows.push(["차이", (f - o > 0 ? "+" : "") + (f - o).toFixed(1) + "℃"]);
    return { when: fmtWhen(t0ms + i * 3600e3), rows: rows };
  });
}

// ── 예보 변화 (지점값 표출) ─────────────────────────────
// 관측 지도와 같은 밑그림·지점망을 쓴다. 값은 '어제 발표 대비 오늘 발표'의 차이(℃).
const FD_SCALE = { vmin: -3, vmax: 3, step: 0.5, label: "예보 변화", unit: "℃" };
let FD = { date: null, data: null, v: "tmx" };

function fdColor(d) {   // 빨강=상향 · 파랑=하향 (0 근처는 흰색)
  const t = Math.max(-1, Math.min(1, d / FD_SCALE.vmax));
  const mix = (a, b, f) => a.map((x, i) => Math.round(x + (b[i] - x) * f));
  const W = [247, 247, 247], R = [176, 24, 43], B = [33, 102, 172];
  const c = t >= 0 ? mix(W, R, t) : mix(W, B, -t);
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

async function renderFd() {
  const d = $("dateSelK").value;
  const on = (MF.fd_dates || []).includes(d);
  $("fdTitle").hidden = !on;
  $("fdTitle").nextElementSibling.hidden = !on;
  $("fdPair").hidden = !on;
  if (!on) return;
  if (FD.date !== d) {
    FD.data = await (await fetch(`fcstdiff/${d}.json?${Date.now()}`)).json();
    FD.date = d;
  }
  if (!obsState.meta) {
    obsState.meta = await (await fetch("obs/stations.json")).json();
    obsState.base = await (await fetch("basemap.json")).json();
  }
  const vv = FD.data.vars[FD.v] || {}, bm = obsState.base;
  let pts = "", lbl = "", n = 0;
  obsState.meta.stations.forEach((st) => {
    const v = vv[String(st.s)];
    if (v == null) return;
    n++;
    pts += `<circle cx="${st.x}" cy="${st.y}" r="${st.L ? 8 : 7}" fill="${fdColor(v)}"`
         + ` stroke="${st.L ? "#000" : "#333"}" stroke-width="${st.L ? 1.4 : 0.7}"`
         + ` data-n="${st.n}" data-v="${v}"/>`;
    if (st.L) {
      lbl += `<text x="${st.x + 11}" y="${st.y + 5}" font-size="15" font-weight="bold"`
           + ` paint-order="stroke" stroke="#fff" stroke-width="3.5" fill="#111">`
           + `${st.n} ${v > 0 ? "+" : ""}${v.toFixed(1)}</text>`;
    }
  });
  const nb = Math.round((FD_SCALE.vmax - FD_SCALE.vmin) / FD_SCALE.step);
  const CW = 620, SW = CW / nb;
  let defs = "", cells = "", ticks = "";
  for (let i = 0; i < nb; i++) {
    const a = FD_SCALE.vmin + i * FD_SCALE.step, b = a + FD_SCALE.step;
    defs += `<linearGradient id="fg${i}"><stop offset="0%" stop-color="${fdColor(a)}"/>`
          + `<stop offset="100%" stop-color="${fdColor(b)}"/></linearGradient>`;
    cells += `<rect x="${(i * SW).toFixed(1)}" y="0" width="${SW.toFixed(1)}" height="22" fill="url(#fg${i})" stroke="#fff" stroke-width="0.8"/>`;
  }
  for (let i = 0; i <= nb; i++) {
    const e = FD_SCALE.vmin + i * FD_SCALE.step;
    if (i % 2) continue;
    ticks += `<line x1="${(i * SW).toFixed(1)}" y1="22" x2="${(i * SW).toFixed(1)}" y2="27" stroke="#666"/>`
           + `<text x="${(i * SW).toFixed(1)}" y="38" text-anchor="middle" font-size="12" fill="#444">${e > 0 ? "+" : ""}${e}</text>`;
  }
  const p2 = (x) => x.slice(4, 6) + "-" + x.slice(6, 8) + " " + x.slice(8) + "시";
  $("fdMap").innerHTML =
    `<div class="step-label">${p2(FD.data.prev)} 발표 대비 ${p2(FD.data.now)} 발표 · 대상 ${fmtDate(FD.data.target)}</div>
     <svg id="fdSvg" viewBox="0 0 ${bm.w} ${bm.h}">
      <rect width="${bm.w}" height="${bm.h}" fill="#f7f9fb"/>
      <path d="${bm.paths.admin}" fill="none" stroke="#c9c9c9" stroke-width="0.8"/>
      <path d="${bm.paths.coast}" fill="none" stroke="#5a5a5a" stroke-width="1.2"/>
      ${pts}${lbl}
     </svg>
     <div class="cbar"><svg viewBox="-6 0 ${CW + 12} 44"><defs>${defs}</defs>${cells}${ticks}</svg>
       <div class="cbar-lab">예보 변화 (℃) — 빨강 상향 · 파랑 하향, 칸 하나 ${FD_SCALE.step}℃</div></div>
     <p class="note">지점 ${n}곳 — 마우스를 올리거나(휴대폰은 짚은 채 움직이면) 지점명과 변화량이 표시됩니다.</p>`;

  bindDotHover("fdSvg", (t) => {
    const v = +t.dataset.v;
    return `<b>${t.dataset.n}</b><br>예보 변화 ${v > 0 ? "+" : ""}${v.toFixed(1)}℃`;
  });
  $("fdVarBtns").querySelectorAll("button").forEach((b) => {
    b.onclick = () => {
      FD.v = b.dataset.v;
      $("fdVarBtns").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
      renderFd();
    };
  });
}

// 지점 원 위 마우스/터치 — 짚은 채 옮겨 다니며 값을 훑을 수 있다.
// 세로로 긋는 동작은 페이지 스크롤로 넘긴다(휴대폰에서 아래로 못 내려가면 안 되니까).
function bindDotHover(svgId, fmt) {
  const tip = $("chartTip"), svg = $(svgId);
  if (!svg) return;
  const show = (t, cx, cy) => {
    if (!t || t.tagName !== "circle") return;   // 빈 곳에서는 직전 값을 유지
    tip.innerHTML = fmt(t);
    tip.hidden = false;
    tip.style.left = Math.min(Math.max(8, cx + 14), innerWidth - 200) + "px";
    tip.style.top = Math.max(8, cy - 60) + "px";
  };
  svg.onmousemove = (ev) => show(ev.target, ev.clientX, ev.clientY);
  svg.onmouseleave = () => { tip.hidden = true; };
  let t0x = 0, t0y = 0, mode = 0;
  svg.addEventListener("touchstart", (ev) => {
    const t = ev.touches[0];
    t0x = t.clientX; t0y = t.clientY; mode = 0;
    show(document.elementFromPoint(t.clientX, t.clientY), t.clientX, t.clientY);
  }, { passive: true });
  svg.addEventListener("touchmove", (ev) => {
    const t = ev.touches[0];
    if (!mode) {
      const dx = Math.abs(t.clientX - t0x), dy = Math.abs(t.clientY - t0y);
      if (dx + dy < 8) return;
      const onDot = document.elementFromPoint(t0x, t0y);
      mode = ((onDot && onDot.tagName === "circle") || dx > dy) ? 1 : 2;
      if (mode === 2) tip.hidden = true;
    }
    if (mode === 1) {
      show(document.elementFromPoint(t.clientX, t.clientY), t.clientX, t.clientY);
      ev.preventDefault();
    }
  }, { passive: false });
  svg.addEventListener("touchend", () => setTimeout(() => { tip.hidden = true; }, 2500));
}

// ── 미티오그램 ──
const MODEL_COLOR = { ECMWF: "#c01c28", GFS: "#26914a", KIM: "#1a5fb4" };
const METEO_UNIT = { t2m: "℃", tcc: "%" };
let METEO = { date: null, data: null, v: "t2m" };

function renderMeteoCharts() {
  const d = METEO.data, v = METEO.v;
  if (!d) { $("meteoCharts").innerHTML = ""; return; }
  const t0ms = keyToMs(d.t0), i1 = d.steps - 1;
  let lo = Infinity, hi = -Infinity;
  d.models.forEach((m) => d.cities.forEach((c) => (d.series[m][c][v] || []).forEach((x) => {
    if (x != null) { lo = Math.min(lo, x); hi = Math.max(hi, x); }
  })));
  if (!isFinite(lo)) { $("meteoCharts").innerHTML = "<p class='note'>자료 없음</p>"; return; }
  if (v === "tcc") { lo = 0; hi = 100; }
  const pad = v === "tcc" ? 0 : Math.max(1, (hi - lo) * 0.12);
  $("meteoCharts").innerHTML = d.cities.map((c) => drawPanel({
    title: c, i0: 0, i1: i1, ylo: lo - pad, yhi: hi + pad,
    t0ms: t0ms, stepMs: 3 * 3600e3, w: 1160, h: 200,
    series: d.models.map((m) => ({ color: MODEL_COLOR[m] || "#666", data: d.series[m][c][v] })),
  })).join("");
  $("meteoLegend").innerHTML = d.models.map((m) =>
    `<span style="color:${MODEL_COLOR[m] || "#666"};font-weight:bold">■ ${m}</span>`
    + `<span style="color:#777;font-size:12px"> 런 ${d.runs[m].slice(4, 6)}-${d.runs[m].slice(6, 8)} ${d.runs[m].slice(8)}z</span>`
  ).join(" &nbsp; ");
  bindHover("meteoCharts", (city, i) => ({
    when: fmtWhen(t0ms + i * 3 * 3600e3),
    rows: d.models.map((m) => {
      const x = d.series[m][city][v] && d.series[m][city][v][i];
      return [m, x == null ? "—" : x.toFixed(v === "tcc" ? 0 : 1) + METEO_UNIT[v]];
    }),
  }));
}

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
  return `archive/${state.date}/${model.toLowerCase()}_${run}_f${String(stepH).padStart(3, "0")}_${state.panel}.webp`;
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
// 관측 실황을 이미지가 아니라 지점 값으로 그린다 (2026-08-27).
// 하루 2.3MB(WebP 63장) → 31KB. 모든 지점의 값을 마우스/터치로 읽을 수 있다.
// 지점 사이는 원래 관측이 없는 구간이라 점 표출이 보간 면보다 정직하다.
let obsState = { date: null, v: null, idx: 0, data: null, meta: null };

// 색을 구간으로 끊는다 — 연속 그라데이션은 '이 색이 몇 도인지'를 알 수 없다.
// 눈금과 원의 색이 정확히 같은 구간을 쓰도록 여기서 한 번에 정의한다 (2026-08-27).
function obsBins(sc) {
  const span = sc.vmax - sc.vmin;
  const step = [0.25, 0.5, 1, 2, 2.5, 5, 10, 20].find((p) => p >= span / 11) || 20;
  const lo = Math.floor(sc.vmin / step) * step;
  const edges = [];
  for (let e = lo; e <= sc.vmax + 1e-9; e += step) edges.push(+e.toFixed(3));
  const colors = edges.slice(0, -1).map((e, i) => {
    const t = Math.max(0, Math.min(1, ((e + step / 2) - sc.vmin) / span));
    return sc.colors[Math.round(t * (sc.colors.length - 1))];
  });
  return { edges: edges, colors: colors, step: step };
}
// 색은 연속으로(칸 안에서도 값 차이가 보이도록), 눈금은 칸으로(값대를 읽도록).
// 두 가지를 같은 색함수로 묶어 두어야 원과 눈금이 어긋나지 않는다.
function lerpColor(sc, t) {
  const cs = sc.colors;
  const x = Math.max(0, Math.min(1, t)) * (cs.length - 1);
  const i = Math.min(cs.length - 2, Math.floor(x)), f = x - i;
  const hex = (c) => [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)];
  const a = hex(cs[i]), b = hex(cs[i + 1]);
  const m = a.map((v, k) => Math.round(v + (b[k] - v) * f));
  return `rgb(${m[0]},${m[1]},${m[2]})`;
}
function obsColor(v, sc) {
  if (v == null) return null;
  return lerpColor(sc, (v - sc.vmin) / (sc.vmax - sc.vmin));
}

async function loadObs(ymd) {
  if (!obsState.meta) {
    obsState.meta = await (await fetch("obs/stations.json")).json();
    obsState.base = await (await fetch("basemap.json")).json();
  }
  if (obsState.date === ymd && obsState.data) return;
  obsState.data = await (await fetch(`obs/${ymd}.json?${Date.now()}`)).json();
  obsState.date = ymd;
}

function obsHours() {
  const vv = obsState.data && obsState.data.vars[obsState.v];
  if (!vv) return [];
  const set = new Set();
  Object.values(vv).forEach((arr) => arr.forEach((x, h) => { if (x != null) set.add(h); }));
  return [...set].sort((a, b) => a - b);
}

function renderObsVarBtns() {
  const present = Object.keys((obsState.data && obsState.data.vars) || {});
  const vars = OBS_ORDER.filter((v) => present.includes(v))
    .concat(present.filter((v) => !OBS_ORDER.includes(v)));
  if (!vars.length) {
    $("obsVarBtns").innerHTML = "";
    $("obsMap").innerHTML = "";
    $("obsLabel").textContent = "이 날짜엔 관측 자료 없음";
    return;
  }
  if (!vars.includes(obsState.v)) obsState.v = vars.includes("ta") ? "ta" : vars[0];
  $("obsVarBtns").innerHTML = vars.map((v) =>
    `<button data-v="${v}" class="${v === obsState.v ? "on" : ""}">${OBS_LABEL[v] || v}</button>`).join("");
  $("obsVarBtns").querySelectorAll("button").forEach((b) => {
    b.onclick = () => { obsState.v = b.dataset.v; renderObsVarBtns(); };
  });
  const hours = obsHours();
  $("obsSlider").max = Math.max(0, hours.length - 1);
  if (firstObs && hours.length) {
    const now = Date.now();
    obsState.idx = hours.reduce((bi, h, i) =>
      Math.abs(obsEpoch(obsState.date, h) - now) <
      Math.abs(obsEpoch(obsState.date, hours[bi]) - now) ? i : bi, 0);
    firstObs = false;
  }
  if (obsState.idx > hours.length - 1) obsState.idx = Math.max(0, hours.length - 1);
  renderObs();
}

function renderObs() {
  const hours = obsHours();
  if (!hours.length) { $("obsMap").innerHTML = ""; return; }
  $("obsSlider").value = obsState.idx;
  const h = hours[obsState.idx];
  const sc = obsState.meta.scales[obsState.v];
  const vv = obsState.data.vars[obsState.v];
  const bm = obsState.base;
  const bins = obsBins(sc);
  $("obsLabel").textContent =
    `${fmtDate(obsState.date)} ${String(h).padStart(2, "0")}시 KST 실황 — ${sc.label} (${relNow(obsEpoch(obsState.date, h))})`;

  let pts = "", lbl = "", n = 0;
  obsState.meta.stations.forEach((st) => {
    const arr = vv[String(st.s)];
    const v = arr && arr[h];
    const col = obsColor(v, sc);
    if (col == null) return;
    n++;
    pts += `<circle cx="${st.x}" cy="${st.y}" r="${st.L ? 8 : 7}" fill="${col}"`
         + ` stroke="${st.L ? "#000" : "#333"}" stroke-width="${st.L ? 1.4 : 0.7}"`
         + ` data-n="${st.n}" data-v="${v}"/>`;
    // 대표 도시는 값을 지도에 직접 — 흰 테두리로 어떤 배경색 위에서도 읽히게
    if (st.L) {
      const txt = `${st.n} ${v.toFixed(1)}`;
      lbl += `<text x="${st.x + 11}" y="${st.y + 5}" font-size="15" font-weight="bold"`
           + ` paint-order="stroke" stroke="#fff" stroke-width="3.5" fill="#111">${txt}</text>`;
    }
  });
  // 구간별 칸 + 경계 눈금 — 색이 어느 값대인지 바로 읽히도록
  const CW = 620, SW = CW / bins.colors.length;
  const span = sc.vmax - sc.vmin;
  const defs = bins.colors.map((_c, i) => {
    const a = lerpColor(sc, (bins.edges[i] - sc.vmin) / span);
    const b = lerpColor(sc, (bins.edges[i + 1] - sc.vmin) / span);
    return `<linearGradient id="cb${i}"><stop offset="0%" stop-color="${a}"/><stop offset="100%" stop-color="${b}"/></linearGradient>`;
  }).join("");
  const cells = bins.colors.map((_c, i) =>
    `<rect x="${(i * SW).toFixed(1)}" y="0" width="${SW.toFixed(1)}" height="22" fill="url(#cb${i})" stroke="#fff" stroke-width="0.8"/>`).join("");
  const ticks = bins.edges.map((e, i) =>
    `<line x1="${(i * SW).toFixed(1)}" y1="22" x2="${(i * SW).toFixed(1)}" y2="27" stroke="#666"/>`
    + `<text x="${(i * SW).toFixed(1)}" y="38" text-anchor="middle" font-size="12" fill="#444">${e}</text>`).join("");
  $("obsMap").innerHTML =
    `<svg id="obsSvg" viewBox="0 0 ${bm.w} ${bm.h}">
      <rect width="${bm.w}" height="${bm.h}" fill="#f7f9fb"/>
      <path d="${bm.paths.admin}" fill="none" stroke="#c9c9c9" stroke-width="0.8"/>
      <path d="${bm.paths.coast}" fill="none" stroke="#5a5a5a" stroke-width="1.2"/>
      ${pts}${lbl}
    </svg>
    <div class="cbar">
      <svg viewBox="-6 0 ${CW + 12} 44"><defs>${defs}</defs>${cells}${ticks}</svg>
      <div class="cbar-lab">${sc.label} (${sc.unit}) — 칸 하나 ${bins.step}${sc.unit === "℃" ? "℃" : ""}</div>
    </div>
    <p class="note">지점 ${n}곳 실측 — 원 색이 값. 마우스를 올리거나(휴대폰은 짚으면) 지점명과 값이 표시됩니다.</p>`;

  bindDotHover("obsSvg", (t) => {
    const unit = sc.unit === "℃" ? "℃" : " " + sc.unit;
    return `<b>${t.dataset.n}</b> ${String(h).padStart(2, "0")}시<br>${sc.label} ${(+t.dataset.v).toFixed(1)}${unit}`;
  });
}

$("obsSlider").oninput = (ev) => { obsState.idx = +ev.target.value; renderObs(); };
$("obsPrev").onclick = () => { if (obsState.idx > 0) { obsState.idx--; renderObs(); } };
$("obsNext").onclick = () => {
  if (obsState.idx < obsHours().length - 1) { obsState.idx++; renderObs(); }
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
async function renderMeteo() {
  const d = $("dateSelM").value;
  if (METEO.date !== d) {
    METEO.data = await (await fetch(`meteo/${d}.json?${Date.now()}`)).json();
    METEO.date = d;
  }
  renderMeteoCharts();
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
function renderVerif() {
  // 도시×모델×리드타임 ME/MAE 표는 제거 (2026-08-26 사용자: 보기 어렵고 필요성 낮음)
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
  const mdates = (MF.meteo_dates || []).slice().reverse();
  $("dateSelM").innerHTML = mdates.map((d) => `<option value="${d}">${fmtDate(d)}</option>`).join("");
  $("dateSelM").onchange = renderMeteo;
  $("meteoVarBtns").querySelectorAll("button").forEach((b) => {
    b.onclick = () => {
      METEO.v = b.dataset.v;
      $("meteoVarBtns").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
      renderMeteoCharts();
    };
  });

  const odates = (MF.obs_dates || []).slice().reverse();
  $("dateSelO").innerHTML = odates.map((d) => `<option value="${d}">${fmtDate(d)}</option>`).join("");
  const onObsDate = async () => { await loadObs($("dateSelO").value); renderObsVarBtns(); };
  $("dateSelO").onchange = onObsDate;
  if (odates.length) onObsDate();
  renderVm();

  // 예보-관측 탭 — 날짜 + 발표시각 선택
  const kdates = (MF.kmafcst_dates || []).slice().reverse();
  if (kdates.length) {
    $("dateSelK").innerHTML = kdates.map((d) => `<option value="${d}">${fmtDate(d)}</option>`).join("");
    const fillIssues = () => {
      const iss = Object.keys((KMAF.data && KMAF.data.fcst) || {}).sort().reverse();
      $("issueSelK").innerHTML = iss.map((b) =>
        `<option value="${b}">${b.slice(4, 6)}-${b.slice(6, 8)} ${b.slice(8)}시 발표</option>`).join("");
    };
    const loadK = async (d) => {   // 날짜 자료를 먼저 받아야 발표시각 목록을 채울 수 있다
      if (KMAF.date === d) return;
      KMAF.data = await (await fetch(`kmafcst/${d}.json?${Date.now()}`)).json();
      KMAF.date = d;
    };
    const onKDate = async () => {
      await loadK($("dateSelK").value);
      fillIssues();
      renderKmaf();
      renderFd();
    };
    $("dateSelK").onchange = onKDate;
    $("issueSelK").onchange = renderKmaf;
    onKDate();
  }

  // 나우캐스트 탭 — manifest.nowcast 있을 때만 노출
  if (MF.nowcast && MF.nowcast.issue) {
    $("nowcastTabBtn").hidden = false;
    const nc = MF.nowcast;
    const ep = Date.UTC(+nc.issue.slice(0, 4), +nc.issue.slice(4, 6) - 1,
                        +nc.issue.slice(6, 8), +nc.issue.slice(8, 10), +nc.issue.slice(10, 12));
    const k = new Date(ep + 9 * 3600e3);
    const p = (n) => String(n).padStart(2, "0");
    $("ncIssue").textContent =
      `발령 ${p(k.getUTCMonth() + 1)}-${p(k.getUTCDate())} ${p(k.getUTCHours())}:${p(k.getUTCMinutes())} KST (${relNow(ep)})`;
    const ncLeads = (nc.leads && nc.leads.length) ? nc.leads : [1, 2, 3];
    let ncIdx = 0;
    const renderNc = () => {
      const h = ncLeads[ncIdx];
      $("ncSlider").value = ncIdx;
      const vt = ep + h * 3600e3;
      $("ncLeadLabel").textContent =
        `+${h}시간 → 유효 ${p(new Date(vt + 9 * 3600e3).getUTCHours())}시 KST (${relNow(vt)})`;
      $("ncMap").src = `nowcast/map_${h}h.webp?${Date.now()}`;
      [ncIdx - 1, ncIdx + 1].forEach((i) => {   // 인접 스텝만 프리로드
        if (i >= 0 && i < ncLeads.length) new Image().src = `nowcast/map_${ncLeads[i]}h.webp`;
      });
    };
    $("ncSlider").max = ncLeads.length - 1;
    $("ncSlider").oninput = (e) => { ncIdx = +e.target.value; renderNc(); };
    $("ncPrev").onclick = () => { if (ncIdx > 0) { ncIdx--; renderNc(); } };
    $("ncNext").onclick = () => { if (ncIdx < ncLeads.length - 1) { ncIdx++; renderNc(); } };
    renderNc();
    if (nc.has_now) $("ncNow").src = `nowcast/map_0h.webp?${Date.now()}`;
    else $("ncNow").closest(".imgwrap").hidden = true;
    $("ncCities").src = `nowcast/cities.webp?${Date.now()}`;
    ["ncVerifyTitle", "ncVerifyNote", "ncVerify"].forEach((id) => { $(id).hidden = !nc.has_verify; });
    if (nc.has_verify) $("ncVerify").src = `nowcast/verify.webp?${Date.now()}`;
    // 과거 검증 패널 — 3시간 간격 보관분에서 선택
    const past = (nc.past || []).slice().reverse();
    if (past.length) {
      $("ncPastRow").hidden = false;
      $("ncPastSel").innerHTML = ['<option value="">지금 (최신)</option>'].concat(
        past.map((t) => `<option value="${t}">${t.slice(4, 6)}-${t.slice(6, 8)} ${t.slice(8)}시</option>`)
      ).join("");
      const showPast = () => {
        const v = $("ncPastSel").value;
        $("ncVerify").src = v ? `nowcast/archive/${v}.webp?${Date.now()}`
                              : `nowcast/verify.webp?${Date.now()}`;
      };
      $("ncPastSel").onchange = showPast;
      $("ncPastNow").onclick = () => { $("ncPastSel").value = ""; showPast(); };
    }
    const leads = Object.keys(nc.skill || {}).map(Number).sort((a, b) => a - b);
    $("ncSkill").innerHTML = !leads.length
      ? "<p class='note'>검증 표본 누적 중 — 발령 +6시간 후부터 자동 채점됩니다.</p>"
      : `<table><tr><th>리드</th>${leads.map((l) => `<th>+${l / 60}h</th>`).join("")}</tr>` +
        `<tr><td>skill(%)</td>${leads.map((l) => {
          const v = nc.skill[String(l)];
          return `<td style="color:${v >= 0 ? "#1a7a3c" : "#c22"}">${v > 0 ? "+" : ""}${v}</td>`;
        }).join("")}</tr></table>` +
        `<p class='note'>최근 7일, 발령 ${nc.n_issues}건 평균.</p>`;
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
