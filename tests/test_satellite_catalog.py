import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
from satellite_catalog import normalize, export, CHANNELS, ORIGIN

NOW = datetime(2026, 10, 2, 0, 32, tzinfo=timezone.utc)

def row(channel, utc_time=NOW-timedelta(minutes=4)):
    _, prefix, suffix = CHANNELS[channel]
    return {'tm':(utc_time+timedelta(hours=9)).strftime('%Y%m%d%H%M'), 'url':'/w/repositary/image/sat/gk2a/KO/gk2a_ami_le1b_'+prefix+utc_time.strftime('%Y%m%d%H%M')+suffix}

class SatelliteCatalogTests(unittest.TestCase):
    def test_kst_and_utc_names_must_match(self):
        good=row('ir105',datetime(2026,10,1,15,2,tzinfo=timezone.utc))
        midnight=datetime(2026,10,1,15,10,tzinfo=timezone.utc)
        frames=normalize([good],'ir105',midnight)
        self.assertEqual(frames[0]['time'],'2026-10-01T15:02:00+00:00')
        wrong=dict(good,tm='202610020004')
        self.assertEqual(normalize([wrong],'ir105',midnight),[])

    def test_unexpected_urls_future_and_duplicates(self):
        good=row('rgb-cs')
        bad=dict(good,url='https://example.com/image.png')
        future=row('rgb-cs',NOW+timedelta(minutes=2))
        self.assertEqual(len(normalize([good,good,bad,future],'rgb-cs',NOW)),1)

    def test_failure_retains_timestamp_and_never_fetches_images(self):
        with tempfile.TemporaryDirectory() as directory:
            def good(channel,now): return normalize([row(channel)],channel,now)
            with patch('satellite_catalog.urllib.request.urlopen',side_effect=AssertionError('Unexpected network request')):
                initial=export(directory,fetcher=good,now=NOW)
                def fail(channel,now): raise TimeoutError()
                result=export(directory,fetcher=fail,now=NOW+timedelta(minutes=10))
            self.assertEqual(initial,result)
            self.assertEqual([p.name for p in Path(directory).iterdir()],['satellite.json'])
            self.assertLess(Path(directory,'satellite.json').stat().st_size,4000)
            self.assertEqual(json.loads(Path(directory,'satellite.json').read_text()),result)

    def test_expired_metadata_is_not_republished_as_current(self):
        with tempfile.TemporaryDirectory() as directory:
            export(directory,fetcher=lambda channel,now:normalize([row(channel)],channel,now),now=NOW)
            def fail(channel,now): raise TimeoutError()
            result=export(directory,fetcher=fail,now=NOW+timedelta(hours=7))
            self.assertTrue(all(not channel['frames'] for channel in result['channels'].values()))

if __name__=='__main__': unittest.main()
