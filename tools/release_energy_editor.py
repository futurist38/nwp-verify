"""Stage and publish the approved editor, preserving unrelated site-data files."""
import base64,json,os,shutil,subprocess,sys,tempfile,zipfile
from pathlib import Path
ROOT=Path.cwd();STAGE=ROOT/'energy_editor_stage';STATE=ROOT/'energy_editor_release_state.json'
FRONT=['energy-weather.html','energy-weather.js','energy-editor.css','inline-edit.js']
def git(*args,**kwargs):return subprocess.check_output(['git',*args],**kwargs)
def ref():
 git('fetch','--depth=1','origin','site-data');return git('rev-parse','FETCH_HEAD').decode().strip()
def prepare():
 base=ref();shutil.rmtree(STAGE,ignore_errors=True);STAGE.mkdir()
 manifest=json.loads(git('show',base+':energy/index.json'));guards={};files=[]
 assets=ROOT/'energy_runtime/energy_assets'
 if not assets.exists():
  with zipfile.ZipFile(ROOT/'energy_runtime/energy_assets.zip') as z:z.extractall(assets)
 for date in manifest['dates']:
  if len(date)!=8 or not date.isdigit():raise ValueError('Invalid date')
  prefix='energy/'+date+'/';dest=STAGE/prefix;dest.mkdir(parents=True)
  for name in ['report.json','editor.json']:
   key=prefix+name;raw=git('show',base+':'+key);(dest/name).write_bytes(raw);guards[key]=git('rev-parse',base+':'+key).decode().strip()
  report=json.loads((dest/'report.json').read_text());assert len(report['forecast'])==9
  for panel in json.loads((dest/'editor.json').read_text()).get('panels',[]):
   if panel.get('src') and panel['id'] in ['radar','satellite']:(dest/(panel['id']+'.png')).write_bytes(base64.b64decode(panel['src'].split(',',1)[1]))
  subprocess.run([sys.executable,'energy_runtime/energy_render.py',str(dest/'report.json'),str(dest)],check=True)
  for name in ['editor.json','editor2.json','background.webp','background2.webp','01.webp','02.webp']:files.append(prefix+name)
 for name in FRONT:shutil.copy2(ROOT/'site'/name,STAGE/name);files.append(name)
 (STAGE/'energy/index.json').write_text(json.dumps(manifest));STATE.write_text(json.dumps({'guards':guards,'files':files}))
 print('Prepared',len(manifest['dates']),'reports and editor files')
def publish():
 state=json.loads(STATE.read_text());base=ref()
 for path,sha in state['guards'].items():
  if git('rev-parse',base+':'+path).decode().strip()!=sha:
   print('Report changed while validating; rebuild before publish');return 2
 with tempfile.TemporaryDirectory() as td:
  env=dict(os.environ,GIT_INDEX_FILE=td+'/index');git('read-tree',base,env=env)
  for path in state['files']:
   sha=git('hash-object','-w',str(STAGE/path)).decode().strip();git('update-index','--add','--cacheinfo','100644',sha,path,env=env)
  manifest=json.loads((STAGE/'energy/index.json').read_text());manifest['updated_kst']=__import__('datetime').datetime.now(__import__('zoneinfo').ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds')
  sha=git('hash-object','-w','--stdin',input=json.dumps(manifest).encode()).decode().strip();git('update-index','--add','--cacheinfo','100644',sha,'energy/index.json',env=env)
  tree=git('write-tree',env=env).decode().strip();commit=git('commit-tree',tree,'-m','Publish approved energy editor with inline text and four colors').decode().strip()
  result=subprocess.run(['git','push',f'--force-with-lease=refs/heads/site-data:{base}','origin',commit+':refs/heads/site-data'])
  if result.returncode:return 2
  print('Published',commit);return 0
if __name__=='__main__':
 if sys.argv[1]=='prepare':prepare()
 else:raise SystemExit(publish())
