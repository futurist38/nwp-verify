# Energy image time lookup

Prepared, not deployed. The existing report and saved thumbnails work before this function is deployed; time lookup reports that the connection is pending on HTTP 404. Publishing frontend code alone does not deploy the Supabase function.

Deploy `supabase/functions/energy-imagery/index.ts` as **energy-imagery** in project `lfxajxconibunipejdjz`. The dashboard editor accepts this single file. Use its code-based authorization (`verify_jwt = false` in config.toml): every request forwards the caller's user JWT to the existing RLS-protected `energy_editors` table and requires an unlock within 24 hours. No additional secret, database schema or storage policy is required. Alternatively, the authenticated Supabase CLI can run `supabase functions deploy energy-imagery --project-ref lfxajxconibunipejdjz` from the repository.

The existing publishable/anonymous key and project URL are supplied by Supabase. No KMA API key or service-role key is used by this function. Never send a publishable key as a Bearer token; the browser sends its signed-in user JWT.

After deployment, open the actual energy editor, unlock it, and load an available past time for all four sources using the one shared KST input. Confirm actual times, apply a thumbnail, undo, share-save/reload, and export PNG before considering the feature live. If the Supabase region cannot fetch KMA, existing images remain untouched and the UI reports failure.

## Data semantics

- Satellite: RGB day/night, 2-minute frames. `row.tm` is KST; the PNG filename is UTC. Exact rounded frame required.
- Radar: KMA public HSR layer, 5-minute frames. The client composites a same-origin static coastline and the official mm/h color scale; no blank-map layer is applied alone. The coastline uses Natural Earth public-domain 1:50m data projected to KMA's published SFC-HSR grid corners, with alignment checked at all four corners. Rebuild with `tools/build_energy_radar_map.py` (`requests`, `pyshp`).
- Warnings: latest bulletin issued at or before the requested time. Issuance is labeled **발표**; effective times are shown separately. The bulletin graphic may describe a later effective time; it is not a reconstructed minute-by-minute warning status. No preliminary bulletin substitution.
- PM10: KMA dust-station **hourly mean**, not PM2.5 or an AirKorea interpolated field. Uses the selected hour in the historical daily table. Midnight is the previous date's 24-hour column. Missing values remain missing; an entirely missing hour fails.
- Inputs are KST, at most 30 days old and never in the future. Availability depends on upstream retention. Non-aligned minutes round down to the source interval and actual time is displayed. No substitution with a newer/latest image.

Requests use fixed public hosts/products, bounded body/image sizes, deadlines, a bounded short cache and per-isolate request limits. These limits are not a global quota. Retrieval only changes the source thumbnail; applying it is a separate click and produces one undo entry. Old requests cannot mutate another report date.

Validation: `node --test imagery-service/source-times.test.mjs imagery-service/editor.test.cjs imagery-service/shared-store.test.cjs`; `python -m unittest discover -s tests -p test_energy_sources.py`.
