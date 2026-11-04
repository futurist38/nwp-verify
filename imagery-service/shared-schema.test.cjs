// NODE_PATH=/path/to/pglite/node_modules node --test imagery-service/shared-schema.test.cjs
const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');
const {PGlite}=require('@electric-sql/pglite');
test('schema preserves edits on re-run and enforces unlock, version conflicts and image permissions',async()=>{
 const db=new PGlite();
 try{
  await db.exec(`
   create role anon; create role authenticated; create role service_role bypassrls;
   create schema auth; create schema storage;
   create table auth.users(id uuid primary key);
   insert into auth.users values ('11111111-1111-4111-8111-111111111111'), ('22222222-2222-4222-8222-222222222222');
   create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.user_id',true),'')::uuid$$;
   create table storage.buckets(id text primary key,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);
   create table storage.objects(id bigint generated always as identity,bucket_id text,name text);
   create function storage.foldername(name text) returns text[] language sql immutable as $$select string_to_array(name,'/')$$;
   alter table storage.objects enable row level security;
   grant usage on schema public, auth, storage to anon,authenticated,service_role;
   grant insert on storage.objects to authenticated;
  `);
  const sql=fs.readFileSync(__dirname+'/../supabase/setup_energy.sql','utf8');await db.exec(sql);
  await db.exec('set role anon');assert.equal((await db.query('select * from public.energy_edits')).rows.length,0);
  await assert.rejects(db.query("select public.energy_unlock('energy')"),/permission denied/);
  await db.exec("set role authenticated; set request.user_id='11111111-1111-4111-8111-111111111111'");
  await assert.rejects(db.query("select public.energy_unlock('wrong')"),/invalid_edit_key/);
  const save="select public.energy_save_edit((now() at time zone 'Asia/Seoul')::date, 1, $1, '{\"schema\":1,\"reset\":true}') as saved";
  await assert.rejects(db.query(save,[0]),/edit_unlock_required/);
  await db.query("select public.energy_unlock('energy')");
  assert.equal((await db.query(save,[0])).rows[0].saved.version,1);
  await assert.rejects(db.query(save,[0]),/edit_conflict/);
  await assert.rejects(db.query("update public.energy_edits set version=999"),/permission denied/);
  await db.query("insert into storage.objects(bucket_id,name) values ('energy-images','11111111-1111-4111-8111-111111111111/20261104/image.png')");
  await assert.rejects(db.query("insert into storage.objects(bucket_id,name) values ('energy-images','22222222-2222-4222-8222-222222222222/20261104/image.png')"),/row-level security/);
  await db.exec("set request.user_id='22222222-2222-4222-8222-222222222222'");
  assert.equal((await db.query('select * from public.energy_editors')).rows.length,0);
  await db.query("select public.energy_unlock('energy')");
  await assert.rejects(db.query(save,[0]),/edit_conflict/);
  assert.equal((await db.query(save,[1])).rows[0].saved.version,2);
  await db.exec('reset role');await db.exec(sql);
  assert.equal((await db.query('select version from public.energy_edits')).rows[0].version,2);
 }finally{await db.close();}
});
