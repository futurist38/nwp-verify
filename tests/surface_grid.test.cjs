const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const grid = require('../site/surface-grid.js');

test('float32 decode preserves zero and missing values and rejects truncation', () => {
  const raw = new ArrayBuffer(16), view = new DataView(raw);
  [-7.25, 0, NaN, 100].forEach((v, i) => view.setFloat32(i * 4, v, true));
  const values = grid.decode(raw, {nx: 2, ny: 2, channels: 1});
  assert.deepEqual([...values], [-7.25, 0, NaN, 100]);
  assert.throws(() => grid.decode(raw.slice(1), {nx: 2, ny: 2, channels: 1}));
});

test('display interpolation does not bridge missing values or modify native samples', () => {
  const values = new Float32Array([0, 10, 20, 30]);
  assert.equal(grid.bilinear(values, 2, 2, .5, .5), 15);
  assert.deepEqual([...values], [0, 10, 20, 30]);
  values[3] = NaN;
  assert.ok(Number.isNaN(grid.bilinear(values, 2, 2, .5, .5)));
  assert.equal(grid.bilinear(values, 2, 2, 0, 0), 0);
  assert.deepEqual(grid.composite(0, 0, 0), [255, 255, 255]);
  assert.deepEqual(grid.composite(NaN, 0, 0), [190, 190, 190]);
  const triple = grid.composite(100, 100, 100);
  assert.ok(triple[1] > triple[0] && triple[1] > triple[2]);
});

test('chart integration uses grids for surface fields and images for upper charts', () => {
  const source = fs.readFileSync(require.resolve('../site/app.js'), 'utf8');
  const part = source.slice(source.indexOf('function surfaceMapHTML('), source.indexOf('function mountSurfaceMaps('));
  const context = vm.createContext({state: {panel: 't2m'}, PANEL_LABEL: {t2m: '기온', p500: '500'},
    imgPathFor: (model, step) => `${model}_${step}.webp`});
  vm.runInContext(part, context);
  assert.match(vm.runInContext('surfaceMapHTML("GFS", 3, {grids:{t2m:{"3":{path:"grid"}}}})', context), /data-grid-model="GFS"/);
  assert.doesNotMatch(vm.runInContext('surfaceMapHTML("GFS", 3, {grids:{t2m:{"3":{path:"grid"}}}})', context), /<img/);
  vm.runInContext('state.panel = "p500"', context);
  assert.match(vm.runInContext('surfaceMapHTML("GFS", 6, {})', context), /<img src="GFS_6.webp"/);
  assert.equal(grid.descriptor({grids: {t2m: {'3': {path: 'a'}}}}, 't2m', 6), null);
});
