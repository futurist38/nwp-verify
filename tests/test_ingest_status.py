import unittest

from tools.ingest_status import classify


class Classification(unittest.TestCase):
    def test_complete_cached_forecasts(self):
        output = ('[예보변화] 2026111305: 재사용 97, 조회 0, 수신 0, 미완료 0지점, 0.07초\n'
                  '[예보변화] 2026111217: 재사용 97, 조회 0, 수신 0, 미완료 0지점, 0.07초')
        self.assertEqual(classify(0, output), ('success', None))

    def test_non_ingest_warnings(self):
        for output in ('DownloadWarning: Downloading: coastline.zip',
                       'DeprecationWarning: datetime.datetime.utcnow() is deprecated',
                       'UserWarning: plotting configuration\n[nowcast] 표출 → output',
                       'findfont: Failed to find font weight bold'):
            with self.subTest(output=output):
                self.assertEqual(classify(0, output), ('success', None))

    def test_missing_data_stays_partial(self):
        for output in ('미완료 1지점', '미완료 10지점\n미완료 0지점',
                       '캐시 미완료', '미완료 0지점\n[GFS] f024 수신 실패 (건너뜀)',
                       'Warning: 수신 실패'):
            with self.subTest(output=output):
                self.assertEqual(classify(0, output)[0], 'partial')

    def test_nonzero_exit_overrides_complete_output(self):
        for code in (1, 124):
            self.assertEqual(classify(code, '미완료 0지점')[0], 'failed')
        self.assertEqual(classify(124, '')[1], '시간초과')


if __name__ == '__main__':
    unittest.main()
