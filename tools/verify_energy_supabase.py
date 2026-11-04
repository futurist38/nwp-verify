"""Integration smoke test using a baseline-only reset and conditional cleanup."""
import base64, datetime as dt, os, urllib.error, hashlib
from sync_energy_supabase import Cloud, URL
from zoneinfo import ZoneInfo
KEY='sb_publishable_alSMzB50Ofl3CZCfbCNyCg_4tiju1lD'
def main():
 import urllib.request,json
 admin=Cloud(os.environ['SUPABASE_SECRET_KEY']);public=Cloud(KEY)
 session=public.request('/auth/v1/signup','POST',{})
 user=Cloud(KEY);user.headers['Authorization']='Bearer '+session['access_token']
 uid=session['user']['id'];day=(dt.datetime.now(ZoneInfo('Asia/Seoul')).date()-dt.timedelta(days=28)).isoformat();created=False; image_path=None
 try:
  assert user.request('/rest/v1/rpc/energy_unlock','POST',{'p_key':'energy'}) is True
  png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aF1kAAAAASUVORK5CYII=')
  image_path=uid+'/'+day.replace('-','')+'/'+hashlib.sha256(png).hexdigest()+'.png'
  req=urllib.request.Request(URL+'/storage/v1/object/energy-images/'+image_path,data=png,method='POST',headers={**user.headers,'Content-Type':'image/png','x-upsert':'false'})
  with urllib.request.urlopen(req,timeout=30) as response: assert response.status==200
  with urllib.request.urlopen(URL+'/storage/v1/object/public/energy-images/'+image_path,timeout=30) as response: assert response.read()==png
  rows=public.request('/rest/v1/energy_edits?day=eq.'+day+'&page=eq.2&select=version')
  if not rows:
   row=user.request('/rest/v1/rpc/energy_save_edit','POST',{'p_day':day,'p_page':2,'p_expected_version':0,'p_payload':{'schema':1,'reset':True}});created=True
   assert row['version']==1
   assert public.request('/rest/v1/energy_edits?day=eq.'+day+'&page=eq.2&select=payload')[0]['payload']=={'schema':1,'reset':True}
   try:user.request('/rest/v1/rpc/energy_save_edit','POST',{'p_day':day,'p_page':2,'p_expected_version':0,'p_payload':{'schema':1,'reset':True}})
   except RuntimeError as e:assert '409' in str(e)
   else:raise AssertionError('Concurrent overwrite was accepted')
  print('Live Supabase: anonymous unlock, image upload/public read verified; baseline-only save/conflict checked when test slot was empty')
 finally:
  if image_path:admin.request('/storage/v1/object/energy-images','DELETE',{'prefixes':[image_path]})
  if created:admin.request('/rest/v1/energy_edits?day=eq.'+day+'&page=eq.2&version=eq.1','DELETE')
  admin.request('/auth/v1/admin/users/'+uid,'DELETE')
if __name__=='__main__':main()
