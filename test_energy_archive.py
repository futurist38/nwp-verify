import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from energy_archive import publish_energy

class RetentionTests(unittest.TestCase):
    def test_cutoff_and_expired_seed_not_restored(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'source';site=root/'site'
            for day in ['20260929','20260930','20261029']:
                folder=source/day;folder.mkdir(parents=True)
                for name in ['01.webp','02.webp','report.json']:(folder/name).write_text('{}')
            old=site/'energy'/'20260929';old.mkdir(parents=True)
            keep=site/'energy'/'other';keep.mkdir()
            result=publish_energy(site,source,dt.date(2026,10,29))
            self.assertEqual(result['dates'],['20261029','20260930'])
            self.assertFalse(old.exists());self.assertTrue(keep.exists())
            result=publish_energy(site,source,dt.date(2026,11,28))
            self.assertEqual(result['dates'],[])

if __name__=='__main__':unittest.main()
