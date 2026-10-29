"""Wonju must be its own real station/grid, never a nearby-city fallback."""
import csv
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from config import CITIES, CITY_OBS_STN, DISPLAY_CITIES
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
        cities = {c: {day: {'min': 10, 'max': 20}} for c in REGS if c not in {'원주', '청주'}}
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


class TwelveCityPipelineTests(unittest.TestCase):
    ORDER = ['서울', '인천', '수원', '원주', '강릉', '대전', '청주', '전주',
             '광주', '대구', '부산', '제주']
    ADDED = {
        '수원': (119, (37.25746, 126.983), (60, 120), '11B20601', '11B00000'),
        '청주': (131, (36.63924, 127.44066), (68, 107), '11C10301', '11C10000'),
        '전주': (146, (35.84092, 127.11718), (63, 89), '11F10201', '11F10000'),
    }

    def test_shared_order_station_grids_and_official_medium_codes(self):
        import build_site
        self.assertEqual(list(DISPLAY_CITIES), self.ORDER)
        self.assertEqual([c[0] for c in CITIES[:12]], self.ORDER)
        self.assertEqual(build_site.KMAF_CITIES, self.ORDER)
        self.assertEqual(list(short.CITY_GRID), self.ORDER)
        self.assertEqual(list(REGS), self.ORDER)
        self.assertEqual(list(fc.CITY_REGIONS), self.ORDER)
        # Retain legacy model-only Naju, but do not invent an ASOS observation.
        self.assertIn('나주', [c[0] for c in CITIES])
        self.assertIsNone(CITY_OBS_STN['나주'])
        with open(Path(__file__).resolve().parents[1] / 'verification/obs/stations.csv', encoding='utf-8-sig') as f:
            stations = {r['name']: r for r in csv.DictReader(f)}
        for city, (stn, position, grid, mid, land) in self.ADDED.items():
            with self.subTest(city=city):
                station = stations[city]
                self.assertEqual(int(station['STN']), stn)
                self.assertEqual((float(station['lat']), float(station['lon'])), position)
                self.assertEqual(next(c[1:3] for c in CITIES if c[0] == city), position)
                self.assertEqual(CITY_OBS_STN[city], stn)
                self.assertIn(stn, kma_asos.default_stations())
                self.assertIn(stn, kma_asos.all_stations())
                self.assertEqual(short.CITY_GRID[city], grid)
                self.assertEqual(latlon_to_grid(*position), grid)
                self.assertEqual(REGS[city], mid)
                self.assertEqual(fc.CITY_REGIONS[city], land)

    def test_three_new_short_grids_collect_once_without_replacing_existing_cities(self):
        issue, valid = '2026102605', '2026102612'
        old = {'서울': {valid: 20}, **{'서울#'+c: {} for c in short.EXTRA_CATS}}
        grids = {c: short.CITY_GRID[c] for c in ['서울', *self.ADDED]}
        def receive(nx, ny, *args, **kwargs):
            # Deliberately different city temperatures catch accidental grid reuse.
            return {'TMP': {valid: nx-ny}, **{c: {} for c in short.EXTRA_CATS}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '20261026.json'
            path.write_text(json.dumps({issue: old}), encoding='utf-8')
            with patch.object(short, 'CACHE_DIR', tmp), patch.object(short, 'CITY_GRID', grids), patch.object(short, 'fetch', side_effect=receive) as fetch:
                got = short.load_fcst_cached(dt.date(2026, 10, 26), [issue], 'test-only')
                self.assertEqual(got[issue]['서울'], old['서울'])
                for city, (_, _, (nx, ny), _, _) in self.ADDED.items():
                    self.assertEqual(got[issue][city], {valid: nx-ny})
                self.assertEqual([c.args[:2] for c in fetch.call_args_list], [grids[c] for c in self.ADDED])
                short.load_fcst_cached(dt.date(2026, 10, 26), [issue], 'test-only')
                self.assertEqual(fetch.call_count, 3)

    def test_medium_new_optional_city_does_not_expand_existing_completeness_gate(self):
        import kma_midfcst as mid
        expected = set(self.ORDER) - {'원주', '청주'}
        self.assertEqual(mid.REQUIRED_CITIES, expected)
        issue, day = '2026102606', '20261030'
        cities = {c: {day: {'min': 0, 'max': 10}} for c in expected}
        with tempfile.TemporaryDirectory() as tmp, patch.object(mid, 'CACHE_DIR', tmp), patch.object(mid, 'collect', return_value={issue: cities}), patch('sys.argv', ['kma_midfcst.py']):
            mid.main()
            saved = json.loads((Path(tmp) / (issue + '.json')).read_text())
            self.assertNotIn('청주', saved)
            cities['청주'] = {day: {'min': -1, 'max': 9}}
            cities['서울'] = {day: {'min': 99, 'max': 99}}
            mid.main()
            saved = json.loads((Path(tmp) / (issue + '.json')).read_text())
            self.assertEqual(saved['청주'][day]['min'], -1)
            self.assertEqual(saved['서울'][day]['min'], 0)

    def test_short_export_has_all_twelve_cities_and_missing_is_null_not_older_or_zero(self):
        import build_site
        issue, previous, valid = '2026102605', '2026102517', '2026102612'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'kmafcst').mkdir(); (root / 'obs').mkdir()
            raw = {previous: {'청주': {valid: 99}}, issue: {'서울': {valid: 0}, '수원': {valid: 12}}}
            (root / 'kmafcst/20261026.json').write_text(json.dumps(raw), encoding='utf-8')
            (root / 'obs/2026-10.csv').write_text('TM,STN,TA,CA_TOT\n2026-10-26 12:00:00,119,11,0\n2026-10-26 11:00:00,131,20,3\n', encoding='utf-8')
            with patch.object(build_site, 'VERIF_DIR', str(root)):
                build_site.export_kmafcst(str(root / 'site'))
            out = json.loads((root / 'site/kmafcst/20261026.json').read_text())
            ix = int((dt.datetime.strptime(valid, '%Y%m%d%H') - dt.datetime.strptime(out['t0'], '%Y%m%d%H')).total_seconds() / 3600)
            self.assertEqual(out['cities'], self.ORDER)
            self.assertEqual(list(out['fcst'][issue]), self.ORDER)
            self.assertEqual(list(out['obs']), self.ORDER)
            self.assertEqual(out['fcst'][issue]['서울'][ix], 0)
            self.assertEqual(out['obs']['수원'][ix], 11)
            self.assertIsNone(out['obs']['청주'][ix])
            self.assertIsNone(out['fcst'][issue]['청주'][ix])
            self.assertEqual(out['fcst'][previous]['청주'][ix], 99)
            self.assertTrue(all(v is None for v in out['fcst'][issue]['전주']))

    def test_medium_export_and_manifest_advertise_twelve_cities_even_when_values_missing(self):
        import build_site
        today = dt.date.today(); issue = f'{today:%Y%m%d}06'; day = f'{today + dt.timedelta(days=4):%Y%m%d}'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'midfcst').mkdir(); site = root / 'site'; site.mkdir()
            (root / 'midfcst' / (issue + '.json')).write_text(json.dumps({'서울': {day: {'min': 0, 'max': 10}}}), encoding='utf-8')
            with patch.object(build_site, 'VERIF_DIR', str(root)):
                self.assertTrue(build_site.export_midfcst(str(site)))
                build_site.build_manifest(str(site))
            out = json.loads((site / 'midfcst/index.json').read_text())
            self.assertEqual(out['cities'], self.ORDER)
            self.assertEqual(out['fcst'][issue]['서울'][day][:2], [0, 10])
            self.assertEqual(out['fcst'][issue]['청주'], {})
            self.assertEqual(out['obs']['청주'], {})
            self.assertEqual(json.loads((site / 'manifest.json').read_text())['city_order'], self.ORDER)

    def test_observation_metadata_marks_twelve_without_removing_other_stations(self):
        import build_site
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'obs').mkdir()
            catalog = Path(__file__).resolve().parents[1] / 'verification/obs/stations.csv'
            (root / 'obs/stations.csv').write_bytes(catalog.read_bytes())
            with patch.object(build_site, 'VERIF_DIR', str(root)):
                build_site.export_obs(str(root / 'site'))
            meta = json.loads((root / 'site/obs/stations.json').read_text())
            self.assertEqual(meta['city_order'], self.ORDER)
            self.assertEqual({s['n'] for s in meta['stations'] if s['L']}, set(self.ORDER))
            self.assertGreater(len(meta['stations']), 12)

    def test_comparison_normalizes_only_actual_new_city_records_and_keeps_archive(self):
        day, valid = '20261030', '2026102612'
        short_doc = fc.normalize_short('2026102605', {'수원': {valid: 0}, '청주': {valid: -1}})
        self.assertEqual(short_doc['cities']['수원']['20261026']['hourly'][valid]['temp'], 0)
        self.assertNotIn('전주', short_doc['cities'])
        mid = fc.normalize_mid('2026102606', {}, {'11C10000': {'wf4Am': '흐림'}})['cities']
        self.assertEqual(mid['청주'][day]['wx_am']['code'], 'overcast')
        self.assertIsNone(mid['청주'][day]['tmin'])
        self.assertNotIn('대전', mid)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); verif = root / 'verification'; site = root / 'site'
            fc.write(verif / 'kmafcst/20261026.json', {'2026102605': {'수원': {valid: 0}}, '2026102517': {'청주': {valid: 49}}})
            entries = fc.export(site, verif, archive=True)
            self.assertEqual(len(entries), 2)
            idx = fc.read(site / 'forecast_compare/index.json')
            self.assertEqual(idx['city_order'], self.ORDER)
            latest = fc.read(site / 'forecast_compare/issues/2026102605-short.json')
            self.assertNotIn('청주', latest['cities'])
            self.assertTrue((verif / 'forecast_compare/2026102517-short.json').exists())


if __name__ == '__main__':
    unittest.main()
