import datetime as dt
import unittest
from unittest.mock import patch
from tools import collect_energy_sources as sources


class SourceTests(unittest.TestCase):
    def test_warning_does_not_select_preliminary_notice(self):
        markup = '<img src="/w/KTKO52_202611041600_108_4.png"><img src="/w/KTKO50_202611030200_108_13.png;jsessionid=x">'
        url, stamp = sources.parse_warning(markup)
        self.assertTrue(url.endswith('KTKO50_202611030200_108_13.png'))
        self.assertEqual(stamp.isoformat(), '2026-11-03T02:00:00+09:00')
        with self.assertRaises(ValueError):
            sources.parse_warning('<img src="/w/KTKO52_202611041600_108_4.png">')

    def test_pm10_preserves_missing_observations_and_actual_timestamp(self):
        markup = '[ PM10 : 1시간 평균값 ] <span>2026년 11월 04일(수) 06시</span>'
        markup += ''.join(f'<li class="pm10_{i}"><a>서울</a><span class="val">{v}</span></li>' for i, v in enumerate(['-', '42'] * 6))
        stamp, rows = sources.parse_pm10(markup)
        self.assertEqual(stamp.hour, 6)
        self.assertEqual(rows[0][2], '-')
        with self.assertRaises(ValueError):
            sources.parse_pm10(markup.replace('42', '-'))

    def test_one_failure_does_not_block_other_sources(self):
        now = dt.datetime(2026, 11, 4, 7, tzinfo=sources.KST)
        with patch.object(sources, 'warning', return_value={'src': 'warning-image', 'time': now.isoformat()}), patch.object(sources, 'pm10', side_effect=ValueError('stale')):
            result = sources.collect('20261104', now)
        self.assertEqual([s['available'] for s in result['sources']], [True, False])
        self.assertNotIn('src', result['sources'][1])

    def test_archived_date_never_receives_current_images(self):
        now = dt.datetime(2026, 11, 4, 7, tzinfo=sources.KST)
        with patch.object(sources, 'read', side_effect=AssertionError('No live requests for archived day')):
            result = sources.collect('20261103', now)
        self.assertTrue(all(not s['available'] for s in result['sources']))



if __name__ == '__main__':
    unittest.main()
