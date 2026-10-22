import datetime as dt
import unittest
import numpy as np
from solar_ca_mapping import fit_lookup, irradiance_ratio, score_common, solar_reference


class MappingTests(unittest.TestCase):
    def test_same_cloud_can_have_different_dsr(self):
        lut = fit_lookup(np.array([100., 100., 100.]), np.array([100., 500., 900.]), min_count=1)
        self.assertEqual(lut.apply(np.array([100.]))[0], 500.)
        self.assertGreater(lut.p90[0] - lut.p10[0], 600)

    def test_missing_and_unseen_cloud_ranges_are_not_clear_sky(self):
        lut = fit_lookup(np.array([0., 5., 100., np.nan]),
                         np.array([800., 700., 100., 9999.]), min_count=1)
        out = lut.apply(np.array([2.5, 50, np.nan, -1, 101, 100.]))
        self.assertAlmostEqual(out[0], 750.)
        self.assertTrue(np.isnan(out[1:5]).all())
        self.assertEqual(out[5], 100.)

    def test_zero_dsr_and_enhancement_survive(self):
        ratio = irradiance_ratio(np.array([0., 900., np.nan, 10.]),
                                  np.array([800., 800., 800., 0.]))
        np.testing.assert_allclose(ratio[:2], [0., 1.125])
        self.assertTrue(np.isnan(ratio[2:]).all())

    def test_solar_adjustment(self):
        lut = fit_lookup(np.array([50., 50.]),
                         irradiance_ratio(np.array([400., 400.]), np.array([800., 800.])),
                         min_count=1)
        self.assertEqual((lut.apply(np.array([50.])) * 600)[0], 300)

    def test_common_mask_does_not_reward_missing_predictions(self):
        actual = np.array([100., 200., 300.])
        rows, mask = score_common(actual, {'a': np.array([110., np.nan, 310.]),
                                          'b': np.array([120., 9999., 320.])},
                                  np.ones(3, bool))
        self.assertEqual(rows['a']['n'], rows['b']['n'])
        self.assertEqual(rows['b']['mae'], 20)
        self.assertAlmostEqual(rows['a']['coverage'], 2/3)

    def test_utc_and_day_night(self):
        t = dt.datetime(2026, 3, 20, 3)
        g, el = solar_reference(t, np.array([127.]), np.array([37.]))
        self.assertTrue(700 < g[0] < 1000 and 45 < el[0] < 60)
        self.assertEqual(solar_reference(t + dt.timedelta(hours=12), np.array([127.]), np.array([37.]))[0][0], 0)
        local = t.replace(tzinfo=dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=9)))
        np.testing.assert_allclose(g, solar_reference(local, np.array([127.]), np.array([37.]))[0])


if __name__ == '__main__':
    unittest.main()
