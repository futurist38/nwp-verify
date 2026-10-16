import unittest
import numpy as np
from cloud_layers import cloud_composite


class CloudLayersTest(unittest.TestCase):
    def test_full_range_stays_readable(self):
        low, mid, high = np.meshgrid(*([np.arange(0, 101, 5)] * 3), indexing="ij")
        rgb = cloud_composite(low, mid, high)
        brightness = rgb @ np.array([0.2126, 0.7152, 0.0722])
        self.assertTrue(np.all((rgb >= 0) & (rgb <= 1)))
        self.assertGreater(brightness.min(), 0.55)
        np.testing.assert_array_equal(rgb[0, 0, 0], [1, 1, 1])
        self.assertGreater(brightness[-1, -1, -1], 0.58)

    def test_missing_is_not_clear_and_broadcasts(self):
        rgb = cloud_composite(np.array([0, np.nan, np.inf, 100]), 0, 0)
        self.assertEqual(rgb.shape, (4, 3))
        np.testing.assert_array_equal(rgb[0], [1, 1, 1])
        np.testing.assert_array_equal(rgb[1], [0.9] * 3)
        np.testing.assert_array_equal(rgb[2], [0.9] * 3)

    def test_more_cloud_in_same_mixture_darkens_smoothly(self):
        cover = np.arange(101)
        rgb = cloud_composite(cover, cover * 0.7, cover * 0.3)
        self.assertTrue(np.all(np.diff(rgb, axis=0) <= 1e-12))
        np.testing.assert_allclose(cloud_composite(200, -10, 0),
                                   cloud_composite(100, 0, 0))


if __name__ == "__main__":
    unittest.main()
