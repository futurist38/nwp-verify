-- KPX energy report shared editing. Run once in Supabase SQL Editor.
-- Re-running preserves existing reports and edits.
begin;

create table if not exists public.energy_reports (
  day date primary key,
  report jsonb not null check (jsonb_typeof(report) = 'object'),
  updated_at timestamptz not null default now()
);
create table if not exists public.energy_edits (
  day date not null,
  page smallint not null check (page in (1, 2)),
  version bigint not null check (version > 0),
  payload jsonb not null check (jsonb_typeof(payload) = 'object' and octet_length(payload::text) <= 524288),
  updated_at timestamptz not null default now(),
  primary key (day, page)
);
create table if not exists public.energy_editors (
  user_id uuid primary key references auth.users(id) on delete cascade,
  unlocked_at timestamptz not null default now()
);
alter table public.energy_reports enable row level security;
alter table public.energy_edits enable row level security;
alter table public.energy_editors enable row level security;
revoke all on public.energy_reports, public.energy_edits, public.energy_editors from anon, authenticated;
grant select on public.energy_reports, public.energy_edits to anon, authenticated;
grant select on public.energy_editors to authenticated;
grant all on public.energy_reports, public.energy_edits, public.energy_editors to service_role;

drop policy if exists energy_reports_read on public.energy_reports;
create policy energy_reports_read on public.energy_reports for select to anon, authenticated using (true);
drop policy if exists energy_edits_read on public.energy_edits;
create policy energy_edits_read on public.energy_edits for select to anon, authenticated using (true);
drop policy if exists energy_editors_self on public.energy_editors;
create policy energy_editors_self on public.energy_editors for select to authenticated using (user_id = (select auth.uid()));

-- This is an intentional shared editing key, not a private account password.
create or replace function public.energy_unlock(p_key text)
returns boolean language plpgsql security definer set search_path = '' as $$
begin
  if auth.uid() is null or p_key is distinct from 'energy' then
    raise sqlstate 'PT403' using message = 'invalid_edit_key';
  end if;
  insert into public.energy_editors(user_id, unlocked_at) values (auth.uid(), now())
    on conflict(user_id) do update set unlocked_at = excluded.unlocked_at;
  return true;
end;
$$;

-- Version comparison is atomic, including two users creating the first edit.
-- Reset is stored as a versioned {schema:1, reset:true} payload, not a deletion.
create or replace function public.energy_save_edit(p_day date, p_page integer, p_expected_version bigint, p_payload jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_current bigint;
  v_saved public.energy_edits%rowtype;
begin
  if auth.uid() is null or not exists (
    select 1 from public.energy_editors where user_id = auth.uid() and unlocked_at > now() - interval '24 hours'
  ) then raise sqlstate 'PT403' using message = 'edit_unlock_required'; end if;
  if p_day is null or p_day < (now() at time zone 'Asia/Seoul')::date - 29
     or p_day > (now() at time zone 'Asia/Seoul')::date
     or p_page is null or p_page not in (1, 2)
     or p_expected_version is null or p_expected_version < 0
     or p_payload is null or jsonb_typeof(p_payload) <> 'object'
     or p_payload->>'schema' is distinct from '1'
     or octet_length(p_payload::text) > 524288 then
    raise sqlstate 'PT400' using message = 'invalid_edit_payload';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('energy:' || p_day::text || ':' || p_page::text, 0));
  select version into v_current from public.energy_edits where day = p_day and page = p_page;
  if coalesce(v_current, 0) <> p_expected_version then
    raise sqlstate 'PT409' using message = 'edit_conflict';
  end if;
  insert into public.energy_edits(day, page, version, payload, updated_at)
    values (p_day, p_page, coalesce(v_current, 0) + 1, p_payload, now())
    on conflict(day, page) do update set version = excluded.version, payload = excluded.payload, updated_at = excluded.updated_at
    returning * into v_saved;
  return to_jsonb(v_saved);
end;
$$;
revoke all on function public.energy_unlock(text) from public, anon;
revoke all on function public.energy_save_edit(date, integer, bigint, jsonb) from public, anon;
grant execute on function public.energy_unlock(text) to authenticated;
grant execute on function public.energy_save_edit(date, integer, bigint, jsonb) to authenticated;

-- Public report images; only unlocked editors may add new files in their own folder.
-- No browser permission to replace/delete files used by someone else's report.
insert into storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
values ('energy-images', 'energy-images', true, 2097152, array['image/png','image/jpeg','image/webp'])
on conflict(id) do update set public = excluded.public, file_size_limit = excluded.file_size_limit, allowed_mime_types = excluded.allowed_mime_types;
drop policy if exists energy_images_insert on storage.objects;
create policy energy_images_insert on storage.objects for insert to authenticated with check (
  bucket_id = 'energy-images'
  and (storage.foldername(name))[1] = (select auth.uid())::text
  and exists (select 1 from public.energy_editors where user_id = (select auth.uid()) and unlocked_at > now() - interval '24 hours')
);
notify pgrst, 'reload schema';
commit;

select 'Energy shared storage ready' as result;
