import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import plot_fcstdiff as maps
from fcstdiff_cache import clean_series, complete, expired_cache_path, read_cache, write_cache

DAY = dt.date(2026, 11, 11)


def series(value=0, hours=24, day=DAY):
    return {f'{day:%Y%m%d}{h:02d}': value + h for h in range(hours)}


def stations(ids):
    return pd.DataFrame([{'STN': i, 'nx': i, 'ny': 1, 'lon': 127., 'lat': 37.} for i in ids])


class ForecastChangeCacheTests(unittest.TestCase):
    def test_both_issues_reuse_all_194_records_without_auth_or_api(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(maps, 'CACHE_DIR', tmp), \
                patch.object(maps, 'DEADLINE', 0), contextlib.redirect_stdout(io.StringIO()):
            stns = stations(range(1, 98))
            with patch.object(maps, 'fetch', return_value={'TMP': series()}) as fetch:
                expected = [maps.load_issue(issue, stns, 'test', target_days=[DAY])
                            for issue in ('2026111005', '2026110917')]
                self.assertEqual(fetch.call_count, 194)
            with patch.object(maps, 'fetch', side_effect=AssertionError('unexpected network')), \
                    patch.object(maps, 'auth_key', side_effect=AssertionError('unexpected key read')):
                actual = [maps.load_issue(issue, stns, target_days=[DAY], cache_only=True)
                          for issue in ('2026111005', '2026110917')]
            self.assertEqual(actual, expected)

    def test_partial_empty_and_failed_stations_only_are_retried(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(maps, 'CACHE_DIR', tmp), \
                patch.object(maps, 'DEADLINE', 0), contextlib.redirect_stdout(io.StringIO()):
            path = Path(tmp) / '2026111005.json'
            write_cache(path, {'1': series(), '2': series(hours=23), '3': {}})
            calls = []
            def fetch(nx, *args):
                calls.append(nx)
                if nx == 3:
                    raise RuntimeError('upstream unavailable')
                return {'TMP': {f'{DAY:%Y%m%d}23': 23}}
            with patch.object(maps, 'fetch', side_effect=fetch):
                result = maps.load_issue('2026111005', stations([1, 2, 3]), 'test', target_days=[DAY])
            self.assertEqual(calls, [2, 3])
            self.assertEqual(result['2'], series())
            with patch.object(maps, 'fetch', return_value={'TMP': series()}) as fetch:
                maps.load_issue('2026111005', stations([1, 2, 3]), 'test', target_days=[DAY])
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(fetch.call_args.args[0], 3)

    def test_corrupt_cache_recovers_and_nonfinite_or_wrong_day_is_not_a_hit(self):
        bad = {**series(), f'{DAY:%Y%m%d}12': float('nan'), '2026111199': 3, 'x': 2}
        self.assertFalse(complete(clean_series(bad), [DAY]))
        self.assertFalse(complete(series(day=DAY - dt.timedelta(days=1)), [DAY]))
        self.assertEqual(clean_series({f'{DAY:%Y%m%d}00': 0, f'{DAY:%Y%m%d}01': True}), {f'{DAY:%Y%m%d}00': 0.})
        with tempfile.TemporaryDirectory() as tmp, patch.object(maps, 'CACHE_DIR', tmp), \
                patch.object(maps, 'DEADLINE', 0), contextlib.redirect_stdout(io.StringIO()):
            path = Path(tmp) / '2026111005.json'; path.write_text('{broken')
            with patch.object(maps, 'fetch', return_value={'TMP': series()}):
                maps.load_issue('2026111005', stations([1]), 'test', target_days=[DAY])
            self.assertTrue(complete(read_cache(path)['1'], [DAY]))

    def test_received_station_survives_interruption_and_failed_atomic_replace(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(maps, 'CACHE_DIR', tmp), \
                patch.object(maps, 'DEADLINE', 0):
            with patch.object(maps, 'fetch', side_effect=[{'TMP': series()}, KeyboardInterrupt]):
                with self.assertRaises(KeyboardInterrupt):
                    maps.load_issue('2026111005', stations([1, 2]), 'test', target_days=[DAY])
            path = Path(tmp) / '2026111005.json'; before = path.read_bytes()
            self.assertEqual(set(read_cache(path)), {'1'})
            with patch('fcstdiff_cache.os.replace', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    write_cache(path, {'2': series()})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(tmp).glob('*.tmp')), [])

    def test_cache_only_fails_closed_and_deadline_retains_received_values(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(maps, 'CACHE_DIR', tmp), \
                patch.object(maps, 'fetch', side_effect=AssertionError('network forbidden')), \
                patch.object(maps, 'auth_key', side_effect=AssertionError('key forbidden')), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'API 호출 없음'):
                maps.load_issue('2026111005', stations([1]), target_days=[DAY], cache_only=True)
            with patch.object(maps, 'DEADLINE', 1):
                self.assertEqual(maps.load_issue('2026111005', stations([1]), target_days=[DAY]), {})

    def test_four_day_retention_never_matches_results_or_other_history(self):
        today = dt.date(2026, 11, 10)
        self.assertTrue(expired_cache_path('verification/fcstdiff/2026110605.json', today))
        self.assertFalse(expired_cache_path('verification/fcstdiff/2026110705.json', today))
        self.assertFalse(expired_cache_path('verification/fcstdiff_data/2026110605.json', today))
        self.assertFalse(expired_cache_path('verification/obs/2026110605.json', today))

    def test_existing_twenty_hour_rule_and_finite_json_output(self):
        self.assertIsNone(maps.daily_stat(series(hours=19), DAY, np.max))
        self.assertEqual(maps.daily_stat(series(hours=20), DAY, np.max), 19)
        with tempfile.TemporaryDirectory() as tmp, patch.object(maps, 'VERIF_DIR', tmp + '/verification'), \
                patch.object(maps, 'OUT_DIR', tmp + '/output'), patch.object(maps, 'CACHE_DIR', tmp + '/cache'), \
                patch.object(maps, 'stations', return_value=stations([1, 2])), \
                patch.object(maps, 'load_issue', side_effect=[{'1': series(value=2)}, {'1': series()}]), \
                patch('sys.argv', ['plot_fcstdiff.py', '--issue', '2026111005', '--no-plot']), \
                contextlib.redirect_stdout(io.StringIO()):
            maps.main()
            text = (Path(tmp) / 'verification/fcstdiff_data/20261110.json').read_text()
            result = json.loads(text, parse_constant=lambda token: self.fail(token))
            self.assertEqual(result['vars'], {'tmx': {'1': 2.0}, 'tmn': {'1': 2.0}})
            self.assertEqual((result['prev'], result['now'], result['target']),
                             ('2026110917', '2026111005', '20261111'))


if __name__ == '__main__':
    unittest.main()
