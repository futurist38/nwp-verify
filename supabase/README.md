# Energy report shared storage setup

Status: shared editing and daily sync are connected. Browser tests and live Supabase checks run before editor publication.

1. Open this project's Supabase **SQL Editor**, create a new query, paste all of `setup_energy.sql`, and click **Run**. Success ends with `Energy shared storage ready`. Re-running this script preserves saved reports and edits. It only creates/updates the named energy tables, functions, bucket and policies.
2. In **Authentication**, find the **Anonymous Sign-Ins** provider under sign-in providers/settings and enable it. Visitors will not see a login form; an anonymous identity is created only when they enter editing mode. The `energy` key is an intentional shared editing gate, not a strong secret.
3. Enter editing mode with the shared key `energy`. Use `공유 저장` to save this page for everyone. Existing local edits are available through `이 브라우저 저장본 불러오기`. Stale saves are rejected; use `공유본 다시 불러오기` to review changes. Reset the page and then share-save to reset the shared version.
4. The daily workflow uses GitHub Actions secret `SUPABASE_SECRET_KEY` to run `tools/sync_energy_supabase.py` after publication. It upserts and verifies generated metadata and removes expired records/images. Retained manual edits are never overwritten. Failure marks the workflow failed while the already published GitHub report remains available.

## Storage contract

- `energy_reports`: date-keyed generated metadata; service-role writes only.
- `energy_edits`: one versioned JSON payload per date/page. Everyone may read; browser writes use `energy_save_edit` after `energy_unlock`.
- `energy_editors`: anonymous identities unlocked for 24 hours; clients can only read their own row. No browser direct writes.
- `energy-images`: public raster images, maximum 2 MiB each. Unlocked users may insert in their own identity folder. No browser overwrite/delete rights. Image paths include report date and a content hash. Daily maintenance removes objects older than the 30-day retention cutoff.
- Save compares `p_expected_version` atomically. HTTP 409 means a newer edit exists; never auto-overwrite it. Reset is a new version with `{ "schema": 1, "reset": true }`.
- JSON limit 512 KiB; images go to Storage, not base64 inside edit JSON. Client integration must validate/allowlist payload fields and image sources before rendering.

The public URL and publishable key in `site/energy-shared.js` are intended for browser use. No privileged key is included.
