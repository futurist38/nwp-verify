# Operational recovery and model-image retention — 2026-11-10

- Wonju export fixtures freeze their calendar at 2026-10-26. The hourly validation
  job reports failures independently; observations do not depend on that job.
- Ordinary model images, including SFC, use KST archive calendar dates. Today is
  day 1: days 1–5 retain all runs; days 6–7 retain the latest run per date/model;
  day 8 onward is removed. Pressure-level maps keep the existing retention and
  variable definitions. Nowcast (7 days) and energy reports (30 days) are unchanged.
- `model_image_retention.py` is the common selection rule for local cleanup, R2
  restore plans and manifest filtering. R2 deletion failure cannot reintroduce
  a removed ordinary run. `tools/site_storage.py` writes exact image-key lists;
  numerical JSON/CSV is not a deletion target. The chart selector lists only runs
  containing the chosen panel, so preserved upper runs remain accessible.
- Publishing starts with a clean generated staging directory on each lease retry.
  Storage logs report total site, archive and nowcast bytes before and after.
- `tools/persist_verification.py` uses a separate Git index and a fast-forward
  commit on current main. Concurrent CSV updates merge by observation/forecast/
  score keys; JSON objects merge by key. Unchanged stale values cannot overwrite
  remote updates. True conflicting CSV rows stay coherent (more complete row,
  then remote wins ties). Concurrent binary/derived-file conflicts retain remote.
  The runner checkout is never rebased, reset or stashed. Failed pushes fetch and
  merge again, with a visible failure after six attempts. Daily publication still
  runs after a persistence error, and the error is then reported as job failure.
- WebP quality remains 82/method 4 pending direct PNG evaluation. The daily push
  run produces `webp-original-png-comparison`: ECMWF/GFS/KIM × SFC/500 hPa/T2M/
  DSR/TCC, q82/m4, q82/m6, q78/m6, original-referenced SSIM, times and native-pixel
  crops. Existing lossy WebP images are not recompressed.

Local validation: 63 Python tests + 51 JavaScript tests passed. New cases cover
KST date boundaries, independent model runs, stale R2 listings, numerical-data
preservation, panel-specific selection, timestamp key normalization and a real
Git push race preserving both writers' rows and the original working tree.
