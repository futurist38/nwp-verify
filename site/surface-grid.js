/* Surface-only maps. Native values stay unchanged; interpolation is display-only. */
(function (host) {
  'use strict';
  const PANELS = ['t2m', 'tcc', 'cloud3', 'dswrf', 'tp'];
  const RAIN = [0.1, 0.5, 1, 2, 5, 10, 20, 30, 50, 80];
  const RAIN_COLORS = ['#d4ecff', '#a6d4ff', '#6fb6ff', '#3d8ef0', '#1f5fd0', '#7a3fd0', '#c02fb0', '#e0207a', '#ff4040', '#7a0000'];
  const SOLAR_COLORS = ['#f1f4f6', '#b7dce0', '#5db8c0', '#e9df88', '#f8b74e', '#ee7736', '#c5352d'];
  // Demand-forecasting cities; separate labels around the capital region.
  const CITY_MARKERS = [
    ['서울', 126.966, 37.571, 6, -16],
    ['수원', 126.983, 37.25746, -6, 18],
    ['인천', 126.625, 37.478, -6, 0],
    ['대전', 127.372, 36.372, 6, -2],
    ['광주', 126.891, 35.173, -6, 10],
    ['부산', 129.032, 35.105, 6, 11],
    ['대구', 128.653, 35.878, -6, 9],
    ['원주', 127.94659, 37.33749, 6, -2]
  ];
  const CACHE_LIMIT = 18;
  const cache = new Map(), pending = new Map(), observers = new Set();
  let assetsPromise;

  function composite(l, m, h) {
    if (![l, m, h].every(Number.isFinite)) return [190, 190, 190];
    const a = [l, m, h].map(v => Math.max(0, Math.min(1, v / 100)));
    const sum = a[0] + a[1] + a[2], maximum = Math.max(...a);
    if (!sum) return [255, 255, 255];
    const colors = [[.88, .48, .06], [.84, .10, .67], [0, .57, .76]], triple = [.08, .66, .20];
    const r = Math.min(...a) / maximum, w = r * r * (3 - 2 * r);
    return [0, 1, 2].map(c => Math.round(255 * (1 - .96 * maximum * (1 -
      ((1 - w) * a.reduce((s, v, i) => s + v / sum * colors[i][c], 0) + w * triple[c])))));
  }

  function bilinear(values, nx, ny, x, y, offset = 0) {
    x = Math.max(0, Math.min(nx - 1, x)); y = Math.max(0, Math.min(ny - 1, y));
    const i = Math.floor(x), j = Math.floor(y), u = x - i, v = y - j;
    const ii = Math.min(i + 1, nx - 1), jj = Math.min(j + 1, ny - 1);
    const points = [[j * nx + i, (1 - u) * (1 - v)], [j * nx + ii, u * (1 - v)],
      [jj * nx + i, (1 - u) * v], [jj * nx + ii, u * v]];
    let result = 0;
    for (const [k, weight] of points) {
      if (weight === 0) continue;
      if (!Number.isFinite(values[offset + k])) return NaN;
      result += values[offset + k] * weight;
    }
    return result;
  }

  function decode(raw, meta) {
    if (raw.byteLength !== meta.nx * meta.ny * meta.channels * 4) throw new Error('격자 크기 불일치');
    const view = new DataView(raw), values = new Float32Array(raw.byteLength / 4);
    for (let i = 0; i < values.length; i++) values[i] = view.getFloat32(i * 4, true);
    return values;
  }

  function descriptor(entry, panel, step) { return entry?.grids?.[panel]?.[String(step)] || null; }

  async function readFrame(meta) {
    if (!/^grids\/\d{8}\/(ecmwf|gfs|kim)_\d{10}\/f\d{3}_(t2m|tcc|cloud3|dswrf|tp)_[0-9a-f]{12}\.f32\.gz$/.test(meta.path)) {
      throw new Error('격자 경로 오류');
    }
    if (cache.has(meta.path)) {
      const values = cache.get(meta.path); cache.delete(meta.path); cache.set(meta.path, values); return values;
    }
    if (pending.has(meta.path)) return pending.get(meta.path);
    const promise = (async () => {
      const response = await fetch(meta.path);
      if (!response.ok) {
        const error = new Error(`자료 수신 실패 (${response.status})`);
        error.expired = response.status === 404; throw error;
      }
      let raw = await response.arrayBuffer();
      const magic = new Uint8Array(raw, 0, Math.min(2, raw.byteLength));
      if (magic[0] === 31 && magic[1] === 139) {
        if (typeof DecompressionStream === 'undefined') throw new Error('최신 브라우저에서 열어주세요');
        raw = await new Response(new Blob([raw]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
      }
      const values = decode(raw, meta);
      cache.set(meta.path, values);
      while (cache.size > CACHE_LIMIT) cache.delete(cache.keys().next().value);
      return values;
    })();
    pending.set(meta.path, promise);
    try { return await promise; } finally { pending.delete(meta.path); }
  }

  async function assets() {
    if (!assetsPromise) assetsPromise = (async () => {
      if (!host.d3?.contours) await new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = 'd3-7.9.0.min.js'; script.onload = resolve;
        script.onerror = () => { script.remove(); reject(new Error('지도 구성요소 수신 실패')); };
        document.head.appendChild(script);
      });
      const response = await fetch('surface-coast.json?v=1');
      if (!response.ok) throw new Error('해안선 자료 수신 실패');
      return {d3: host.d3, geography: await response.json()};
    })().catch(error => { assetsPromise = null; throw error; });
    return assetsPromise;
  }

  function settings(panel, d3) {
    const solar = d3.scaleLinear().domain(SOLAR_COLORS.map((_, i) => i * 1000 / 6)).range(SOLAR_COLORS).clamp(true);
    return {
      t2m: {title: '2m 기온', unit: '°C', levels: d3.range(-15, 40, 3), ticks: [-15, -6, 3, 12, 21, 30, 39],
        color: v => d3.interpolateRdYlBu(1 - Math.max(0, Math.min(1, (v + 15) / 53))), base: d3.interpolateRdYlBu(1)},
      tcc: {title: '전운량', unit: '%', levels: d3.range(0, 101, 10), ticks: [0, 20, 40, 60, 80, 100],
        color: v => d3.interpolateGreys(1 - Math.max(0, Math.min(1, v / 100))), base: '#000'},
      tp: {title: '강수량', unit: 'mm', levels: RAIN, ticks: RAIN,
        color: v => RAIN_COLORS[Math.max(0, d3.bisectRight(RAIN, v) - 1)], base: '#fff'},
      dswrf: {title: '하향 단파복사 · 3시간 평균', unit: 'W/m²', levels: d3.range(0, 1001, 10), ticks: [0, 200, 400, 600, 800, 1000],
        color: v => v >= 1000 ? '#8f1d25' : solar(v), base: solar(0)},
      cloud3: {title: '층별 운량 합성', unit: '%'}
    }[panel];
  }

  function projection(meta, width, height, d3) {
    const p = d3.geoMercator().scale(1).translate([0, 0]);
    const a = p([meta.lon0, meta.lat0]), b = p([meta.lon1, meta.lat1]);
    const scale = Math.min((width - 28) / (b[0] - a[0]), (height - 28) / (b[1] - a[1]));
    return p.scale(scale).translate([width / 2 - scale * (a[0] + b[0]) / 2, height / 2 - scale * (a[1] + b[1]) / 2]);
  }

  function paint(canvas, values, meta, panel, d3, geography, width) {
    const start = performance.now(), height = Math.round(width * 1.04), ratio = Math.min(2, host.devicePixelRatio || 1);
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio); canvas.style.height = height + 'px';
    const ctx = canvas.getContext('2d'); ctx.scale(ratio, ratio);
    const p = projection(meta, width, height, d3), nw = p([meta.lon0, meta.lat0]), se = p([meta.lon1, meta.lat1]);
    const dx = (meta.lon1 - meta.lon0) / (meta.nx - 1), dy = (meta.lat0 - meta.lat1) / (meta.ny - 1);
    const conf = settings(panel, d3), size = meta.nx * meta.ny;
    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, width, height);
    ctx.save(); ctx.beginPath(); ctx.rect(nw[0], nw[1], se[0] - nw[0], se[1] - nw[1]); ctx.clip();
    if (panel === 'cloud3') {
      const off = document.createElement('canvas'); off.width = Math.ceil(se[0] - nw[0]); off.height = Math.ceil(se[1] - nw[1]);
      const ox = off.getContext('2d'), image = ox.createImageData(off.width, off.height);
      const xs = Array.from({length: off.width}, (_, i) => (p.invert([nw[0] + i + .5, nw[1]])[0] - meta.lon0) / dx);
      const ys = Array.from({length: off.height}, (_, j) => (meta.lat0 - p.invert([nw[0], nw[1] + j + .5])[1]) / dy);
      for (let j = 0; j < off.height; j++) for (let i = 0; i < off.width; i++) {
        const color = composite(...[0, 1, 2].map(c => bilinear(values, meta.nx, meta.ny, xs[i], ys[j], c * size)));
        const k = (j * off.width + i) * 4; image.data.set([...color, 255], k);
      }
      ox.putImageData(image, 0, 0); ctx.drawImage(off, nw[0], nw[1]);
    } else {
      ctx.fillStyle = conf.base; ctx.fillRect(nw[0], nw[1], se[0] - nw[0], se[1] - nw[1]);
      const contours = d3.contours().size([meta.nx, meta.ny]).smooth(true).thresholds(conf.levels)(values);
      for (const contour of contours) {
        ctx.beginPath();
        for (const polygon of contour.coordinates) for (const ring of polygon) {
          ring.forEach((point, i) => { const xy = p([meta.lon0 + (point[0] - .5) * dx, meta.lat0 - (point[1] - .5) * dy]);
            if (i) ctx.lineTo(...xy); else ctx.moveTo(...xy); }); ctx.closePath();
        }
        ctx.fillStyle = conf.color(contour.value); ctx.fill('evenodd');
      }
      // Missing values remain visibly missing; never paint them as clear sky/night.
      ctx.fillStyle = '#bebebe';
      for (let k = 0; k < size; k++) if (!Number.isFinite(values[k])) {
        const i = k % meta.nx, j = Math.floor(k / meta.nx);
        const a = p([meta.lon0 + (i - .5) * dx, meta.lat0 - (j - .5) * dy]);
        const b = p([meta.lon0 + (i + .5) * dx, meta.lat0 - (j + .5) * dy]); ctx.fillRect(a[0], a[1], b[0] - a[0], b[1] - a[1]);
      }
    }
    const line = panel === 'tcc' ? '#e5c827' : '#343434';
    const path = d3.geoPath(p, ctx); ctx.strokeStyle = line; ctx.globalAlpha = .85;
    for (const feature of geography.features) { ctx.beginPath(); path(feature); ctx.lineWidth = feature.properties?.kind === 'coastline' ? .85 : .6; ctx.stroke(); }
    ctx.globalAlpha = 1; ctx.fillStyle = line; ctx.font = '12px sans-serif';
    ctx.strokeStyle = panel === 'tcc' ? 'rgba(0,0,0,.85)' : 'rgba(255,255,255,.9)';
    ctx.lineWidth = 2.5; ctx.lineJoin = 'round'; ctx.textBaseline = 'middle';
    for (const [name, lon, lat, offsetX, offsetY] of CITY_MARKERS) {
      const xy = p([lon, lat]); ctx.beginPath(); ctx.arc(...xy, 2, 0, Math.PI * 2); ctx.stroke(); ctx.fill();
      ctx.textAlign = offsetX < 0 ? 'right' : 'left';
      ctx.strokeText(name, xy[0] + offsetX, xy[1] + offsetY);
      ctx.fillText(name, xy[0] + offsetX, xy[1] + offsetY);
    }
    ctx.restore(); ctx.strokeStyle = '#ccc'; ctx.lineWidth = 1; ctx.strokeRect(nw[0], nw[1], se[0] - nw[0], se[1] - nw[1]);
    return {projection: p, width, height, milliseconds: performance.now() - start};
  }

  function drawLegend(node, panel, meta, d3) {
    node.replaceChildren(); const conf = settings(panel, d3);
    const title = document.createElement('div'); title.className = 'sg-legend-title';
    title.textContent = panel === 'cloud3' ? '층별 운량 · 색 농도는 최대 층 운량' :
      `${conf.title}${panel === 'tp' ? ' · 직전 ' + meta.window_h + '시간 누적' : ''} (${conf.unit})`;
    node.appendChild(title);
    if (panel === 'cloud3') {
      const bars = document.createElement('div'); bars.className = 'sg-cloud-bars';
      ['하층', '중층', '상층'].forEach((label, channel) => {
        const bar = document.createElement('div'), ramp = document.createElement('i');
        const values = [0, 0, 0]; values[channel] = 100;
        ramp.style.background = `linear-gradient(to right,#fff,rgb(${composite(...values).join(',')}))`;
        bar.append(label + ' 0', ramp, '100%'); bars.appendChild(bar);
      });
      node.appendChild(bars);
      const row = document.createElement('div'); row.className = 'sg-cloud-legend';
      const groups = [['하층', [100, 0, 0]], ['중층', [0, 100, 0]], ['상층', [0, 0, 100]],
        ['하+중', [100, 100, 0]], ['하+상', [100, 0, 100]], ['중+상', [0, 100, 100]], ['3층 겹침', [100, 100, 100]]];
      for (const [label, value] of groups) {
        const item = document.createElement('span'), swatch = document.createElement('i');
        swatch.style.background = `rgb(${composite(...value).join(',')})`; item.append(swatch, label); row.appendChild(item);
      }
      node.appendChild(row); const note = document.createElement('div'); note.className = 'sg-note';
      note.textContent = '겹침색은 각 층 100% 예시 · 회색: 결측'; node.appendChild(note); return;
    }
    const width = Math.max(260, Math.round(node.clientWidth || 500)), svg = d3.select(node).append('svg').attr('viewBox', `0 0 ${width} 43`);
    const n = panel === 'tp' ? RAIN.length : conf.levels.length - 1;
    const scale = d3.scaleLinear().domain(panel === 'tp' ? [0, n] : [conf.levels[0], conf.levels.at(-1)]).range([18, width - 18]);
    for (let i = 0; i < n; i++) {
      const a = scale(panel === 'tp' ? i : conf.levels[i]), b = scale(panel === 'tp' ? i + 1 : conf.levels[i + 1]);
      svg.append('rect').attr('x', a).attr('y', 2).attr('width', b - a + .1).attr('height', 12).attr('fill', conf.color(conf.levels[i]));
    }
    const ticks = panel === 'tp' && width < 440 ? [.1, 1, 5, 20, 80] : conf.ticks;
    ticks.forEach((value, i) => svg.append('text').attr('x', scale(panel === 'tp' ? RAIN.indexOf(value) : value)).attr('y', 32)
      .attr('text-anchor', i === 0 ? 'start' : i === ticks.length - 1 ? 'end' : 'middle').text(value));
  }

  function clear() { for (const observer of observers) observer.disconnect(); observers.clear(); }

  async function render(node, meta, panel, label) {
    node.textContent = '지도 자료를 불러오는 중…'; node.classList.add('surface-grid'); node.dataset.ready = 'loading';
    try {
      const [values, {d3, geography}] = await Promise.all([readFrame(meta), assets()]);
      if (!node.isConnected) return;
      node.replaceChildren();
      const canvas = document.createElement('canvas'), legend = document.createElement('div'), detail = document.createElement('div');
      canvas.setAttribute('role', 'img'); canvas.setAttribute('aria-label', label + ' · 격자자료 채색 지도');
      legend.className = 'sg-legend'; detail.className = 'sg-detail';
      detail.textContent = `${meta.nx} × ${meta.ny} 격자 · 부드러운 채색 · 회색: 결측`;
      node.append(canvas, legend, detail);
      let drawn, lastWidth = 0;
      function redraw() {
        if (!node.isConnected) return;
        const width = Math.round(node.clientWidth || 640);
        if (width === lastWidth) return;
        lastWidth = width; drawn = paint(canvas, values, meta, panel, d3, geography, width);
        drawLegend(legend, panel, meta, d3); node.dataset.ready = 'true';
      }
      const observer = new ResizeObserver(redraw); observer.observe(node); observers.add(observer); redraw();
      function showValue(event) {
        if (!drawn) return;
        const box = canvas.getBoundingClientRect();
        const [lon, lat] = drawn.projection.invert([(event.clientX - box.left) * drawn.width / box.width,
          (event.clientY - box.top) * drawn.height / box.height]);
        if (lon < meta.lon0 || lon > meta.lon1 || lat > meta.lat0 || lat < meta.lat1) return;
        const i = Math.round((lon - meta.lon0) / (meta.lon1 - meta.lon0) * (meta.nx - 1));
        const j = Math.round((meta.lat0 - lat) / (meta.lat0 - meta.lat1) * (meta.ny - 1)), k = j * meta.nx + i;
        const format = v => Number.isFinite(v) ? v.toFixed(panel === 'tp' ? 2 : 1) : '결측';
        const value = panel === 'cloud3' ? ['하층', '중층', '상층'].map((name, c) => `${name} ${format(values[k + c * meta.nx * meta.ny])}%`).join(' · ')
          : `${format(values[k])} ${settings(panel, d3).unit}`;
        const gridLon = meta.lon0 + i * (meta.lon1 - meta.lon0) / (meta.nx - 1);
        const gridLat = meta.lat0 - j * (meta.lat0 - meta.lat1) / (meta.ny - 1);
        detail.textContent = `격자값 ${gridLon.toFixed(2)}°E, ${gridLat.toFixed(2)}°N · ${value}`;
      }
      canvas.addEventListener('pointermove', event => { if (event.pointerType !== 'touch') showValue(event); });
      canvas.addEventListener('click', showValue);
    } catch (error) {
      if (!node.isConnected) return;
      node.dataset.ready = 'error'; node.textContent = '지도를 표시하지 못했습니다. ';
      const button = document.createElement('button'); button.type = 'button';
      button.textContent = error.expired ? '최신 자료 불러오기' : '다시 불러오기';
      button.onclick = () => error.expired ? host.location.reload() : render(node, meta, panel, label); node.appendChild(button);
      console.warn('[surface-grid]', error.message);
    }
  }

  const api = {PANELS, descriptor, render, clear, preload: meta => { if (meta) readFrame(meta).catch(() => {}); },
    composite, bilinear, decode, paint, settings, projection};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else host.SurfaceGrid = api;
})(typeof window === 'undefined' ? globalThis : window);

