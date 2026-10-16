import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build_site as site


class UpperRetirementTest(unittest.TestCase):
    def test_deletion_targets_only_dated_retired_map_keys(self):
        for model in ("ecmwf", "gfs", "kim"):
            for ext in ("png", "webp"):
                self.assertTrue(site.is_disabled_upper_key(
                    f"20261016/{model}_2026101600_f024_p200.{ext}"))
        for key in (
            "20261016/gfs_2026101600_f024_p300.webp",
            "20261016/gfs_2026101600_f024_p200.json",
            "20261016/city_upper_gfs_2026101600.json",
            "20261016/notes_p200.webp",
            "notes/gfs_2026101600_f024_p200.webp",
            "../gfs_2026101600_f024_p200.webp",
            "20261016/nested/gfs_2026101600_f024_p200.webp",
        ):
            self.assertFalse(site.is_disabled_upper_key(key), key)

    def test_local_cleanup_and_stale_remote_listing_preserve_300(self):
        day = dt.date.today().strftime("%Y%m%d")
        stem = f"gfs_{day}00_f024_"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "site" / "archive" / day
            archive.mkdir(parents=True)
            for name in (stem + "p200.webp", stem + "p200.png",
                         stem + "p300.webp", "city_upper_gfs.json"):
                (archive / name).write_bytes(b"preserve-or-delete")
            site.prune_disabled_upper(str(root / "site"))
            self.assertEqual({p.name for p in archive.iterdir()},
                             {stem + "p300.webp", "city_upper_gfs.json"})
            listing = root / "listing"
            listing.write_text(f"{day}/{stem}p200.webp\n{day}/{stem}p300.webp\n")
            with patch.dict("os.environ", {"R2_LISTING": str(listing)}):
                site.build_manifest(str(root / "site"))
            data = json.loads((root / "site" / "manifest.json").read_text())
            run = data["dates"][day]["models"]["GFS"]["runs"][day + "00"]
            self.assertEqual(run["panels"], ["p300"])
            self.assertEqual(run["psteps"], {"p300": [24]})
            # Old local output must not reintroduce the deleted image.
            output = root / "output" / day / "upper"
            output.mkdir(parents=True)
            for level in (200, 300):
                (output / f"{stem}p{level}.png").write_bytes(b"image")
            with patch.object(site, "OUT_DIR", str(root / "output")):
                site.copy_outputs(str(root / "site"))
            self.assertFalse((archive / f"{stem}p200.png").exists())
            self.assertTrue((archive / f"{stem}p300.png").exists())

    def test_collection_and_old_data_rendering_skip_200(self):
        import numpy as np
        import fetch_upper
        import fetch_kim_nc
        import plot_upper

        url = fetch_upper.gfs_url("20261016", "00", 24)
        self.assertNotIn("lev_200_mb", url)
        self.assertIn("lev_300_mb=on", url)
        self.assertNotIn(200, fetch_kim_nc.UPPER_VARS)
        self.assertIn(300, fetch_kim_nc.UPPER_VARS)
        fields = {(v, "isobaricInhPa", level): {24: np.ones((2, 2))}
                  for level in (200, 300) for v in ("gh", "u", "v")}
        with patch.object(plot_upper, "draw_panel") as draw, \
             patch.object(plot_upper, "dump_city_values"):
            count = plot_upper._render_levels("GFS", fields, [30, 31], [120, 121],
                                              dt.datetime(2026, 10, 16), "unused")
        self.assertEqual(count, 1)
        self.assertEqual(draw.call_args.args[3], 300)
        # Rendering definitions survive for a deliberate future reactivation.
        self.assertIn(200, plot_upper.CONTOUR)
        self.assertIn(200, plot_upper.FILL)
        self.assertIn(200, plot_upper.PL_VARS)


if __name__ == "__main__":
    unittest.main()
