"""Exercise the real shell publisher against local Git and a filesystem R2 double."""
import datetime as dt
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE=Path(__file__).resolve().parents[1]


class PublishSiteIntegrationTest(unittest.TestCase):
    def test_publication_precedes_remote_deletion_and_retired_runs_stay_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);repo=root/'repo';repo.mkdir();remote=root/'origin.git'
            def git(*args,env=None,input=None):
                return subprocess.check_output(['git',*args],cwd=repo,env=env,input=input,stderr=subprocess.DEVNULL).decode().strip()
            subprocess.run(['git','init','--bare',str(remote)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            git('init','-b','main');git('config','user.name','test');git('config','user.email','test@example.com')
            for p in SOURCE.glob('*.py'):shutil.copy2(p,repo/p.name)
            shutil.copytree(SOURCE/'site',repo/'site');shutil.copytree(SOURCE/'tools',repo/'tools',ignore=shutil.ignore_patterns('__pycache__'))
            (repo/'verification/obs').mkdir(parents=True)
            shutil.copy2(SOURCE/'verification/obs/stations.csv',repo/'verification/obs/stations.csv')
            # The publisher's only network metadata call is irrelevant to retention.
            (repo/'satellite_catalog.py').write_text('def export(site_dir):\n    pass\n')
            git('add','.');git('commit','-m','fixture');git('remote','add','origin',str(remote));git('push','origin','main')
            today=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
            day=(today-dt.timedelta(days=5)).strftime('%Y%m%d')
            old=f'{day}/gfs_{day}00_f024_t2m.webp';new=f'{day}/gfs_{day}12_f024_t2m.webp'
            data=f'{day}/city_upper_gfs_{day}00.json'
            seed=root/'seed';(seed/'archive'/day).mkdir(parents=True)
            for k in [old,new,data]:(seed/'archive'/k).write_bytes(b'fixture')
            idx=root/'seed-index';env=dict(os.environ,GIT_INDEX_FILE=str(idx))
            git('--work-tree='+str(seed),'add','-A',env=env)
            tree=git('write-tree',env=env);commit=git('commit-tree',tree,'-m','site fixture')
            git('push','origin',commit+':refs/heads/site-data')
            cloud=root/'cloud';shutil.copytree(seed/'archive',cloud)
            bindir=root/'bin';bindir.mkdir()
            fake=bindir/'rclone'
            fake.write_text('''#!/usr/bin/env python3
import os,sys,shutil,subprocess
from pathlib import Path
args=sys.argv[1:]; op=next(x for x in args if x in {'lsf','copy','delete'});i=args.index(op)
cloud=Path(os.environ['TEST_CLOUD'])
def keys():return [p.relative_to(cloud).as_posix() for p in cloud.rglob('*') if p.is_file()]
def selected():
    return Path(args[args.index('--files-from-raw')+1]).read_text().splitlines() if '--files-from-raw' in args else keys()
if op=='lsf':print('\\n'.join(keys()))
elif op=='copy':
    src,dst=args[i+1:i+3]
    if src.startswith('r2:'):
        for k in selected():
            out=Path(dst)/k;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(cloud/k,out)
    else:
        for p in Path(src).rglob('*'):
            if p.is_file():
                out=cloud/p.relative_to(src);out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,out)
elif op=='delete':
    old=os.environ['TEST_OLD'];new=os.environ['TEST_NEW']
    origin=os.environ['TEST_ORIGIN']
    assert subprocess.run(['git','--git-dir='+origin,'cat-file','-e','site-data:archive/'+old],stderr=subprocess.DEVNULL).returncode != 0, 'remote cleanup ran before publication'
    subprocess.run(['git','--git-dir='+origin,'cat-file','-e','site-data:archive/'+new],check=True)
    for k in selected():(cloud/k).unlink(missing_ok=True)
    Path(os.environ['TEST_MARKER']).write_text('after publish')
''')
            fake.chmod(0o755)
            marker=root/'deletion-order'
            env=dict(os.environ,PATH=str(bindir)+os.pathsep+os.environ['PATH'],
                     R2_BUCKET='test-bucket',R2_ACCOUNT_ID='test-only',R2_ACCESS_KEY_ID='test-only',R2_SECRET_ACCESS_KEY='test-only',
                     R2_PUBLIC_URL='https://example.invalid',TEST_CLOUD=str(cloud),TEST_ORIGIN=str(remote),
                     TEST_OLD=old,TEST_NEW=new,TEST_MARKER=str(marker),TZ='Asia/Seoul')
            result=subprocess.run(['bash','tools/publish_site.sh','integration test','--hourly'],cwd=repo,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
            self.assertEqual(marker.read_text(),'after publish')
            self.assertFalse((cloud/old).exists());self.assertTrue((cloud/new).exists());self.assertTrue((cloud/data).exists())
            self.assertFalse((repo/'site_build/archive'/old).exists())
            self.assertTrue((repo/'site_build/archive'/new).exists())
            self.assertTrue((repo/'site_build/archive'/data).exists())
            self.assertEqual(git('diff','--cached','--name-only'),'')
