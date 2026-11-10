from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
import build_site as b


class WebpPublicationTests(unittest.TestCase):
    def test_original_png_is_encoded_once_and_existing_webp_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=root/'archive/20261110';archive.mkdir(parents=True)
            png=archive/'gfs_2026111000_f024_p500.png'
            Image.new('RGB',(120,80),'white').save(png)
            existing=archive/'gfs_2026111000_f048_p500.webp'
            Image.new('RGB',(120,80),'blue').save(existing,format='WEBP',quality=82,method=4)
            original=existing.read_bytes()
            b.to_webp(tmp)
            self.assertFalse(png.exists())
            with Image.open(png.with_suffix('.webp')) as im:
                self.assertEqual(im.size,(120,80))
            self.assertEqual(existing.read_bytes(),original)
            produced=png.with_suffix('.webp').read_bytes()
            b.to_webp(tmp)
            self.assertEqual(png.with_suffix('.webp').read_bytes(),produced)

    def test_encoder_failure_keeps_png_and_previous_webp(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'archive/20261110';folder.mkdir(parents=True)
            png=folder/'gfs_2026111000_f024_t2m.png';png.write_bytes(b'original PNG')
            webp=png.with_suffix('.webp');webp.write_bytes(b'previous WebP')
            with patch('PIL.Image.open',side_effect=OSError('encoder failure')):
                b.to_webp(tmp)
            self.assertEqual(png.read_bytes(),b'original PNG')
            self.assertEqual(webp.read_bytes(),b'previous WebP')
