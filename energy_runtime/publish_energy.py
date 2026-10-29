"""Update only energy/* in site-data, with optimistic locking and 30-day expiry."""
import datetime as dt, json, os, subprocess, tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

def git(*args,env=None,input=None):
    return subprocess.check_output(['git',*args],env=env,input=input,text=True).strip()

def main():
    now=dt.datetime.now(ZoneInfo('Asia/Seoul'));cutoff=(now.date()-dt.timedelta(days=29)).strftime('%Y%m%d')
    root=Path.cwd();incoming=root/'energy_generated'
    for attempt in range(5):
        git('fetch','--depth=1','origin','site-data');base=git('rev-parse','FETCH_HEAD')
        with tempfile.TemporaryDirectory() as td:
            env=dict(os.environ,GIT_INDEX_FILE=td+'/index')
            git('read-tree',base,env=env)
            paths=git('ls-tree','-r','--name-only',base,'energy').splitlines()
            dates={p.split('/')[1] for p in paths if len(p.split('/'))>2 and p.split('/')[1].isdigit()}
            for p in paths:
                bits=p.split('/')
                if len(bits)>2 and len(bits[1])==8 and bits[1].isdigit() and bits[1]<cutoff:
                    git('update-index','--force-remove',p,env=env)
            for folder in incoming.iterdir():
                if not folder.is_dir() or not folder.name.isdigit():continue
                report=json.loads((folder/'report.json').read_text())
                try:old=json.loads(git('show',base+':energy/'+folder.name+'/report.json'))
                except subprocess.CalledProcessError:old={}
                # Preserve a later approved/manual report for the same day.
                if old.get('publication_kst','')>report['publication_kst']:
                    print('Preserved later publication:',folder.name);continue
                for p in folder.iterdir():
                    if not p.is_file():continue
                    sha=git('hash-object','-w',str(p))
                    git('update-index','--add','--cacheinfo','100644',sha,'energy/'+folder.name+'/'+p.name,env=env)
                dates.add(folder.name)
            manifest={'dates':sorted((d for d in dates if cutoff<=d<=now.strftime('%Y%m%d')),reverse=True),'retention_days':30,'target_time_kst':'07:00','automatic_generation':True,'status':'enabled','updated_kst':now.isoformat(timespec='seconds')}
            sha=git('hash-object','-w','--stdin',input=json.dumps(manifest,ensure_ascii=False))
            git('update-index','--add','--cacheinfo','100644',sha,'energy/index.json',env=env)
            tree=git('write-tree',env=env)
            # site-data is an orphan snapshot branch to avoid retaining deleted large images in history.
            commit=git('commit-tree',tree,'-m','Energy weather '+now.strftime('%Y-%m-%d %H:%M KST'))
            result=subprocess.run(['git','push',f'--force-with-lease=refs/heads/site-data:{base}','origin',commit+':refs/heads/site-data'])
            if result.returncode==0:return
    raise SystemExit('Concurrent publication conflict; no changes published')

if __name__=='__main__':main()
