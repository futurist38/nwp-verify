"""Wonju must be its own real station/grid, never a nearby-city fallback."""
import csv
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from config import CITIES, CITY_OBS_STN
import forecast_compare as fc
import kma_asos
from kma_midfcst import REGS
from kma_vilage import latlon_to_grid
import plot_kmafcst as short


class WonjuPipelineTests(unittest.TestCase):
    def test_station_and_model_coordinates_match_committed_station_catalog(self):
        with open(Path(__file__).resolve().parents[1] / 'verification/obs/stations.csv', encoding='utf-8-sig') as f:
            station = next(r for r in csv.DictReader(f) if r['name'] == '원주')
        self.assertEqual(CITY_OBS_STN['원주'], int(station['STN']))
        city = next(c for c in CITIES if c[0] == '원주')
        self.assertEqual(city[1:3], (float(station['lat']), float(station['lon'])))
        self.assertIn(114, kma_asos.default_stations())
        self.assertIn(114, kma_asos.all_stations())
        self.assertEqual(CITY_OBS_STN['강릉'], 105)
        self.assertEqual(short.CITY_GRID['원주'], latlon_to_grid(*city[1:3]))
        self.assertEqual(REGS['원주'], '11D10401')
        self.assertEqual(fc.CITY_REGIONS['원주'], '11D10000')
        self.assertNotEqual(fc.CITY_REGIONS['원주'], fc.CITY_REGIONS['강릉'])

    def test_existing_issue_gets_missing_city_from_its_own_grid_and_is_cached(self):
        issue, valid = '2026102605', '2026102612'
        existing = {'강릉': {valid: 16}, **{'강릉#'+c: {} for c in short.EXTRA_CATS}}
        response = {'TMP': {valid: 12}, **{c: {} for c in short.EXTRA_CATS}}
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / '20261026.json'
            p.write_text(json.dumps({issue: existing}), encoding='utf-8')
            with patch.object(short, 'CACHE_DIR', tmp), patch.object(short, 'CITY_GRID', {'강릉': (92, 131), '원주': (77, 122)}), patch.object(short, 'fetch', return_value=response) as fetch:
                got = short.load_fcst_cached(dt.date(2026, 10, 26), [issue], 'test-only')
                self.assertEqual(got[issue]['강릉'], existing['강릉'])
                self.assertEqual(got[issue]['원주'], {valid: 12})
                self.assertEqual(fetch.call_args.args[:3], (77, 122, issue))
                short.load_fcst_cached(dt.date(2026, 10, 26), [issue], 'test-only')
                self.assertEqual(fetch.call_count, 1)

    def test_failed_collection_does_not_copy_another_city(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(short, 'CACHE_DIR', tmp), patch.object(short, 'CITY_GRID', {'원주': (77, 122)}), patch.object(short, 'fetch', side_effect=RuntimeError('unavailable')):
            got = short.load_fcst_cached(dt.date(2026, 10, 26), ['2026102605'], 'test-only')
            self.assertEqual(got, {})

    def test_medium_new_issue_preserves_prior_city_gate_when_wonju_is_unavailable(self):
        import kma_midfcst as mid
        issue, day = '2026102606', '20261030'
        cities = {c: {day: {'min': 10, 'max': 20}} for c in REGS if c != '원주'}
        self.assertEqual(len(cities), 10)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mid, 'CACHE_DIR', tmp), patch.object(mid, 'collect', return_value={issue: cities}), patch('sys.argv', ['kma_midfcst.py']):
                mid.main()
            saved = json.loads((Path(tmp) / (issue + '.json')).read_text())
            self.assertEqual(saved, cities)
            self.assertNotIn('원주', saved)
        # Wonju cannot stand in for one of the pre-existing required cities.
        cities.pop('서울')
        cities['원주'] = {day: {'min': 8, 'max': 18}}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mid, 'CACHE_DIR', tmp), patch.object(mid, 'collect', return_value={issue: cities}), patch('sys.argv', ['kma_midfcst.py']):
                mid.main()
            self.assertFalse((Path(tmp) / (issue + '.json')).exists())

    def test_medium_existing_issue_adds_only_actual_new_city_within_requested_range(self):
        import kma_midfcst as mid
        issue, older, day = '2026102606', '2026100106', '20261030'
        existing = {'강릉': {day: {'min': 10, 'max': 20}}}
        received = {issue: {'강릉': {day: {'min': 99, 'max': 99}},
                            '원주': {day: {'min': 8, 'max': 18}}}}
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / (issue + '.json')
            past = Path(tmp) / (older + '.json')
            for path in (p, past):
                path.write_text(json.dumps(existing), encoding='utf-8')
            original_past = past.read_bytes()
            with patch.object(mid, 'CACHE_DIR', tmp), patch.object(mid, 'collect', return_value=received) as collect, patch('sys.argv', ['kma_midfcst.py', '--days', '3']):
                mid.main()
                collect.assert_called_once_with(3)
                saved = json.loads(p.read_text())
                self.assertEqual(saved['강릉'], existing['강릉'])
                self.assertEqual(saved['원주'][day]['min'], 8)
                self.assertEqual(past.read_bytes(), original_past)
                # A subsequent response without Wonju must not remove the saved city.
                received[issue].pop('원주')
                mid.main()
                self.assertEqual(json.loads(p.read_text()), saved)

    def test_site_export_keeps_real_wonju_observations_but_missing_forecasts_null(self):
        import build_site
        issue, valid = '2026102605', '2026102612'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'kmafcst').mkdir()
            (root / 'obs').mkdir()
            raw = {issue: {'강릉': {valid: 16}}}
            (root / 'kmafcst/20261026.json').write_text(json.dumps(raw), encoding='utf-8')
            (root / 'obs/2026-10.csv').write_text('TM,STN,TA,CA_TOT\n2026-10-26 12:00:00,114,12.3,\n2026-10-26 12:00:00,105,16.1,3\n', encoding='utf-8')
            with patch.object(build_site, 'VERIF_DIR', str(root)):
                build_site.export_kmafcst(str(root / 'site'))
                output = json.loads((root / 'site/kmafcst/20261026.json').read_text())
                index = int((dt.datetime.strptime(valid, '%Y%m%d%H') - dt.datetime.strptime(output['t0'], '%Y%m%d%H')).total_seconds() / 3600)
                self.assertIn('원주', output['cities'])
                self.assertEqual(output['obs']['원주'][index], 12.3)
                self.assertEqual(output['obs']['강릉'][index], 16.1)
                self.assertIsNone(output['obs_ca']['원주'][index])
                self.assertTrue(all(v is None for v in output['fcst'][issue]['원주']))
                raw[issue]['원주'] = {valid: 13}
                (root / 'kmafcst/20261026.json').write_text(json.dumps(raw), encoding='utf-8')
                build_site.export_kmafcst(str(root / 'site'))
                updated = json.loads((root / 'site/kmafcst/20261026.json').read_text())
                self.assertEqual(updated['fcst'][issue]['원주'][index], 13)
                self.assertEqual(updated['obs']['강릉'], output['obs']['강릉'])

    def test_comparison_accepts_wonju_and_keeps_missing_history_missing(self):
        valid = '2026102612'
        raw = {'강릉': {valid: 16}, '원주': {valid: 12}}
        got = fc.normalize_short('2026102605', raw)['cities']
        self.assertEqual(got['원주']['20261026']['hourly'][valid]['temp'], 12)
        self.assertIsNone(got['원주']['20261026']['tmax'])
        self.assertIsNone(got['원주']['20261026']['hourly'][valid]['wx'])
        self.assertNotIn('원주', fc.normalize_short('2026102505', {'강릉': {valid: 16}})['cities'])
        got = fc.normalize_mid('2026102606', {'강릉': {'20261030': {'min': 10, 'max': 20}}}, {'11D20000': {'wf4Am': '맑음'}, '11D10000': {'wf4Am': '흐림'}})['cities']
        self.assertEqual(got['원주']['20261030']['wx_am']['code'], 'overcast')
        self.assertIsNone(got['원주']['20261030']['tmin'])
        self.assertEqual(got['강릉']['20261030']['tmin']['value'], 10)


if __name__ == '__main__':
    unittest.main()
