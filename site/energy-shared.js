/* Shared storage adapter. Activated by the editor only after backend setup. */
(function(root){
 'use strict';
 const URL='https://lfxajxconibunipejdjz.supabase.co';
 const KEY='sb_publishable_alSMzB50Ofl3CZCfbCNyCg_4tiju1lD';
 class SharedError extends Error{constructor(message,status){super(message);this.status=status;}}
 class EnergySharedStore{
  constructor({fetcher=root.fetch.bind(root),storage=root.localStorage,now=()=>Date.now()}={}){
   this.fetcher=fetcher;this.storage=storage;this.now=now;this.session=null;this.authPending=null;
   this.sessionKey='kpx-energy-supabase-session-v1';
   try{this.session=JSON.parse(storage.getItem(this.sessionKey));}catch{}
  }
  async request(path,{method='GET',body,token,headers={}}={}){
   const h={apikey:KEY,...headers};if(token)h.Authorization='Bearer '+token;
   if(body!==undefined&&!(body instanceof Blob)){h['Content-Type']='application/json';body=JSON.stringify(body);}
   const response=await this.fetcher(URL+path,{method,headers:h,body,cache:'no-store',signal:AbortSignal.timeout(20000)});
   const value=await response.json().catch(()=>null);
   if(!response.ok)throw new SharedError(value?.message||value?.msg||value?.error||'shared_storage_error',response.status);
   return value;
  }
  async authenticate(){
   if(this.session?.access_token&&this.session.expires_at*1000>this.now()+60000)return this.session;
   if(this.authPending)return this.authPending;
   this.authPending=(async()=>{
    let session;
    if(this.session?.refresh_token){
     // Network/server failures must not create a new anonymous identity.
     try{session=await this.request('/auth/v1/token?grant_type=refresh_token',{method:'POST',body:{refresh_token:this.session.refresh_token}});}
     catch(e){if(![400,401,403].includes(e.status))throw e;}
    }
    if(!session)session=await this.request('/auth/v1/signup',{method:'POST',body:{}});
    if(!session?.access_token||!session?.user?.id)throw new SharedError('anonymous_sign_in_unavailable',403);
    session.expires_at??=Math.floor(this.now()/1000)+(session.expires_in||3600);
    this.session=session;try{this.storage.setItem(this.sessionKey,JSON.stringify(session));}catch{}
    return session;
   })();
   try{return await this.authPending;}finally{this.authPending=null;}
  }
  day(day){if(!/^\d{8}$/.test(day))throw new SharedError('invalid_date',400);return day.slice(0,4)+'-'+day.slice(4,6)+'-'+day.slice(6);}
  async unlock(key){const s=await this.authenticate();return this.request('/rest/v1/rpc/energy_unlock',{method:'POST',token:s.access_token,body:{p_key:key}});}
  async read(day,page){
   if(![1,2].includes(page))throw new SharedError('invalid_page',400);
   const rows=await this.request('/rest/v1/energy_edits?day=eq.'+this.day(day)+'&page=eq.'+page+'&select=version,payload,updated_at');
   if(!Array.isArray(rows))throw new SharedError('invalid_response',502);
   return rows[0]||{version:0,payload:null,updated_at:null};
  }
  async save(day,page,version,payload){
   if(![1,2].includes(page)||!Number.isSafeInteger(version)||version<0||payload?.schema!==1)throw new SharedError('invalid_edit',400);
   const s=await this.authenticate();
   return this.request('/rest/v1/rpc/energy_save_edit',{method:'POST',token:s.access_token,body:{p_day:this.day(day),p_page:page,p_expected_version:version,p_payload:payload}});
  }
  async upload(day,blob){
   this.day(day);const ext={'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}[blob.type];
   if(!ext||!blob.size||blob.size>2097152)throw new SharedError('image_type_or_size',400);
   const s=await this.authenticate(),hash=await root.crypto.subtle.digest('SHA-256',await blob.arrayBuffer());
   const hex=Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,'0')).join('');
   const path=s.user.id+'/'+day+'/'+hex+'.'+ext;
   try{await this.request('/storage/v1/object/energy-images/'+path,{method:'POST',token:s.access_token,body:blob,headers:{'Content-Type':blob.type,'x-upsert':'false','cache-control':'max-age=31536000'}});}
   catch(e){if(!([400,409].includes(e.status)&&/already exists|Duplicate/i.test(e.message)))throw e;}
   return URL+'/storage/v1/object/public/energy-images/'+path;
  }
 }
 root.EnergySharedStore=EnergySharedStore;
 if(typeof module!=='undefined')module.exports={EnergySharedStore,SharedError};
})(globalThis);
