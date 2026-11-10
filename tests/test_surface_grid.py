import datetime as dt
import gzip
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import xarray as xr

from surface_grid import export_surface_grid, publish_surface_grids, merge_surface_manifest, read_index


def data(run='2026111000', steps=(0, 3, 6), missing=False):
    values = np.arange(len(steps) * 6, dtype=np.float32).reshape(len(steps), 2, 3)
    if missing:
        values[0, 0, 1] = np.nan
    da = xr.DataArray(values, dims=('step', 'latitude', 'longitude'),
                      coords={'step': np.array(steps, dtype='timedelta64[h]'),
                              'latitude': [31., 32.], 'longitude': [121., 120.5, 120.]})
    return {'run': dt.datetime.strptime(run, '%Y%m%d%H'), 't2m': da, 'tcc': da,
            'lcc': da, 'mcc': da, 'hcc': da,
            'dswrf': da.assign_coords(win_h=('step', [0 if s == 0 else 6 if s == 6 else 3 for s in steps])),
            'tp': da.assign_coords(win_h=('step', [0 if s == 0 else 3 for s in steps]))}


class SurfaceGridTest(unittest.TestCase):
    def test_binary_native_resolution_orientation_missing_and_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = export_surface_grid('GFS', data(missing=True), tmp)
            index = read_index(path)
            frame = index['panels']['t2m']['0']
            decoded = np.frombuffer(gzip.decompress((path.parent / frame['file']).read_bytes()), dtype='<f4').reshape(2, 3)
            np.testing.assert_allclose(decoded, [[5, 4, 3], [2, np.nan, 0]], equal_nan=True)
            self.assertEqual((frame['nx'], frame['ny'], frame['lat0'], frame['lat1'], frame['lon0'], frame['lon1']), (3, 2, 32, 31, 120, 121))
            self.assertEqual(list(index['panels']['dswrf']), ['3'])
            self.assertNotIn('0', index['panels']['tp'])
            self.assertEqual(index['panels']['cloud3']['0']['channels'], 3)
            # Export the same data twice: immutable URLs and deterministic compressed bytes.
            original = path.read_bytes()
            export_surface_grid('GFS', data(missing=True), tmp)
            self.assertEqual(original, path.read_bytes())

    def test_latest_run_merge_resists_stale_job_and_partial_same_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); site = root / 'site'; output = root / 'output'
            first = export_surface_grid('KIM', data('2026111012', (0, 3)), output / '20261110')
            publish_surface_grids(site, output)
            saved = site / 'grids/20261110/kim_2026111012/index.json'
            before = saved.read_bytes()
            # A stale runner received an older run and cannot roll back the current one.
            stale = root / 'stale'
            export_surface_grid('KIM', data('2026111000', (0, 3)), stale / '20261110')
            publish_surface_grids(site, stale)
            self.assertEqual(saved.read_bytes(), before)
            export_surface_grid('KIM', data('2026111012', (6,)), stale / '20261110')
            publish_surface_grids(site, stale)
            merged = json.loads(saved.read_text())
            self.assertEqual(sorted(merged['panels']['t2m']), ['0', '3', '6'])
            self.assertEqual(len(list((site / 'grids').glob('*/*/index.json'))), 1)
            # An incomplete package is never published.
            broken = read_index(first)['panels']['t2m']['0']['file']
            (first.parent / broken).unlink()
            self.assertIsNone(read_index(first))

    def test_manifest_uses_grids_and_keeps_upper_images_and_other_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); site = root / 'site'; output = root / 'output'
            export_surface_grid('GFS', data(), output / '20261110')
            publish_surface_grids(site, output)
            upper = {'steps': [6, 12], 'panels': ['p500', 'sfc'], 'psteps': {'p500': [6], 'sfc': [12]}}
            manifest = {'dates': {'20261109': {'models': {
                'GFS': {'latest': '2026110918', 'runs': {'2026110918': {**upper, 'panels': ['p500', 'sfc', 't2m'],
                    'psteps': {**upper['psteps'], 't2m': [6, 12]}}}},
                'ECMWF': {'latest': '2026110912', 'runs': {'2026110912': {'steps': [3], 'panels': ['t2m'], 'psteps': {'t2m': [3]}}}}}}}}
            merge_surface_manifest(manifest, site)
            self.assertEqual(manifest['dates']['20261109']['models']['GFS']['runs']['2026110918'], upper)
            self.assertIn('ECMWF', manifest['dates']['20261109']['models'])
            grids = manifest['dates']['20261110']['models']['GFS']['runs']['2026111000']['grids']
            self.assertTrue((site / grids['t2m']['3']['path']).is_file())
            self.assertEqual(grids['tp']['3']['window_h'], 3)


if __name__ == '__main__':
    unittest.main()
