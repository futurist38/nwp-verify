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

    def test_seed_preserves_same_or_later_published_edits(self):
        for published_hour in (9, 10):
            with self.subTest(published_hour=published_hour), tempfile.TemporaryDirectory() as td:
                root=Path(td);source=root/'source';site=root/'site'
                seed=source/'20261029';seed.mkdir(parents=True)
                current=site/'energy'/'20261029';current.mkdir(parents=True)
                for folder,hour in ((seed,9),(current,published_hour)):
                    (folder/'report.json').write_text(json.dumps({'publication_kst':f'2026-10-29T{hour:02d}:00:00+09:00'}))
                    for name in ('01.webp','02.webp','editor.json'):
                        (folder/name).write_text('old seed' if folder==seed else 'published repair')
                (current/'editor2.json').write_text('{"groups": []}')
                publish_energy(site,source,dt.date(2026,10,29))
                for name in ('01.webp','02.webp','editor.json'):
                    self.assertEqual((current/name).read_text(),'published repair')
                self.assertEqual((current/'editor2.json').read_text(),'{"groups": []}')

    def test_newer_seed_advances_older_publication(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'source';site=root/'site'
            seed=source/'20261029';seed.mkdir(parents=True)
            current=site/'energy'/'20261029';current.mkdir(parents=True)
            for folder,hour in ((seed,9),(current,7)):
                (folder/'report.json').write_text(json.dumps({'publication_kst':f'2026-10-29T{hour:02d}:00:00+09:00'}))
                for name in ('01.webp','02.webp'):(folder/name).write_text(str(hour))
            publish_energy(site,source,dt.date(2026,10,29))
            self.assertEqual((current/'02.webp').read_text(),'9')
            self.assertEqual(json.loads((current/'report.json').read_text())['publication_kst'],'2026-10-29T09:00:00+09:00')

if __name__=='__main__':unittest.main()
