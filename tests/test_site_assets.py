from pathlib import Path
import tempfile
import unittest

from site_assets import ENERGY_EDITOR_FILES, copy_static_assets


class SiteAssetsTests(unittest.TestCase):
    def test_stale_observation_publish_preserves_released_editor(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target = root / 'stale-checkout', root / 'restored-site-data'
            source.mkdir()
            target.mkdir()
            for name in ENERGY_EDITOR_FILES:
                (source / name).write_bytes(b'old editor')
                (target / name).write_bytes(b'validated editor')
            (source / 'app.js').write_bytes(b'new platform')
            (target / 'app.js').write_bytes(b'old platform')
            report = target / 'energy' / '20261104' / 'report.json'
            report.parent.mkdir(parents=True)
            report.write_bytes(b'published report')

            # A second normal publish must also retain the editor bundle.
            for _ in range(2):
                copy_static_assets(source, target)
                for name in ENERGY_EDITOR_FILES:
                    self.assertEqual((target / name).read_bytes(), b'validated editor', name)
                self.assertEqual((target / 'app.js').read_bytes(), b'new platform')
                self.assertEqual(report.read_bytes(), b'published report')

    def test_missing_assets_are_bootstrapped(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target = root / 'checkout', root / 'new-site'
            source.mkdir()
            for name in ENERGY_EDITOR_FILES | {'index.html'}:
                (source / name).write_bytes(name.encode())
            copy_static_assets(source, target)
            for asset in source.iterdir():
                self.assertEqual((target / asset.name).read_bytes(), asset.read_bytes())


if __name__ == '__main__':
    unittest.main()
