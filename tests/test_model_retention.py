import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build_site as b
import model_image_retention as policy
from tools.site_storage import plan, trim_local

TODAY = dt.date(2026, 11, 10)

def key(day, model='gfs', run='00', panel='t2m', ext='webp'):
    return f'{day}/{model}_{day}{run}_f024_{panel}.{ext}'


class ModelRetentionTests(unittest.TestCase):
    def test_calendar_boundaries_models_and_all_steps_share_one_run(self):
        keys = {key(day, model, hour, panel, ext)
                for day in ['20261103','20261104','20261105','20261106','20261110']
                for model in ['gfs','kim','ecmwf'] for hour in ['00','12']
                for panel in ['sfc','t2m','p925','p850','p700','p500','p300']
                for ext in ['png','webp']}
        keep = policy.retained_model_keys(keys, TODAY)
        for path in keys:
            m = policy.MODEL_IMAGE_RE.fullmatch(path)
            expected = m['panel'].startswith('p') or (m['day'] >= '20261104' and (
                m['day'] >= '20261106' or m['run'].endswith('12')))
            self.assertEqual(path in keep, expected, path)
        # Each model chooses its own latest run; JSON and unusual paths are safe.
        special = {key('20261105','gfs','18'), key('20261105','kim','00'),
                   '20261001/city_upper_gfs_2026100100.json', '../notes.json'}
        self.assertEqual(policy.retained_model_keys(special,TODAY), special)

    def test_stale_remote_listing_cannot_restore_removed_runs_or_advertise_them(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(policy, 'today_kst', return_value=TODAY), patch('tools.site_storage.today_kst', return_value=TODAY), patch.object(b, 'today_kst', return_value=TODAY):
            root=Path(tmp); folder=root/'archive/20261105';folder.mkdir(parents=True)
            old=key('20261105');new=key('20261105',run='12')
            upper=key('20261105',panel='p500');data='20261105/city_upper_gfs_2026110500.json'
            for path in [old,upper,data]:
                (root/'archive'/path).write_bytes(b'1234')
            listing=root/'listing'; listing.write_text('\n'.join([old,new,upper,data]))
            count,size=policy.prune_model_images(root,[old,new,upper,data])
            self.assertEqual((count,size),(1,4))
            plan(root,listing,root/'plan')
            self.assertEqual((root/'plan.delete').read_text().splitlines(),[old])
            self.assertEqual((root/'plan.restore').read_text().splitlines(),[new])
            with patch.dict('os.environ',{'R2_LISTING':str(listing)}):
                b.build_manifest(str(root))
            runs=json.loads((root/'manifest.json').read_text())['dates']['20261105']['models']['GFS']['runs']
            self.assertEqual(runs['2026110500']['panels'],['p500'])
            self.assertEqual(runs['2026110512']['panels'],['t2m'])
            trim_local(root)
            self.assertTrue((root/'archive'/data).exists())
            self.assertFalse((root/'archive'/upper).exists())
            self.assertEqual(policy.prune_model_images(root,[old,new,upper,data]),(0,0))

    def test_expired_images_do_not_delete_numerical_archives_or_other_products(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(policy,'today_kst',return_value=TODAY), patch('tools.site_storage.today_kst',return_value=TODAY), patch.object(b,'today_kst',return_value=TODAY):
            root=Path(tmp);(root/'archive/20260901').mkdir(parents=True)
            data='20260901/city_upper_gfs_2026090100.json'
            old=key('20260901'); upper=key('20260901',panel='p300')
            listing=root/'list';listing.write_text('\n'.join([data,old,upper]))
            (root/'archive'/data).write_text('{}')
            plan(root,listing,root/'p')
            self.assertEqual(set((root/'p.delete').read_text().splitlines()),{old,upper})
            (root/'daily').mkdir();(root/'daily/20260901.json').write_text('{}')
            (root/'nowcast').mkdir();(root/'nowcast/map_1h.webp').write_bytes(b'nc')
            (root/'energy').mkdir();(root/'energy/report.webp').write_bytes(b'energy')
            with patch.object(b,'OUT_DIR',str(root/'output')):
                b.copy_outputs(str(root))
            self.assertTrue((root/'archive'/data).exists())
            self.assertTrue((root/'daily/20260901.json').exists())
            self.assertEqual((root/'nowcast/map_1h.webp').read_bytes(),b'nc')
            self.assertEqual((root/'energy/report.webp').read_bytes(),b'energy')
