import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import xarray as xr
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

from solar_radiation import solar_field, draw_solar, is_solar_step


def field(values, window=3):
    da = xr.DataArray(np.asarray(values, dtype=float), dims=("latitude", "longitude"),
                      coords={"latitude": [38, 37], "longitude": [126, 127]})
    return da.assign_coords(win_h=window) if window is not None else da


class SolarMapsTest(unittest.TestCase):
    def test_window_missing_data_and_night(self):
        for step in (0, 1, 121, 132):
            self.assertFalse(is_solar_step(step))
        for step in (3, 120):
            self.assertIsNotNone(solar_field(field([[0, 0], [0, 0]]), step))
        for window in (None, 0, 6, float("nan")):
            self.assertIsNone(solar_field(field([[10, 20], [30, 40]], window), 6))
        self.assertIsNone(solar_field(field([[np.nan] * 2] * 2), 3))
        result = solar_field(field([[-0.5, np.nan], [np.inf, 1100]]), 3)
        self.assertEqual(result[0, 0], 0)
        self.assertEqual(result[1, 1], 1100)
        self.assertEqual(result.mask.tolist(), [[False, True], [True, False]])

    def test_actual_filled_contours_share_scale_and_render_zero(self):
        for values in ([[0, 0], [0, 0]], [[0, 400], [800, 1100]]):
            fig, ax = plt.subplots()
            try:
                contour = draw_solar(fig, ax, [126, 127], [38, 37],
                                     solar_field(field(values), 3))
                fig.canvas.draw()
                self.assertEqual(contour.levels.tolist(), list(range(0, 1001, 10)))
                self.assertEqual(contour.get_clim(), (0, 1000))
                self.assertEqual(contour.extend, "max")
                self.assertTrue(any(path.vertices.size for path in contour.get_paths()))
            finally:
                plt.close(fig)

    def test_plot_pipeline_skips_invalid_windows_and_saves_150dpi(self):
        import plot_charts
        steps = [0, 3, 6, 9, 120, 132]
        arr = xr.DataArray(np.zeros((len(steps), 2, 2)),
                           dims=("step", "latitude", "longitude"),
                           coords={"step": np.array(steps, dtype="timedelta64[h]"),
                                   "latitude": [38, 37], "longitude": [126, 127]})
        solar = arr.copy().assign_coords(win_h=("step", [0, 3, 6, 3, 3, 3]))
        solar.loc[{"step": np.timedelta64(9, "h")}] = np.nan
        data = {"run": dt.datetime(2026, 10, 22), "t2m": arr, "dswrf": solar}
        with tempfile.TemporaryDirectory() as tmp, patch.object(plot_charts, "HAS_CARTOPY", False):
            plot_charts.plot_maps("ECMWF", data, tmp, panels={"dswrf"})
            files = sorted(Path(tmp).glob("*.png"))
            self.assertEqual([p.name for p in files], [
                "ecmwf_2026102200_f003_dswrf.png", "ecmwf_2026102200_f120_dswrf.png"])
            for path in files:
                with Image.open(path) as img:
                    self.assertEqual(img.size, (1110, 885))

    def test_publisher_keeps_solar_and_manifest_filters_local_and_remote_steps(self):
        import build_site
        ymd = dt.date.today().strftime("%Y%m%d")
        run = ymd + "00"
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp, "archive", ymd)
            folder.mkdir(parents=True)
            for step, panel in [(0, "dswrf"), (3, "dswrf"), (132, "dswrf"), (0, "t2m")]:
                (folder / f"ecmwf_{run}_f{step:03d}_{panel}.webp").touch()
            retired = folder / "meteogram_test.webp"
            retired.touch()
            build_site.prune_kmafcst(tmp)
            self.assertFalse(retired.exists())
            self.assertTrue((folder / f"ecmwf_{run}_f003_dswrf.webp").exists())
            listing = Path(tmp, "r2.txt")
            listing.write_text("\n".join(
                f"{ymd}/gfs_{run}_f{s:03d}_dswrf.webp" for s in [0, 3, 120, 132]))
            with patch.dict(os.environ, {"R2_LISTING": str(listing), "IMG_BASE": ""}):
                build_site.build_manifest(tmp)
            models = json.loads(Path(tmp, "manifest.json").read_text())["dates"][ymd]["models"]
            self.assertEqual(models["ECMWF"]["runs"][run]["psteps"], {"dswrf": [3], "t2m": [0]})
            self.assertEqual(models["GFS"]["runs"][run]["psteps"]["dswrf"], [3, 120])


if __name__ == "__main__":
    unittest.main()
