"""Synthetic NetCDF integration checks; these do not certify KMA's live format."""
import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import xarray as xr
import digital_mid as dm


class DigitalMidTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.issue = '2026101218'
        self.now = dt.datetime(2026,10,12,19,tzinfo=dm.KST)
        p = {'id':'synthetic-only', 'verified':True, 'timezone':'UTC',
             'cities':{'서울':[37.5,127]}, 'max_distance_km':10,
             'daily_leads':[5,6], 'hourly_leads':[120,123,126,132],
             'codes':{k:{'1':'synthetic category'} for k in ('SKY','PTY','RPOS','RVAR')}, 'fields':{}}
        for k in (*dm.CORE, *(b+q for b in ('TMP','TMN','TMX') for q in dm.QUANTILES)):
            p['fields'][k] = {'variable':'value','time':'time','latitude':'lat','longitude':'lon',
                              'issue_attribute':'forecast_reference_time','units':'degC' if k.startswith(('TMP','TMN','TMX')) else '1'}
            if k.startswith(('TMN','TMX')):
                p['fields'][k]['date_offset_hours']=0
        self.cfg={'mode':'shadow','profile':p,'display_days':21}
        self.paths={}
        for k in p['fields']:
            self.fixture(k)

    def fixture(self,k,values=None,issue=None,times=None):
        daily=k.startswith(('TMN','TMX'))
        if times is None:
            times = np.array(['2026-10-16T15:00','2026-10-17T15:00'],dtype='datetime64[ns]') if daily else np.array(['2026-10-17T09:00','2026-10-17T12:00','2026-10-17T15:00','2026-10-17T21:00'],dtype='datetime64[ns]')
        value = 10 if k.startswith('TMN') else 20 if k.startswith(('TMP','TMX')) else 1
        for q,n in [('10P',-4),('25P',-2),('75P',2),('90P',4)]:
            if k.endswith(q): value+=n
        data=np.full((len(times),2,2),value,dtype=float) if values is None else values
        ds=xr.Dataset({'value':(('time','lat','lon'),data,{'units':self.cfg['profile']['fields'][k]['units']})},
                      coords={'time':times,'lat':[37.5,38.0],'lon':[127.0,128.0]},
                      attrs={'forecast_reference_time':issue or '2026-10-12T09:00:00'})
        path=self.root/f'DFS_MEDM_GRD_GEMD_HR36_{k}.{self.issue}00.nc'
        ds.to_netcdf(path,engine='scipy')
        self.paths[k]=path

    def test_real_netcdf_normalization_and_quantile_semantics(self):
        d=dm.normalize(self.paths,self.cfg,self.issue)
        c=d['cities']['서울']
        self.assertEqual(list(c['daily']),['20261017','20261018'])
        self.assertEqual(list(c['hourly']),['2026101718','2026101721','2026101800','2026101806'])
        self.assertEqual(c['daily']['20261017']['TMX_quantiles']['p90'],24)
        self.assertEqual(c['daily']['20261017']['TMX'],20)
        self.assertEqual(c['hourly']['2026101718']['RPOS']['raw'],1)

    def test_off_makes_no_network_requests(self):
        with patch('digital_mid.download',side_effect=AssertionError('network')):
            self.assertIsNone(dm.collect({'mode':'off'},self.root/'cache'))

    def test_unverified_profile_is_rejected(self):
        self.cfg['profile']['verified']=False
        with self.assertRaises(dm.InvalidData): dm.normalize(self.paths,self.cfg,self.issue)

    def test_issue_mismatch_rejected_without_cache(self):
        self.fixture('TMP',issue='2026-10-11T09:00:00')
        with self.assertRaises(dm.InvalidData):
            dm.collect(self.cfg,self.root/'cache',self.issue,self.root,now=self.now)
        self.assertFalse((self.root/'cache').exists())

    def test_missing_masked_city_rejected(self):
        arr=np.ones((4,2,2)); arr[0,0,0]=np.nan
        self.fixture('TMP',values=arr)
        with self.assertRaises(dm.InvalidData): dm.normalize(self.paths,self.cfg,self.issue)

    def test_unknown_code_rejected(self):
        self.fixture('RPOS',values=np.full((4,2,2),99.0))
        with self.assertRaises(dm.InvalidData): dm.normalize(self.paths,self.cfg,self.issue)

    def test_incomplete_time_coverage_rejected(self):
        self.fixture('SKY',times=np.array(['2026-10-17T09:00'],dtype='datetime64[ns]'))
        with self.assertRaises(dm.InvalidData): dm.normalize(self.paths,self.cfg,self.issue)

    def test_crossing_quantiles_rejected(self):
        self.fixture('TMX10P',values=np.full((2,2,2),30.0))
        with self.assertRaises(dm.InvalidData): dm.normalize(self.paths,self.cfg,self.issue)

    def test_no_synthetic_daily_extrema(self):
        self.paths.pop('TMN')
        with self.assertRaises(KeyError): dm.normalize(self.paths,self.cfg,self.issue)

    def test_outside_grid_rejected(self):
        self.cfg['profile']['cities']['서울']=[35.0,125.0]
        with self.assertRaises(dm.InvalidData): dm.normalize(self.paths,self.cfg,self.issue)

    def test_shadow_active_rollback_and_correction_history(self):
        cache=self.root/'cache'; cfgpath=self.root/'config.json'; site=self.root/'site'
        first=dm.collect(self.cfg,cache,self.issue,self.root,now=self.now)
        again=dm.collect(self.cfg,cache,self.issue,self.root,now=self.now)
        self.assertEqual(first,again)
        self.fixture('TMP',values=np.full((4,2,2),21.0))
        second=dm.collect(self.cfg,cache,self.issue,self.root,now=self.now+dt.timedelta(hours=1))
        self.assertNotEqual(first,second)
        dm.write(cfgpath,self.cfg)
        self.assertEqual(dm.export(site,cfgpath,cache)['issues'],[])
        self.cfg['mode']='active';self.cfg['display_days']=10000
        dm.write(cfgpath,self.cfg)
        published=dm.export(site,cfgpath,cache)
        self.assertEqual(len(published['issues']),1)
        self.assertEqual(published['issues'][0]['cities']['서울']['hourly']['2026101718']['TMP'],21)
        self.cfg['mode']='off';dm.write(cfgpath,self.cfg)
        self.assertEqual(dm.export(site,cfgpath,cache)['issues'],[])
        self.assertEqual(len(list((cache/'revisions').glob('*.json'))),2)

    def test_profile_change_excludes_old_data(self):
        cache=self.root/'cache';dm.collect(self.cfg,cache,self.issue,self.root,now=self.now)
        self.cfg.update(mode='active',display_days=10000)
        self.cfg['profile']['id']='new-profile'
        cfgpath=self.root/'config.json';dm.write(cfgpath,self.cfg)
        self.assertEqual(dm.export(self.root/'site',cfgpath,cache)['issues'],[])

    def test_recent_success_skips_redundant_download(self):
        cache=self.root/'cache'
        dm.collect(self.cfg,cache,self.issue,self.root,now=self.now)
        with patch('digital_mid.download',side_effect=AssertionError('network')):
            result=dm.collect(self.cfg,cache,self.issue,now=self.now+dt.timedelta(hours=1))
        self.assertTrue(result.exists())

    def test_url_allowlist_blocks_untrusted_hosts(self):
        for url in ('http://example.org/a','https://evil.example/a'):
            with self.assertRaises(dm.InvalidData): dm.download(url,self.root/'bad',{'allowed_hosts':['example.org']})


if __name__=='__main__': unittest.main()
