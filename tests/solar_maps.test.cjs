const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Execute the production chart-tab functions with a small DOM; no duplicate time/selection logic.
function app(models, model = '모델비교') {
  const source = fs.readFileSync(path.join(__dirname, '../site/app.js'), 'utf8');
  const elements = new Map();
  const $ = id => {
    if (!elements.has(id)) elements.set(id, {innerHTML: '', textContent: '', value: '',
      hidden: false, closest() { return this; }, querySelectorAll() { return []; }});
    return elements.get(id);
  };
  const context = vm.createContext({$, Image: class {}, document: {querySelectorAll: () => []},
    MF: {dates: {'20261022': {models}}},
    state: {date: '20261022', model, panel: 'dswrf', stepIdx: 0, runs: {}},
    IMG: () => '', PANEL_LABEL: {dswrf: '일사량', t2m: '기온'},
    PANEL_ORDER: ['t2m', 'dswrf'], UPPER_ORDER: []});
  const start = source.indexOf('function entry()');
  const end = source.indexOf('$("stepSlider").oninput');
  assert.ok(start > 0 && end > start);
  vm.runInContext(source.slice(start, end), context);
  return {context, $, run: code => vm.runInContext(code, context)};
}
const modelEntry = (run, solar, extra = {}) => ({latest: run, runs: {[run]: {
  steps: [0, 3, 6, 9, 120, 132], panels: ['t2m', 'dswrf'], psteps: {dswrf: solar}, ...extra}}});

test('different model runs compare the same three-hour averaging interval', () => {
  const {run, $} = app({ECMWF: modelEntry('2026102200', [3, 6, 120]),
    GFS: modelEntry('2026102118', [3, 9, 12, 120]), KIM: modelEntry('2026102200', [3, 6])});
  assert.equal(run('JSON.stringify(cmpSteps())'), JSON.stringify([
    Date.parse('2026-10-22T03:00:00Z'), Date.parse('2026-10-22T06:00:00Z')]));
  run('renderChart()');
  assert.match($('stepLabel').textContent, /10-22 09시–10-22 12시 KST · 3시간 평균/);
  assert.match($('chartStack').innerHTML, /ecmwf_2026102200_f003_dswrf.webp/);
  assert.match($('chartStack').innerHTML, /gfs_2026102118_f009_dswrf.webp/);
  assert.match($('chartStack').innerHTML, /kim_2026102200_f003_dswrf.webp/);
});

test('solar steps never fall back to another panel and exclude f000 and beyond five days', () => {
  const {run} = app({ECMWF: modelEntry('2026102200', [0, 1, 3, 120, 123, 132])}, 'ECMWF');
  assert.equal(run('JSON.stringify(panelSteps(runEntry("ECMWF")))'), '[3,120]');
  assert.equal(run('JSON.stringify(panelSteps({steps:[0,3,6]}))'), '[]');
  assert.equal(run('JSON.stringify(panelSteps({steps:[0,3,6],psteps:{dswrf:[]}}))'), '[]');
});

test('missing overlap clears the previous image instead of showing a stale variable', () => {
  const {run, $} = app({ECMWF: modelEntry('2026102200', [3]), GFS: modelEntry('2026102200', [6])});
  $('chartStack').innerHTML = '<img src="old-temperature.webp">';
  run('renderChart()');
  assert.equal($('chartStack').innerHTML, '');
  assert.equal($('stepLabel').textContent, '공통 유효시각 없음');
});

test('single-model empty data clears the image and averaging labels cross KST midnight', () => {
  const {run, $} = app({ECMWF: modelEntry('2026102200', [])}, 'ECMWF');
  $('chartStack').innerHTML = 'old';
  run('renderChart()');
  assert.equal($('chartStack').innerHTML, '');
  assert.equal(run('solarPeriodLabel(Date.parse("2026-10-22T15:00:00Z"))'),
    '10-22 21시–10-23 00시 KST · 3시간 평균');
});

test('solar button is available and its note is hidden again for temperature', () => {
  const {run, $} = app({ECMWF: modelEntry('2026102200', [3])}, 'ECMWF');
  run('renderPanelBtns()');
  assert.match($('panelBtns').innerHTML, /data-p="dswrf".*일사량/);
  assert.equal($('solarNote').hidden, false);
  // This test is about note state, so skip the unrelated temperature image renderer.
  run('state.panel = "t2m"; renderChart = () => {}; renderPanelBtns()');
  assert.equal($('solarNote').hidden, true);
});
