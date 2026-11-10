import csv
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from tools.persist_verification import merge_file, persist


def rows(data):
    return list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))


class PersistenceTests(unittest.TestCase):
    def test_concurrent_rows_and_corrections_keep_remote_updates(self):
        base=b'TM,STN,TA\n2026-11-10 01:00:00,108,10\n'
        local=base+b'2026-11-10 02:00:00,108,12\n'
        remote=b'TM,STN,TA\n2026-11-10 01:00:00,108,11\n2026-11-10 03:00:00,108,13\n'
        got=rows(merge_file('verification/obs/2026-11.csv',base,local,remote))
        self.assertEqual([r['TA'] for r in got],['11','12','13'])
        self.assertEqual(len(got),3)

    def test_timestamp_keys_normalize_and_score_rows_stay_coherent(self):
        base=b'issue_utc,lead_min,method,mae\n2026-11-10,60,M4,2\n'
        local=b'issue_utc,lead_min,method,mae\n2026-11-10 00:00:00,60,M4,3\n'
        remote=b'issue_utc,lead_min,method,mae\n2026-11-10 00:00:00,60,M4,4\n'
        got=rows(merge_file('verification/nowcast/2026-11.csv',base,local,remote))
        self.assertEqual(len(got),1);self.assertEqual(got[0]['mae'],'4')
        path='verification/scores/2026-11.csv'
        header=b'valid_kst,city,model,run_utc,var,fcst,obs,err\n'
        common=b'2026-11-10 12:00:00,Seoul,GFS,2026-11-10,t2m,'
        got=rows(merge_file(path, header+common+b'10,,\n',header+common+b'11,9,2\n',header+common+b'12,10,2\n'))
        self.assertEqual([got[0][k] for k in ['fcst','obs','err']],['12','10','2'])

    def test_json_merge_keeps_both_city_additions_and_remote_correction(self):
        encode=lambda obj:json.dumps(obj).encode()
        got=json.loads(merge_file('verification/kmafcst/day.json',encode({'issue':{'Seoul':1}}),
            encode({'issue':{'Seoul':1,'Wonju':0}}),encode({'issue':{'Seoul':2,'Busan':4}})))
        self.assertEqual(got,{'issue':{'Seoul':2,'Wonju':0,'Busan':4}})

    def test_remote_json_removal_and_local_addition_are_serializable(self):
        encode=lambda obj:json.dumps(obj).encode()
        got=json.loads(merge_file('verification/kmafcst/day.json', encode({'old':1,'shared':2}),
            encode({'old':1,'shared':2,'new':0}), encode({'shared':3})))
        self.assertEqual(got,{'shared':3,'new':0})

    def test_real_git_push_retries_with_concurrent_data_without_touching_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);remote=root/'remote.git';local=root/'local';other=root/'other'
            def run(*args,cwd=root):
                return subprocess.check_output(['git',*args],cwd=cwd,stderr=subprocess.DEVNULL)
            run('init','--bare',str(remote));run('clone',str(remote),str(local))
            run('checkout','-b','main',cwd=local)
            for repo in [local]:
                run('config','user.name','test',cwd=repo);run('config','user.email','test@example.com',cwd=repo)
            (local/'verification/obs').mkdir(parents=True)
            path=local/'verification/obs/month.csv';path.write_text('TM,STN,TA\n2026-11-10 01:00:00,108,10\n')
            run('add','.',cwd=local);run('commit','-m','base',cwd=local);run('push','origin','main',cwd=local)
            run('clone','-b','main',str(remote),str(other))
            run('config','user.name','other',cwd=other);run('config','user.email','other@example.com',cwd=other)
            path.write_text(path.read_text()+'2026-11-10 02:00:00,108,12\n')
            (local/'unrelated.txt').write_text('keep me')
            original=path.read_bytes();head=run('rev-parse','HEAD',cwd=local)
            import tools.persist_verification as module
            real_git=module.git; raced=False
            def racing_git(*args,**kwargs):
                nonlocal raced
                if args[0]=='push' and not raced:
                    raced=True
                    p=other/'verification/obs/month.csv';p.write_text(p.read_text()+'2026-11-10 03:00:00,108,13\n')
                    run('add','.',cwd=other);run('commit','-m','concurrent',cwd=other);run('push','origin','main',cwd=other)
                return real_git(*args,**kwargs)
            prev=Path.cwd()
            try:
                os.chdir(local)
                with patch.object(module,'git',side_effect=racing_git),patch.object(module.time,'sleep'):
                    persist(['verification/obs'],'test save')
                self.assertEqual(path.read_bytes(),original)
                self.assertEqual(run('rev-parse','HEAD',cwd=local),head)
                self.assertEqual((local/'unrelated.txt').read_text(),'keep me')
                saved=run('--git-dir='+str(remote),'show','main:verification/obs/month.csv')
                self.assertEqual([r['TA'] for r in rows(saved)],['10','12','13'])
            finally:
                os.chdir(prev)
