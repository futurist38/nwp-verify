/* NWP 모델 아카이브 뷰어 — 정적, 프레임워크 없음.
   manifest.json 이 유일한 진입점. 이미지는 현재 스텝 ±1만 프리로드(셀룰러 절약).
   2026-09-06 확장: 일사·강수 패널, 런 겹치기 띠·앙상블 폭·하늘 띠(Meteogram), 예보-관측 하늘 띠·오차 면,
   관측 전운량·평년편차, 중기예보 섹션, 일사 검증, 자동 재생·갱신 배지·야간 음영. */
"use strict";

const PANEL_LABEL = { t2m: "기온", tcc: "전운량", cloud3: "3층운량", dswrf: "일사", tp: "강수" };
const PANEL_ORDER = ["t2m", "tcc", "cloud3", "dswrf", "tp"];
const MODEL_COLOR = { ECMWF: "#c01c28", GFS: "#26914a", KIM: "#1a5fb4" };
const MODEL_SHORT = { ECMWF: "EC", GFS: "GFS", KIM: "KIM" };
let MF = null;
let state = { date: null, model: null, panel: null, stepIdx: 0, runs: {} };

const $ = (id) => document.getElementById(id);

// JSON 수신 — 일시적 연결 끊김(모바일·정적 서버)에 3회 재시도. 한 번 실패로 섹션이 비지 않게.
async function fetchJSON(url) {
  let err;
  for (let k = 0; k < 3; k++) {
    try {
      const r = await fetch(url);
      if (!r.ok) throw new Error(`${r.status} ${url}`);
      return await r.json();
    } catch (e) { err = e; await new Promise((res) => setTimeout(res, 300 * (k + 1))); }
  }
  throw err;
}

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

// ── 자동 재생 (슬라이더 공용) ──
// next(): 한 스텝 전진, atEnd(): 끝인지, rewind(): 처음으로. 끝에 닿으면 처음으로 돌아가 반복.
function makePlayer(btnId, next, atEnd, rewind, ms = 700) {
  const b = $(btnId);
  if (!b) return;
  let timer = null;
  const stop = () => { clearInterval(timer); timer = null; b.classList.remove("on"); b.textContent = "▶"; };
  b.onclick = () => {
    if (timer) { stop(); return; }
    b.classList.add("on"); b.textContent = "⏸";
    timer = setInterval(() => { if (atEnd()) rewind(); else next(); }, ms);
  };
  // 탭을 떠나면 멈춘다
  document.querySelectorAll("#tabs button").forEach((t) => t.addEventListener("click", () => { if (timer) stop(); }));
}

// ── 하늘 상태 색 문법 (Meteogram 띠 · 예보-관측 띠 · 관측 전운량 공통) ──
// 1 맑음(흰) · 2 구름많음(연회) · 3 흐림(진회) · 4 강수(하늘색). 기상청 구분(운량 0~5 / 6~8 / 9~10)에 맞춤.
const SKY_COLOR = { 1: "#ffffff", 2: "#c8c8c8", 3: "#7d7d7d", 4: "#8ec9ff" };
// 그래프 배경용(선 뒤에 깔리므로 옅게). 맑음은 칠하지 않는다(흰 배경 그대로).
const SKY_BG = { 1: null, 2: "rgba(200,200,200,.45)", 3: "rgba(125,125,125,.42)", 4: "rgba(142,201,255,.6)" };
const SKY_NAME = { 1: "맑음", 2: "구름많음", 3: "흐림", 4: "강수" };
function skyFromModel(tcc, tp, win) {
  // 3h 창 0.5mm(6h 창이면 1mm) 이상이면 강수
  if (tp != null && tp >= ((win || 3) > 3 ? 1.0 : 0.5)) return 4;
  if (tcc == null) return 0;
  return tcc >= 85 ? 3 : tcc >= 55 ? 2 : 1;
}
function skyFromKma(sky, pty) {        // 단기예보 SKY(1·3·4) + PTY(0 없음, 1비 2비/눈 3눈 4소나기)
  if (pty != null && pty > 0) return 4;
  if (sky == null) return 0;
  return sky >= 4 ? 3 : sky >= 3 ? 2 : 1;
}
function skyFromCa(ca) {               // ASOS 전운량 십분위
  if (ca == null) return 0;
  return ca >= 9 ? 3 : ca >= 6 ? 2 : 1;
}
const PTY_NAME = { 0: "", 1: "비", 2: "비/눈", 3: "눈", 4: "소나기" };

// ── 시계열 차트 (공용) ────────────────────────────────
// 이미지 대신 데이터를 받아 SVG로 그린다 — 용량이 30배 작고 값을 마우스/터치로 읽을 수 있다.
// 예보-관측·미티오그램·중기예보가 같은 렌더러를 쓴다.
function drawPanel(o) {
  // o: {title, series:[{color,dash,data,width,opacity,dotsOnly,hollow,r}], i0,i1, ylo,yhi, t0ms, stepMs, vline,
  //     w,h, night, now, bands:[{lo,hi,color,opacity}], whiskers:[{idx,lo,hi,mid,color}],
  //     fills:[{a,b,pos,neg,opacity}], strips:[{label,cells:[color|null],names:[...]}], unit}
  const W = o.w || 400, ML = 38, MR = 10, MT = 16;
  const strips = o.strips || [], SH = 9, SG = 2;
  const stripH = strips.length ? strips.length * (SH + SG) + 3 : 0;
  const MB = 24 + stripH;
  const H = (o.h || 210) + stripH;
  const PB = H - MB;                                   // 플롯 바닥(x축)
  const n = Math.max(1, o.i1 - o.i0);
  const X = (i) => ML + ((i - o.i0) / n) * (W - ML - MR);
  const Y = (v) => MT + ((o.yhi - v) / Math.max(1e-6, o.yhi - o.ylo)) * (PB - MT);
  const perStep = (W - ML - MR) / n, half = perStep / 2;
  const stepH = o.stepMs / 3600e3;
  const f1 = (x) => x.toFixed(1);
  let g = "";

  // 플롯 안쪽 배경 띠 (2026-09-06 사용자 지정): y축을 행 수만큼 나눠 위→아래 순서로 깔고,
  // 시간 칸마다 하늘 상태 색을 채운다. 선이 그 위에 그려지므로 색은 옅게.
  const bgs = o.bgStrips || [];
  if (bgs.length) {
    const rowH = (PB - MT) / bgs.length;
    bgs.forEach((sp, r) => {
      const y0 = MT + r * rowH;
      for (let i = o.i0; i <= o.i1; i++) {
        const c = sp.cells[i];
        if (!c) continue;
        const x0 = Math.max(ML, X(i) - half), x1 = Math.min(W - MR, X(i) + half);
        g += `<rect x="${f1(x0)}" y="${f1(y0)}" width="${f1(x1 - x0)}" height="${f1(rowH)}" fill="${c}"/>`;
      }
      if (r) g += `<line x1="${ML}" y1="${f1(y0)}" x2="${W - MR}" y2="${f1(y0)}" stroke="#999" stroke-dasharray="2 3"/>`;
      g += `<text x="${W - MR - 3}" y="${f1(y0 + 11)}" text-anchor="end" font-size="10" font-weight="bold" fill="${sp.color || "#555"}" opacity=".8">${sp.label}</text>`;
    });
  }
  // 야간 음영 (18~06 KST) — 낮/밤 리듬이 보이면 일최고·일최저 위치가 바로 읽힌다
  if (o.night && stepH < 24) {
    for (let i = o.i0; i <= o.i1; i++) {
      const h = new Date(o.t0ms + i * o.stepMs + 9 * 3600e3).getUTCHours();
      if (h >= 18 || h < 6) {
        g += `<rect x="${f1(Math.max(ML, X(i) - half))}" y="${MT}" width="${f1(Math.min(perStep, X(i) + half - Math.max(ML, X(i) - half)))}" height="${f1(PB - MT)}" fill="#eef1f5"/>`;
      }
    }
  }
  const span = o.yhi - o.ylo;
  const gy = span > 600 ? 200 : span > 250 ? 100 : span > 60 ? 20 : span > 25 ? 10 : span > 12 ? 5 : span > 5 ? 2 : 1;
  for (let v = Math.ceil(o.ylo / gy) * gy; v <= o.yhi; v += gy) {
    g += `<line x1="${ML}" y1="${f1(Y(v))}" x2="${W - MR}" y2="${f1(Y(v))}" stroke="#d5d5d5"/>`
       + `<text x="${ML - 4}" y="${f1(Y(v) + 4)}" text-anchor="end" font-size="10" fill="#666">${v}</text>`;
  }
  // x 라벨: 라벨끼리 60px 이상 떨어지도록 자동 조절. 일 단위 격자는 날짜 라벨.
  if (stepH >= 24) {
    const every = Math.max(1, Math.ceil(60 / perStep));
    for (let i = o.i0; i <= o.i1; i++) {
      const d = new Date(o.t0ms + i * o.stepMs + 9 * 3600e3);
      const isSun = d.getUTCDay() === 0;
      g += `<line x1="${f1(X(i))}" y1="${MT}" x2="${f1(X(i))}" y2="${PB}" stroke="${isSun ? "#f0c9c9" : "#e2e2e2"}"/>`;
      if ((i - o.i0) % every === 0) {
        g += `<text x="${f1(X(i))}" y="${H - 10}" text-anchor="middle" font-size="10" fill="${isSun ? "#c22" : "#666"}">${d.getUTCMonth() + 1}/${d.getUTCDate()}</text>`;
      }
    }
  } else {
    let labH = 6;
    while (perStep * (labH / stepH) < 60) labH += stepH;
    for (let i = o.i0; i <= o.i1; i++) {
      const d = new Date(o.t0ms + i * o.stepMs + 9 * 3600e3);
      if (d.getUTCHours() % labH) continue;
      const lab = d.getUTCHours() === 0 ? `${d.getUTCMonth() + 1}/${d.getUTCDate()}` : d.getUTCHours() + "시";
      g += `<line x1="${f1(X(i))}" y1="${MT}" x2="${f1(X(i))}" y2="${PB}" stroke="${d.getUTCHours() === 0 ? "#c9c9c9" : "#e2e2e2"}"/>`
         + `<text x="${f1(X(i))}" y="${H - 10}" text-anchor="middle" font-size="10" fill="#666">${lab}</text>`;
    }
  }
  // 띠 (런 범위·앙상블 등)
  (o.bands || []).forEach((bd) => {
    let up = "", down = [], pen = false;
    const flush = () => { if (up) g += `<path d="${up}${down.reverse().join(" ")} Z" fill="${bd.color}" opacity="${bd.opacity || 0.14}" stroke="none"/>`; up = ""; down = []; pen = false; };
    for (let i = o.i0; i <= o.i1; i++) {
      const lo = bd.lo[i], hi = bd.hi[i];
      if (lo == null || hi == null) { flush(); continue; }
      up += (pen ? "L" : "M") + f1(X(i)) + " " + f1(Y(hi)) + " ";
      down.push("L" + f1(X(i)) + " " + f1(Y(lo)));
      pen = true;
    }
    flush();
  });
  // 오차 면 (a − b 의 부호로 색) — 예보-관측
  (o.fills || []).forEach((fl) => {
    for (let i = o.i0; i < o.i1; i++) {
      const a0 = fl.a[i], a1 = fl.a[i + 1], b0 = fl.b[i], b1 = fl.b[i + 1];
      if ([a0, a1, b0, b1].some((v) => v == null)) continue;
      const d0 = a0 - b0, d1 = a1 - b1;
      const poly = (pts, col) => { g += `<polygon points="${pts.map((p) => f1(p[0]) + "," + f1(p[1])).join(" ")}" fill="${col}" opacity="${fl.opacity || 0.18}"/>`; };
      if (d0 * d1 >= 0) {
        poly([[X(i), Y(a0)], [X(i + 1), Y(a1)], [X(i + 1), Y(b1)], [X(i), Y(b0)]], (d0 + d1) >= 0 ? fl.pos : fl.neg);
      } else {
        const t = d0 / (d0 - d1), xc = X(i) + t * (X(i + 1) - X(i)), yc = Y(a0 + t * (a1 - a0));
        poly([[X(i), Y(a0)], [xc, yc], [X(i), Y(b0)]], d0 >= 0 ? fl.pos : fl.neg);
        poly([[xc, yc], [X(i + 1), Y(a1)], [X(i + 1), Y(b1)]], d1 >= 0 ? fl.pos : fl.neg);
      }
    }
  });
  // 기준선(발표시각) · 지금
  if (o.vline != null && o.vline >= o.i0 && o.vline <= o.i1) {
    g += `<line x1="${f1(X(o.vline))}" y1="${MT}" x2="${f1(X(o.vline))}" y2="${PB}" stroke="#1a5fb4" stroke-dasharray="3 3"/>`;
  }
  if (o.now != null) {
    const iNow = (o.now - o.t0ms) / o.stepMs;
    if (iNow >= o.i0 && iNow <= o.i1) {
      g += `<line x1="${f1(X(iNow))}" y1="${MT}" x2="${f1(X(iNow))}" y2="${PB}" stroke="#e01b24" stroke-width="1.2" stroke-dasharray="4 3" opacity=".8"/>`
         + `<text x="${f1(X(iNow) + 3)}" y="${MT + 10}" font-size="10" fill="#e01b24">지금</text>`;
    }
  }
  // 선·점 — 빈 칸 하나(ECMWF 144h 이후 6h 간격이 3h 격자에 놓일 때)는 건너 이어 그린다
  const path = (arr) => {
    let out = "", pen = false, gap = 0;
    for (let i = o.i0; i <= o.i1; i++) {
      const v = arr && arr[i];
      if (v == null) { gap++; if (gap > 1) pen = false; continue; }
      gap = 0;
      out += (pen ? "L" : "M") + f1(X(i)) + " " + f1(Y(v)) + " ";
      pen = true;
    }
    return out;
  };
  const dots = (se) => {
    let out = "";
    const r = se.r || 2;
    for (let i = o.i0; i <= o.i1; i++) {
      const v = se.data && se.data[i];
      if (v != null) out += `<circle cx="${f1(X(i))}" cy="${f1(Y(v))}" r="${r}" fill="${se.hollow ? "#fff" : se.color}" stroke="${se.color}" stroke-width="${se.hollow ? 1.5 : 0}"${se.opacity != null ? ` opacity="${se.opacity}"` : ""}/>`;
    }
    return out;
  };
  const lines = o.series.map((se) => se.dotsOnly ? "" :
    `<path d="${path(se.data)}" fill="none" stroke="${se.color}" stroke-width="${se.width || 1.7}"`
    + (se.dash ? ` stroke-dasharray="${se.dash}"` : "") + (se.opacity != null ? ` opacity="${se.opacity}"` : "") + "/>").join("");
  const pts = o.series.map((se) => (se.noDots ? "" : dots(se))).join("");
  // 앙상블 등 세로 막대
  let wh = "";
  (o.whiskers || []).forEach((wk) => {
    wk.idx.forEach((i, k) => {
      if (i < o.i0 || i > o.i1 || wk.lo[k] == null || wk.hi[k] == null) return;
      const x = f1(X(i)), y0 = f1(Y(wk.hi[k])), y1 = f1(Y(wk.lo[k]));
      wh += `<line x1="${x}" y1="${y0}" x2="${x}" y2="${y1}" stroke="${wk.color}" stroke-width="${wk.width || 2.2}" opacity=".55"/>`
          + `<line x1="${f1(X(i) - 3.5)}" y1="${y0}" x2="${f1(X(i) + 3.5)}" y2="${y0}" stroke="${wk.color}" stroke-width="1.2" opacity=".7"/>`
          + `<line x1="${f1(X(i) - 3.5)}" y1="${y1}" x2="${f1(X(i) + 3.5)}" y2="${y1}" stroke="${wk.color}" stroke-width="1.2" opacity=".7"/>`;
      if (wk.mid && wk.mid[k] != null) wh += `<circle cx="${x}" cy="${f1(Y(wk.mid[k]))}" r="1.8" fill="${wk.color}"/>`;
    });
  });
  // 하늘 띠
  let st = "";
  strips.forEach((sp, r) => {
    const y = PB + 3 + r * (SH + SG);
    st += `<text x="${ML - 3}" y="${f1(y + SH - 1)}" text-anchor="end" font-size="8.5" fill="#666">${sp.label}</text>`;
    for (let i = o.i0; i <= o.i1; i++) {
      const c = sp.cells[i];
      if (!c) continue;
      const x0 = Math.max(ML, X(i) - half), x1 = Math.min(W - MR, X(i) + half);
      st += `<rect x="${f1(x0)}" y="${f1(y)}" width="${f1(x1 - x0)}" height="${SH}" fill="${c}" stroke="#bbb" stroke-width=".4"/>`;
    }
  });
  if (strips.length) st += `<line x1="${ML}" y1="${PB}" x2="${W - MR}" y2="${PB}" stroke="#999"/>`;
  return `<svg viewBox="0 0 ${W} ${H}" data-t="${o.title}" data-ml="${ML}" data-mr="${MR}"
    data-i0="${o.i0}" data-i1="${o.i1}" data-w="${W}">${g}${lines}${wh}${pts}${st}
    <text x="${ML + 2}" y="${MT - 4}" font-size="12" font-weight="bold">${o.title}</text>
    <line class="cross" x1="0" y1="${MT}" x2="0" y2="${PB}" stroke="#e01b24" stroke-width="1" opacity="0"/>
  </svg>`;
}

function bindHover(container, lookup) {
  // lookup(title, i) → {when, rows:[[이름, 값문자열], ...]}  (행이 많으면 줄바꿈)
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
      const sep = info.rows.length > 3 ? "<br>" : " · ";
      tip.innerHTML = `<b>${title}</b> ${info.when}<br>` + info.rows.map((kv) => `${kv[0]} ${kv[1]}`).join(sep);
      tip.hidden = false;
      tip.style.left = Math.min(Math.max(8, cx + 14), innerWidth - 260) + "px";
      tip.style.top = Math.max(8, cy - 70) + "px";
    };
    svg.onmousemove = (ev) => at(ev.clientX, ev.clientY);
    svg.onmouseleave = () => { tip.hidden = true; cross.setAttribute("opacity", 0); };
    // 터치: 짚은 채 좌우로 움직이면 값을 훑을 수 있게. 세로로 긋는 동작은 페이지 스크롤로 넘긴다.
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
function fmtDay(ms) {
  const d = new Date(ms + 9 * 3600e3), p2 = (x) => String(x).padStart(2, "0");
  return `${p2(d.getUTCMonth() + 1)}-${p2(d.getUTCDate())}(${"일월화수목금토"[d.getUTCDay()]})`;
}

// ── 예보-관측 ──
let KMAF = { date: null, data: null };

function renderKmaf() {
  const d = KMAF.data, b = $("issueSelK").value;
  if (!d || !d.fcst[b]) { $("kmafCharts").innerHTML = ""; return; }
  const t0ms = keyToMs(d.t0);
  const iIss = Math.round((keyToMs(b) - t0ms) / 3600e3);
  // 창은 발표 -6h 부터, 끝은 발표일에 따라 다르다.
  //   전날 발표(11·17시) → 대상일 23시   /  당일 발표(05·11·17시) → 내일 23시 (2026-09-01 사용자 요청)
  const ymd = $("dateSelK").value;
  const endMs = keyToMs(ymd + "23") + (b.slice(0, 8) === ymd ? 24 * 3600e3 : 0);
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
  const sky = d.sky && d.sky[b], pty = d.pty && d.pty[b], pop = d.pop && d.pop[b];
  $("kmafCharts").innerHTML = d.cities.map((c) => {
    // 그래프 배경을 위·아래 두 단으로: 위 = 예보 하늘(SKY·PTY), 아래 = 실측 하늘(전운량) (2026-09-06 사용자 지정)
    const strips = [];
    if (sky && sky[c]) {
      strips.push({ label: "예보", color: "#1a5fb4",
                    cells: sky[c].map((s, i) => { const k = skyFromKma(s, pty && pty[c] ? pty[c][i] : null); return k ? SKY_BG[k] : null; }) });
    }
    if (d.obs_ca && d.obs_ca[c]) {
      strips.push({ label: "실측", color: "#111",
                    cells: d.obs_ca[c].map((v) => { const k = skyFromCa(v); return k ? SKY_BG[k] : null; }) });
    }
    return drawPanel({
      title: c, i0: i0, i1: i1, ylo: lo - pad, yhi: hi + pad,
      t0ms: t0ms, stepMs: 3600e3, vline: iIss, night: !strips.length, now: Date.now(),
      fills: [{ a: d.fcst[b][c] || [], b: d.obs[c] || [], pos: "rgba(200,30,30,1)", neg: "rgba(30,90,200,1)", opacity: 0.16 }],
      series: [{ color: "#1a5fb4", dash: "5 3", data: d.fcst[b][c] },
               { color: "#111", data: d.obs[c] }],
      bgStrips: strips,
    });
  }).join("");
  bindHover("kmafCharts", (city, i) => {
    const o = d.obs[city] && d.obs[city][i], f = d.fcst[b][city] && d.fcst[b][city][i];
    const rows = [["실측", o == null ? "—" : o.toFixed(1) + "℃"],
                  ["예보", f == null ? "—" : f.toFixed(1) + "℃"]];
    if (o != null && f != null) rows.push(["차이", (f - o > 0 ? "+" : "") + (f - o).toFixed(1) + "℃"]);
    if (sky && sky[city] && sky[city][i] != null) {
      const s = sky[city][i], p = pty && pty[city] ? pty[city][i] : null, pp = pop && pop[city] ? pop[city][i] : null;
      rows.push(["예보 하늘", SKY_NAME[skyFromKma(s, p)] + (p ? `(${PTY_NAME[p] || p})` : "") + (pp != null ? ` · 강수확률 ${pp}%` : "")]);
    }
    if (d.obs_ca && d.obs_ca[city] && d.obs_ca[city][i] != null) rows.push(["실측 전운량", d.obs_ca[city][i] + "/10"]);
    return { when: fmtWhen(t0ms + i * 3600e3), rows: rows };
  });
}

// ── 예보 변화 (지점값 표출) ─────────────────────────────
const FD_SCALE = { vmin: -3, vmax: 3, step: 0.5, label: "예보 변화", unit: "℃" };
let FD = { date: null, data: null, v: "tmx" };

function divColor(d, vmax) {   // 빨강=양 · 파랑=음 (0 근처는 흰색)
  const t = Math.max(-1, Math.min(1, d / vmax));
  const mix = (a, b, f) => a.map((x, i) => Math.round(x + (b[i] - x) * f));
  const W = [247, 247, 247], R = [176, 24, 43], B = [33, 102, 172];
  const c = t >= 0 ? mix(W, R, t) : mix(W, B, -t);
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}
const fdColor = (d) => divColor(d, FD_SCALE.vmax);

function divColorbar(vmin, vmax, step, colorFn, idPrefix) {
  const nb = Math.round((vmax - vmin) / step);
  const CW = 620, SW = CW / nb;
  let defs = "", cells = "", ticks = "";
  for (let i = 0; i < nb; i++) {
    const a = vmin + i * step, b = a + step;
    defs += `<linearGradient id="${idPrefix}${i}"><stop offset="0%" stop-color="${colorFn(a)}"/>`
          + `<stop offset="100%" stop-color="${colorFn(b)}"/></linearGradient>`;
    cells += `<rect x="${(i * SW).toFixed(1)}" y="0" width="${SW.toFixed(1)}" height="22" fill="url(#${idPrefix}${i})" stroke="#fff" stroke-width="0.8"/>`;
  }
  for (let i = 0; i <= nb; i++) {
    const e = vmin + i * step;
    if (i % 2) continue;
    ticks += `<line x1="${(i * SW).toFixed(1)}" y1="22" x2="${(i * SW).toFixed(1)}" y2="27" stroke="#666"/>`
           + `<text x="${(i * SW).toFixed(1)}" y="38" text-anchor="middle" font-size="12" fill="#444">${e > 0 ? "+" : ""}${e}</text>`;
  }
  return `<svg viewBox="-6 0 ${CW + 12} 44"><defs>${defs}</defs>${cells}${ticks}</svg>`;
}

async function renderFd() {
  const d = $("dateSelK").value;
  const on = (MF.fd_dates || []).includes(d);
  $("fdTitle").hidden = !on;
  $("fdTitle").nextElementSibling.hidden = !on;
  $("fdPair").hidden = !on;
  if (!on) return;
  if (FD.date !== d) {
    FD.data = await fetchJSON(`fcstdiff/${d}.json?${Date.now()}`);
    FD.date = d;
  }
  if (!obsState.meta) {
    obsState.meta = await fetchJSON("obs/stations.json");
    obsState.base = await fetchJSON("basemap.json");
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
  const p2 = (x) => x.slice(4, 6) + "-" + x.slice(6, 8) + " " + x.slice(8) + "시";
  $("fdMap").innerHTML =
    `<div class="step-label">${p2(FD.data.prev)} 발표 대비 ${p2(FD.data.now)} 발표 · 대상 ${fmtDate(FD.data.target)}</div>
     <svg id="fdSvg" viewBox="0 0 ${bm.w} ${bm.h}">
      <rect width="${bm.w}" height="${bm.h}" fill="#f7f9fb"/>
      <path d="${bm.paths.admin}" fill="none" stroke="#c9c9c9" stroke-width="0.8"/>
      <path d="${bm.paths.coast}" fill="none" stroke="#5a5a5a" stroke-width="1.2"/>
      ${pts}${lbl}
     </svg>
     <div class="cbar">${divColorbar(FD_SCALE.vmin, FD_SCALE.vmax, FD_SCALE.step, fdColor, "fg")}
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

// ── 중기예보 ────────────────────────────────────────
let MID = { data: null };
const MID_CITIES = ["서울", "대전", "대구", "부산", "광주", "강릉"];

async function renderMid() {
  if (!MF.midfcst) { $("midBlock").hidden = true; return; }
  if (!MID.data) {
    try { MID.data = await fetchJSON(`midfcst/index.json?${Date.now()}`); }
    catch (e) { $("midBlock").hidden = true; return; }
    const iss = MID.data.issues.slice().sort().reverse();
    $("midIssueSel").innerHTML = iss.map((t) =>
      `<option value="${t}">${t.slice(4, 6)}-${t.slice(6, 8)} ${t.slice(8)}시 발표</option>`).join("");
    $("midIssueSel").onchange = renderMid;
  }
  $("midBlock").hidden = false;
  const d = MID.data, T = $("midIssueSel").value;
  const fc = d.fcst[T];
  if (!fc) { $("midCharts").innerHTML = "<p class='note'>자료 없음</p>"; return; }
  const cities = MID_CITIES.filter((c) => d.cities.includes(c));
  // 일 격자: 발표일 −7일 ~ +10일
  const tIss = keyToMs(T.slice(0, 8) + "00");
  const t0ms = tIss - 7 * 864e5, n = 18, stepMs = 864e5;
  const dayKey = (i) => { const dd = new Date(t0ms + i * stepMs + 9 * 3600e3); return `${dd.getUTCFullYear()}${String(dd.getUTCMonth() + 1).padStart(2, "0")}${String(dd.getUTCDate()).padStart(2, "0")}`; };
  const keys = Array.from({ length: n }, (_, i) => dayKey(i));
  // 이전 발표 1~3일 전 (같은 시각 우선)
  const prevIss = [1, 2, 3].map((k) => {
    const dd = new Date(tIss - k * 864e5 + 9 * 3600e3);
    const ymd = `${dd.getUTCFullYear()}${String(dd.getUTCMonth() + 1).padStart(2, "0")}${String(dd.getUTCDate()).padStart(2, "0")}`;
    return d.issues.includes(ymd + T.slice(8)) ? ymd + T.slice(8) : d.issues.filter((x) => x.startsWith(ymd)).sort().pop();
  }).filter(Boolean);
  const arrOf = (src, c, k) => keys.map((ymd) => (src && src[c] && src[c][ymd] && src[c][ymd][k] != null) ? src[c][ymd][k] : null);
  let lo = Infinity, hi = -Infinity;
  const bump = (arr) => arr.forEach((v) => { if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
  cities.forEach((c) => { bump(arrOf(fc, c, 0)); bump(arrOf(fc, c, 1)); bump(arrOf(d.obs, c, 0)); bump(arrOf(d.obs, c, 1)); });
  if (!isFinite(lo)) { $("midCharts").innerHTML = "<p class='note'>자료 없음</p>"; return; }
  const pad = Math.max(1.5, (hi - lo) * 0.1);
  const fade = [0.5, 0.35, 0.22];
  $("midCharts").innerHTML = cities.map((c) => {
    const mx = arrOf(fc, c, 0 + 1), mn = arrOf(fc, c, 0);
    const series = [];
    prevIss.forEach((pi, k) => {
      series.push({ color: "#c01c28", data: arrOf(d.fcst[pi], c, 1), width: 1, opacity: fade[k], dash: "3 2", noDots: true });
      series.push({ color: "#1a5fb4", data: arrOf(d.fcst[pi], c, 0), width: 1, opacity: fade[k], dash: "3 2", noDots: true });
    });
    series.push({ color: "#c01c28", data: mx, width: 2.2, r: 2.5 });
    series.push({ color: "#1a5fb4", data: mn, width: 2.2, r: 2.5 });
    series.push({ color: "#111", data: arrOf(d.obs, c, 0), dotsOnly: true, r: 3.2 });
    series.push({ color: "#111", data: arrOf(d.obs, c, 1), dotsOnly: true, hollow: true, r: 3.2 });
    const idx = keys.map((_, i) => i);
    const whisk = [
      { idx: idx, lo: mx.map((v, i) => v == null ? null : v - (arrOf(fc, c, 4)[i] || 0)), hi: mx.map((v, i) => v == null ? null : v + (arrOf(fc, c, 5)[i] || 0)), color: "#c01c28", width: 1.4 },
      { idx: idx, lo: mn.map((v, i) => v == null ? null : v - (arrOf(fc, c, 2)[i] || 0)), hi: mn.map((v, i) => v == null ? null : v + (arrOf(fc, c, 3)[i] || 0)), color: "#1a5fb4", width: 1.4 },
    ];
    return drawPanel({ title: c, i0: 0, i1: n - 1, ylo: lo - pad, yhi: hi + pad, t0ms: t0ms, stepMs: stepMs,
                       vline: 7, now: Date.now(), series: series, whiskers: whisk, h: 220 });
  }).join("");
  bindHover("midCharts", (city, i) => {
    const ymd = keys[i], f = fc[city] && fc[city][ymd], o = d.obs[city] && d.obs[city][ymd];
    const rows = [];
    if (f) rows.push(["최고 예보", `${f[1]}℃ (−${f[4] || 0}/+${f[5] || 0})`], ["최저 예보", `${f[0]}℃ (−${f[2] || 0}/+${f[3] || 0})`]);
    prevIss.forEach((pi, k) => {
      const g = d.fcst[pi] && d.fcst[pi][city] && d.fcst[pi][city][ymd];
      if (g) rows.push([`${k + 1}일 전 발표`, `${g[1]} / ${g[0]}℃`]);
    });
    if (o) rows.push(["실측 최고/최저", `${o[0]} / ${o[1]}℃`]);
    if (!rows.length) rows.push(["—", "자료 없음"]);
    return { when: fmtDay(t0ms + i * stepMs), rows: rows };
  });
}

// ── 미티오그램 ──
const METEO_UNIT = { t2m: "℃", tcc: "%", dswrf: "W/m²", tp: "mm" };
const METEO_ND = { t2m: 1, tcc: 0, dswrf: 0, tp: 1 };
const STRIP_ORDER = ["ECMWF", "KIM", "GFS"];   // 위 → 아래 (사용자 지정)
let METEO = { date: null, data: null, v: "t2m", prevMode: "band", strips: true };   // 앙상블은 보류(2026-09-06 사용자)

function renderMeteoCharts() {
  const d = METEO.data, v = METEO.v;
  if (!d) { $("meteoCharts").innerHTML = ""; return; }
  const t0ms = keyToMs(d.t0), i1 = d.steps - 1;
  const hasPrev = d.prev && Object.keys(d.prev).length;
  $("prevModeBtn").hidden = !hasPrev;
  let lo = Infinity, hi = -Infinity;
  const bump = (x) => { if (x != null) { lo = Math.min(lo, x); hi = Math.max(hi, x); } };
  d.models.forEach((m) => d.cities.forEach((c) => (d.series[m][c][v] || []).forEach(bump)));
  if (hasPrev && METEO.prevMode !== "off" && (v === "t2m" || v === "tcc")) {
    Object.values(d.prev).forEach((runs) => Object.values(runs).forEach((cs) =>
      d.cities.forEach((c) => (cs[c] && cs[c][v] || []).forEach(bump))));
  }
  if (!isFinite(lo)) { $("meteoCharts").innerHTML = "<p class='note'>자료 없음</p>"; return; }
  if (v === "tcc") { lo = 0; hi = 100; }
  if (v === "dswrf") { lo = 0; hi = Math.max(200, Math.ceil(hi / 100) * 100); }
  if (v === "tp") { lo = 0; hi = Math.max(2, Math.ceil(hi)); }
  const pad = (v === "tcc" || v === "dswrf" || v === "tp") ? 0 : Math.max(1, (hi - lo) * 0.12);

  $("meteoCharts").innerHTML = d.cities.map((c) => {
    const series = [], bands = [], strips = [];
    d.models.forEach((m) => {
      const col = MODEL_COLOR[m] || "#666";
      const runs = hasPrev && d.prev[m] ? Object.keys(d.prev[m]).sort() : [];
      if (METEO.prevMode !== "off" && runs.length && (v === "t2m" || v === "tcc")) {
        if (METEO.prevMode === "band") {
          const lo_ = [], hi_ = [];
          for (let i = 0; i <= i1; i++) {
            const vals = runs.map((r) => d.prev[m][r][c] && d.prev[m][r][c][v] && d.prev[m][r][c][v][i])
                             .concat([d.series[m][c][v] && d.series[m][c][v][i]]).filter((x) => x != null);
            lo_.push(vals.length >= 2 ? Math.min(...vals) : null);
            hi_.push(vals.length >= 2 ? Math.max(...vals) : null);
          }
          bands.push({ lo: lo_, hi: hi_, color: col, opacity: 0.16 });
        } else {
          runs.slice().reverse().forEach((r, k) => {
            series.push({ color: col, data: d.prev[m][r][c] && d.prev[m][r][c][v], width: 1,
                          opacity: [0.55, 0.42, 0.3, 0.2][k] || 0.2, dash: "3 3", noDots: true });
          });
        }
      }
      series.push({ color: col, data: d.series[m][c][v], width: 2 });
    });
    if (METEO.strips) {
      STRIP_ORDER.filter((m) => d.models.includes(m)).forEach((m) => {
        const s = d.series[m][c], w = (d.wins && d.wins[m]) || [];
        const cells = [];
        for (let i = 0; i <= i1; i++) {
          const cls = skyFromModel(s.tcc && s.tcc[i], s.tp && s.tp[i], w[i]);
          cells.push(cls ? SKY_BG[cls] : null);
        }
        // 6h 창(ECMWF 144h 이후)은 3h 격자 두 칸에 걸친다 — 앞 칸이 비면 같은 색으로 채운다
        for (let i = 1; i <= i1; i++) {
          if (w[i] === 6 && cells[i - 1] == null) {
            const cls = skyFromModel(s.tcc && s.tcc[i], s.tp && s.tp[i], w[i]);
            if (cls) cells[i - 1] = SKY_BG[cls];
          }
        }
        strips.push({ label: MODEL_SHORT[m], cells: cells, color: MODEL_COLOR[m] });
      });
    }
    return drawPanel({ title: c, i0: 0, i1: i1, ylo: lo - pad, yhi: hi + pad, t0ms: t0ms, stepMs: 3 * 3600e3,
                       w: 1160, h: 250, night: !METEO.strips, now: Date.now(), series: series, bands: bands,
                       bgStrips: strips });
  }).join("");

  const runTxt = (r) => `${r.slice(4, 6)}-${r.slice(6, 8)} ${r.slice(8)}z`;
  $("meteoLegend").innerHTML = d.models.map((m) => {
    const prev = hasPrev && d.prev[m] ? Object.keys(d.prev[m]).sort() : [];
    return `<span class="legend-chip" style="border-color:${MODEL_COLOR[m]}"><b style="color:${MODEL_COLOR[m]}">■ ${m}</b> 런 ${runTxt(d.runs[m])}`
      + (prev.length && METEO.prevMode !== "off" ? `<span style="color:#888"> · 이전 ${prev.length}런 (${runTxt(prev[0])}~)</span>` : "") + `</span>`;
  }).join("");

  bindHover("meteoCharts", (city, i) => {
    const rows = d.models.map((m) => {
      const x = d.series[m][city][v] && d.series[m][city][v][i];
      let s = x == null ? "—" : x.toFixed(METEO_ND[v]) + METEO_UNIT[v];
      if (hasPrev && d.prev[m] && METEO.prevMode !== "off" && (v === "t2m" || v === "tcc")) {
        const vals = Object.values(d.prev[m]).map((cs) => cs[city] && cs[city][v] && cs[city][v][i]).filter((y) => y != null);
        if (vals.length) s += ` <span style="color:#888">(이전 런 ${Math.min(...vals).toFixed(METEO_ND[v])}~${Math.max(...vals).toFixed(METEO_ND[v])})</span>`;
      }
      return [m, s];
    });
    if (METEO.strips) {
      const sk = STRIP_ORDER.filter((m) => d.models.includes(m)).map((m) => {
        const s = d.series[m][city], w = (d.wins && d.wins[m]) || [];
        const cls = skyFromModel(s.tcc && s.tcc[i], s.tp && s.tp[i], w[i]);
        const tp = s.tp && s.tp[i];
        return `${MODEL_SHORT[m]} ${SKY_NAME[cls] || "—"}${tp != null && tp >= 0.1 ? ` ${tp.toFixed(1)}mm` : ""}`;
      });
      rows.push(["하늘", sk.join(" · ")]);
    }
    return { when: fmtWhen(t0ms + i * 3 * 3600e3), rows: rows };
  });
}

// ── 유틸 ──
function fmtDate(ymd) {
  return `${ymd.slice(0, 4)}-${ymd.slice(4, 6)}-${ymd.slice(6, 8)}`;
}
function validKST(run10, stepH) {
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
  const e = entry().models[m];
  const r = state.runs[m];
  return (r && e.runs[r]) ? r : e.latest;
}
function runEntry(m) { const e = entry().models[m]; const r = runOf(m); return { run: r, ...e.runs[r] }; }
function cmpSteps() {
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
  const dh = (epochUTC - Date.now()) / 3600e3;
  if (Math.abs(dh) < 0.75) return "지금";
  const h = Math.round(Math.abs(dh));
  const d = Math.floor(h / 24);
  const s = d >= 1 ? `${d}일 ${h - d * 24}시간` : `${h}시간`;
  return dh > 0 ? `${s} 후` : `${s} 전`;
}

function renderModelBtns() {
  const models = Object.keys(entry().models);
  if (!models.length) {
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
    const cnt = {};
    cmpModels().forEach((m) => runEntry(m).panels.forEach((p) => { cnt[p] = (cnt[p] || 0) + 1; }));
    panels = PANEL_ORDER.filter((p) => cnt[p] >= 2);
  } else {
    const have = runEntry(state.model).panels;
    panels = PANEL_ORDER.filter((p) => have.includes(p)).concat(have.filter((p) => !PANEL_ORDER.includes(p)));
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
makePlayer("stepPlay", () => $("stepNext").click(), () => state.stepIdx >= maxStepIdx(),
           () => { state.stepIdx = 0; renderChart(); });

// ── 관측 탭 ──
const OBS_LABEL = { ta: "기온", feel: "체감온도", si: "일사", ca: "전운량",
                    anom_tmax: "일최고 평년편차", anom_tmin: "일최저 평년편차" };
const OBS_ORDER = ["ta", "feel", "si", "ca"];   // 시간별 변수 순서 (뒤에 일 단위 평년편차)
const ANOM_SCALE = { vmin: -8, vmax: 8, unit: "℃", label: "평년편차",
                     colors: ["#2166ac", "#4393c3", "#92c5de", "#d1e5f0", "#f7f7f7", "#f7f7f7",
                              "#fddbc7", "#f4a582", "#d6604d", "#b2182b"] };
let firstObs = true;
function obsEpoch(ymd, hour) {  // 관측일(KST)+시 → UTC epoch
  return Date.UTC(+ymd.slice(0, 4), +ymd.slice(4, 6) - 1, +ymd.slice(6, 8), hour) - 9 * 3600e3;
}
let obsState = { date: null, v: null, idx: 0, data: null, meta: null };

// 색을 구간으로 끊는다 — 연속 그라데이션은 '이 색이 몇 도인지'를 알 수 없다.
function obsBins(sc) {
  const span = sc.vmax - sc.vmin;
  const step = [0.25, 0.5, 1, 2, 2.5, 5, 10, 20].find((p) => p >= span / 11) || 20;
  const lo = Math.floor(sc.vmin / step) * step;
  const edges = [];
  for (let e = lo; e <= sc.vmax + 1e-9; e += step) edges.push(+e.toFixed(3));
  const colors = edges.slice(0, -1).map((e) => {
    const t = Math.max(0, Math.min(1, ((e + step / 2) - sc.vmin) / span));
    return sc.colors[Math.round(t * (sc.colors.length - 1))];
  });
  return { edges: edges, colors: colors, step: step };
}
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
    obsState.meta = await fetchJSON("obs/stations.json");
    obsState.base = await fetchJSON("basemap.json");
  }
  if (obsState.date === ymd && obsState.data) return;
  obsState.data = await fetchJSON(`obs/${ymd}.json?${Date.now()}`);
  obsState.date = ymd;
}

const isAnom = (v) => v && v.startsWith("anom_");
function obsHours() {
  const vv = obsState.data && obsState.data.vars[obsState.v];
  if (!vv) return [];
  const set = new Set();
  Object.values(vv).forEach((arr) => arr.forEach((x, h) => { if (x != null) set.add(h); }));
  return [...set].sort((a, b) => a - b);
}

function renderObsVarBtns() {
  const present = Object.keys((obsState.data && obsState.data.vars) || {});
  let vars = OBS_ORDER.filter((v) => present.includes(v))
    .concat(present.filter((v) => !OBS_ORDER.includes(v)));
  if (obsState.data && obsState.data.normals && obsState.data.daily) vars = vars.concat(["anom_tmax", "anom_tmin"]);
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
  $("obsSliderRow").hidden = isAnom(obsState.v);
  if (isAnom(obsState.v)) { renderObs(); return; }
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
  const anom = isAnom(obsState.v);
  const bm = obsState.base;
  let sc, valueOf, h = null, sub = "";
  if (anom) {
    const k = obsState.v === "anom_tmax" ? 0 : 1;      // daily [tmax, tmin, n] · normals [tavg, tmax, tmin]
    const dl = obsState.data.daily || {}, nm = obsState.data.normals || {};
    sc = { ...ANOM_SCALE, label: OBS_LABEL[obsState.v] };
    valueOf = (s) => {
      const d = dl[s], n = nm[s];
      // 일최고는 17시까지(18시간), 일최저는 08시까지(9시간) 관측이 있어야 극값이 확정된다
      if (!d || !n || d[k] == null || n[k + 1] == null || d[2] < (k === 0 ? 18 : 9)) return null;
      return +(d[k] - n[k + 1]).toFixed(1);
    };
    const nh = Math.max(0, ...Object.values(dl).map((d) => d[2] || 0));
    $("obsLabel").textContent = `${fmtDate(obsState.date)} ${OBS_LABEL[obsState.v]} — 관측 ${nh}시간 기준 · 평년 = 1991~2020 자체 산출`;
    sub = "일 극값은 정시 관측값 기반(참값보다 조금 안쪽). 관측이 모자란 지점(일최고 18시간·일최저 9시간 미만)과 평년 없는 지점은 비움.";
    if (nh < (k === 0 ? 18 : 9)) sub = `<b style="color:#a11">아직 이 날의 ${k === 0 ? "일최고(17시까지 관측 필요)" : "일최저(08시까지 관측 필요)"}를 확정할 수 없습니다 — 어제 날짜를 선택하세요.</b> ` + sub;
  } else {
    const hours = obsHours();
    if (!hours.length) { $("obsMap").innerHTML = ""; return; }
    $("obsSlider").value = obsState.idx;
    h = hours[obsState.idx];
    sc = obsState.meta.scales[obsState.v];
    const vv = obsState.data.vars[obsState.v];
    valueOf = (s) => { const arr = vv[s]; return arr ? arr[h] : null; };
    $("obsLabel").textContent =
      `${fmtDate(obsState.date)} ${String(h).padStart(2, "0")}시 KST 실황 — ${sc.label} (${relNow(obsEpoch(obsState.date, h))})`;
  }
  const bins = obsBins(sc);
  let pts = "", lbl = "", n = 0;
  obsState.meta.stations.forEach((st) => {
    const v = valueOf(String(st.s));
    const col = obsColor(v, sc);
    if (col == null) return;
    n++;
    pts += `<circle cx="${st.x}" cy="${st.y}" r="${st.L ? 8 : 7}" fill="${col}"`
         + ` stroke="${st.L ? "#000" : "#333"}" stroke-width="${st.L ? 1.4 : 0.7}"`
         + ` data-n="${st.n}" data-v="${v}"/>`;
    if (st.L) {
      const txt = `${st.n} ${anom && v > 0 ? "+" : ""}${v.toFixed(1)}`;
      lbl += `<text x="${st.x + 11}" y="${st.y + 5}" font-size="15" font-weight="bold"`
           + ` paint-order="stroke" stroke="#fff" stroke-width="3.5" fill="#111">${txt}</text>`;
    }
  });
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
    + `<text x="${(i * SW).toFixed(1)}" y="38" text-anchor="middle" font-size="12" fill="#444">${anom && e > 0 ? "+" : ""}${e}</text>`).join("");
  const unitTxt = sc.unit === "℃" ? "℃" : " " + sc.unit;
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
    <p class="note">지점 ${n}곳 — 원 색이 값. 마우스를 올리거나(휴대폰은 짚으면) 지점명과 값이 표시됩니다. ${sub}</p>`;

  bindDotHover("obsSvg", (t) => {
    const v = +t.dataset.v;
    return `<b>${t.dataset.n}</b> ${h == null ? fmtDate(obsState.date) : String(h).padStart(2, "0") + "시"}<br>${sc.label} ${anom && v > 0 ? "+" : ""}${v.toFixed(1)}${unitTxt}`;
  });
}

$("obsSlider").oninput = (ev) => { obsState.idx = +ev.target.value; renderObs(); };
$("obsPrev").onclick = () => { if (obsState.idx > 0) { obsState.idx--; renderObs(); } };
$("obsNext").onclick = () => {
  if (obsState.idx < obsHours().length - 1) { obsState.idx++; renderObs(); }
};
makePlayer("obsPlay", () => $("obsNext").click(), () => obsState.idx >= obsHours().length - 1,
           () => { obsState.idx = 0; renderObs(); }, 600);

// ── 검증 탭: 오차 지도 ──
let vmState = { v: "t2m", w: "d" };
function renderVm() {
  $("vmImg").src = vmState.w === "sm"
    ? `verif/verifmap_sm_${vmState.v}.png`
    : `verif/verifmap_${vmState.v}_${vmState.w}.png`;
}
document.querizeSelectorAllSafe = null;
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
    METEO.data = await fetchJSON(`meteo/${d}.json?${Date.now()}`);
    METEO.date = d;
  }
  renderMeteoCharts();
}

// ── 검증 탭: 일별 검증표 ──
const CITY_ORDER = ["서울", "대전", "대구", "광주", "부산",
                    "인천", "수원", "전주", "강릉", "제주"];
async function renderVerifDaily() {
  const d = $("dateSelV").value;
  const data = await fetchJSON(`verif/daily/${d}.json`);
  for (const [vr, elId, nd, big] of [["t2m", "verifDailyT", 1, 3], ["tcc", "verifDailyC", 0, 40], ["dswrf", "verifDailyS", 0, 200]]) {
    const vd = data[vr];
    if (vr === "dswrf") { $("verifDailySH").hidden = !vd; $(elId).hidden = !vd; }
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
  $("caseList").innerHTML = (MF.cases || []).slice().reverse().map((fn) =>
    `<li><a href="verif/cases/${fn}" target="_blank">${fn.replace(".md", "")}</a></li>`).join("");
}

// ── 갱신 신선도 배지 ──
function renderFresh() {
  const m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/.exec(MF.generated_utc || "");
  const el = $("freshPill");
  if (!m) { el.textContent = "갱신 시각 불명"; return; }
  const t = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
  const min = Math.round((Date.now() - t) / 60e3);
  el.textContent = `갱신 ${min < 60 ? min + "분 전" : relNow(t)}`;
  el.className = "pill " + (min < 100 ? "ok" : min < 200 ? "warn" : "bad");
  el.title = `site-data 발행 ${MF.generated_utc} UTC` + (min >= 200 ? " — 시간별 갱신이 멈춰 있을 수 있습니다" : "");
}

// ── 초기화 ──
(async function init() {
  MF = await fetchJSON("manifest.json?" + Date.now());
  renderFresh();
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
  $("prevModeBtn").onclick = () => {
    METEO.prevMode = { band: "lines", lines: "off", off: "band" }[METEO.prevMode];
    $("prevModeBtn").textContent = "이전 런: " + { band: "띠", lines: "선", off: "끄기" }[METEO.prevMode];
    $("prevModeBtn").classList.toggle("on", METEO.prevMode !== "off");
    renderMeteoCharts();
  };
  $("prevModeBtn").classList.add("on");
  $("stripBtn").onclick = () => { METEO.strips = !METEO.strips; $("stripBtn").classList.toggle("on", METEO.strips); renderMeteoCharts(); };

  const odates = (MF.obs_dates || []).slice().reverse();
  $("dateSelO").innerHTML = odates.map((d) => `<option value="${d}">${fmtDate(d)}</option>`).join("");
  const onObsDate = async () => {
    const ymd = $("dateSelO").value;
    await loadObs(ymd); renderObsVarBtns();
    // 위성 일사 일적산 그림 — 그 날짜 아카이브에 있으면 표시
    const sat = ((MF.dates[ymd] || {}).satsw || []).filter((f) => f.endsWith(".webp") || f.endsWith(".png"));
    $("satBlock").hidden = !sat.length;
    if (sat.length) $("satImg").src = `archive/${ymd}/${sat[sat.length - 1]}?${Date.now()}`;
  };
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
    const loadK = async (d) => {
      if (KMAF.date === d) return;
      KMAF.data = await fetchJSON(`kmafcst/${d}.json?${Date.now()}`);
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
  renderMid();

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
      [ncIdx - 1, ncIdx + 1].forEach((i) => {
        if (i >= 0 && i < ncLeads.length) new Image().src = `nowcast/map_${ncLeads[i]}h.webp`;
      });
    };
    $("ncSlider").max = ncLeads.length - 1;
    $("ncSlider").oninput = (e) => { ncIdx = +e.target.value; renderNc(); };
    $("ncPrev").onclick = () => { if (ncIdx > 0) { ncIdx--; renderNc(); } };
    $("ncNext").onclick = () => { if (ncIdx < ncLeads.length - 1) { ncIdx++; renderNc(); } };
    makePlayer("ncPlay", () => $("ncNext").click(), () => ncIdx >= ncLeads.length - 1, () => { ncIdx = 0; renderNc(); }, 900);
    renderNc();
    if (nc.has_now) $("ncNow").src = `nowcast/map_0h.webp?${Date.now()}`;
    else $("ncNow").closest(".imgwrap").hidden = true;
    $("ncCities").src = `nowcast/cities.webp?${Date.now()}`;
    ["ncVerifyTitle", "ncVerifyNote", "ncVerify"].forEach((id) => { $(id).hidden = !nc.has_verify; });
    if (nc.has_verify) $("ncVerify").src = `nowcast/verify.webp?${Date.now()}`;
    const cutKey = (() => {
      const d = new Date(Date.now() + 9 * 3600e3 - 7 * 864e5);
      const p2 = (n) => String(n).padStart(2, "0");
      return `${d.getUTCFullYear()}${p2(d.getUTCMonth() + 1)}${p2(d.getUTCDate())}00`;
    })();
    const past = (nc.past || []).filter((t) => t >= cutKey).reverse();
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
