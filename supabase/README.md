# Energy report shared storage setup

Status: backend setup and connection adapter prepared; not activated in the live editor yet.

1. Open this project's Supabase **SQL Editor**, create a new query, paste all of `setup_energy.sql`, and click **Run**. Success ends with `Energy shared storage ready`. Re-running this script preserves saved reports and edits. It only creates/updates the named energy tables, functions, bucket and policies.
2. In **Authentication**, find the **Anonymous Sign-Ins** provider under sign-in providers/settings and enable it. Visitors will not see a login form; an anonymous identity is created only when they enter editing mode. The `energy` key is an intentional shared editing gate, not a strong secret.
3. Next integration stage: enable the adapter in the existing editor, migrate local edits explicitly, add version-conflict handling and validate two independent browser sessions before publishing. Current local edits and production editor are unchanged by this setup.
4. Daily integration stage: put a server-only Supabase secret in the repository's GitHub Actions secrets (never in chat or the website), then extend the existing daily workflow to upsert `energy_reports`, verify the result and prune expired data/images. Daily generation must never write `energy_edits`. If cloud sync fails, continue showing the GitHub-generated baseline and clearly indicate cloud status.

## Storage contract

- `energy_reports`: date-keyed generated metadata; service-role writes only.
- `energy_edits`: one versioned JSON payload per date/page. Everyone may read; browser writes use `energy_save_edit` after `energy_unlock`.
- `energy_editors`: anonymous identities unlocked for 24 hours; clients can only read their own row. No browser direct writes.
- `energy-images`: public raster images, maximum 2 MiB each. Unlocked users may insert in their own identity folder. No browser overwrite/delete rights. Image paths include report date and a content hash. Pending daily maintenance will remove objects older than retained reports; do not activate uploads until maintenance is connected.
- Save compares `p_expected_version` atomically. HTTP 409 means a newer edit exists; never auto-overwrite it. Reset is a new version with `{ "schema": 1, "reset": true }`.
- JSON limit 512 KiB; images go to Storage, not base64 inside edit JSON. Client integration must validate/allowlist payload fields and image sources before rendering.

The public URL and publishable key in `site/energy-shared.js` are intended for browser use. No privileged key is included.
