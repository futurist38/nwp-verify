"""Read-only original PNG samples, using production collectors/renderers.
No verification persistence, R2 operations or site publication.
"""
import datetime as dt
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fetch_ecmwf as ec
import fetch_gfs as gf
import fetch_kim_nc as km
import fetch_upper as up
import plot_charts as charts
import plot_upper as upper
from config import DATA_DIR, OUT_DIR
from unittest.mock import patch

steps=[0,9,12]  # daytime +12h DSR and preceding accumulation interval
Path(DATA_DIR).mkdir(parents=True,exist_ok=True)
paths={}
with patch.object(ec,'ECMWF_STEPS',steps):
    paths['ECMWF']=ec.fetch(workers=3)
with patch.object(gf,'model_steps',lambda *a,**kw:steps):
    paths['GFS']=gf.fetch()
with patch.object(km,'model_steps',lambda *a,**kw:steps),patch.object(km,'KIM_STEPS',steps),patch('sys.argv',['fetch_kim_nc.py','--max-minutes','3']):
    km.main()
paths['KIM']=str(sorted(Path(DATA_DIR).glob('kim_*.npz'))[-1])
folder=Path(OUT_DIR)/dt.date.today().strftime('%Y%m%d')
for model,load in [('ECMWF',charts.load_ecmwf),('GFS',charts.load_gfs),('KIM',charts.load_kim)]:
    data=load(paths[model])
    with patch.object(charts,'map_steps',lambda *a:[12]):
        charts.plot_maps(model,data,str(folder/('maps_'+model.lower())),panels={'t2m','tcc','dswrf'})
with patch.object(up,'STEPS',[12]),patch.object(up,'LEVELS',[850,500]),patch.object(up,'SFC_END',{'ECMWF':12,'GFS':12}):
    up.fetch_ecmwf('ecmwf',workers=3)
    up.fetch_gfs()
with patch.object(km,'UPPER_STEPS',[12]),patch.object(km,'UPPER_VARS',{500:km.UPPER_VARS[500]}),patch.object(km,'_sfc_steps',lambda *a:[12]),patch('sys.argv',['fetch_kim_nc.py','--upper','--max-minutes','3']):
    km.main()
with patch('sys.argv',['plot_upper.py']),patch.object(upper,'LEVELS',[500]):
    upper.main()
