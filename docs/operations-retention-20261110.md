# Operational recovery and model-image retention — 2026-11-10

- Wonju export fixtures freeze their calendar at 2026-10-26. The hourly validation
  job reports failures independently; observations do not depend on that job.
  Code pushes supersede older hourly and daily runs; normal scheduled/dispatch
  runs queue. This also prevents an old publisher from reverting newer UI assets.
- Ordinary model images, including SFC, use KST archive calendar dates. Today is
  day 1: days 1–5 retain all runs; days 6–7 retain the latest run per date/model;
  day 8 onward is removed. Pressure-level maps keep the existing retention and
  variable definitions. Nowcast (7 days) and energy reports (30 days) are unchanged.
- `model_image_retention.py` is the common selection rule for local cleanup, R2
  restore plans and manifest filtering. R2 deletion failure cannot reintroduce
  a removed ordinary run. `tools/site_storage.py` writes exact image-key lists;
  numerical JSON/CSV is not a deletion target. The chart selector lists only runs
  containing the chosen panel, so preserved upper runs remain accessible.
- R2 commands have a five-minute ceiling, a 60-second I/O timeout and two retries.
  Obsolete keys are excluded immediately, but physical deletion follows successful
  site-data publication (32 checkers), so cleanup does not delay fresh Pages data.
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
- New model PNG images use WebP quality 78/method 6 after direct PNG review.
  Existing WebP images are never recompressed; non-model images keep 82/4.
  Conversion writes a temporary file and replaces the WebP only on success.
  The original PNG and previous WebP survive an encoder failure.

## Measured production outcome

The successful hourly run [42732567823](https://github.com/futurist38/nwp-verify/actions/runs/42732567823)
removed 2,192 ordinary model images, totaling 110,391,898 bytes. Tree comparison
found no unexpected removals, upper-image removals or numerical-file removals.
R2 restoration did not reintroduce any retired image.

| Measurement | Before | After |
| --- | ---: | ---: |
| Archive image/data directory | 764,312,414 B | 653,920,516 B |
| Whole published directory | 863,670,559 B | 753,188,890 B |
| Pages compressed artifact | 806,818,913 B | 696,274,360 B |
| Pages build job | 90 s | 87 s |
| Pages deployment job | 29 s | 74 s |

Both Pages deployments succeeded. Service/queue variation means the smaller
artifact did not shorten end-to-end deployment in this pair of runs.
Before: [42732567248](https://github.com/futurist38/nwp-verify/actions/runs/42732567248).
After: [42734060499](https://github.com/futurist38/nwp-verify/actions/runs/42734060499).
The whole-directory difference also includes ordinary observation updates.
These byte values precede the new encoder setting; do not attribute the measured
110.4 MB removal to WebP compression or claim an immediate 570 MB archive.

## Direct PNG compression evidence

The production collectors/renderers generated 15 original PNG maps: ECMWF/GFS/KIM
by SFC/500 hPa/T2M/DSR/TCC. [Run 42733841345](https://github.com/futurist38/nwp-verify/actions/runs/42733841345)
saved original PNGs, each WebP candidate and native-pixel readability crops.
Results are retained in `webp-original-benchmark-20261110.json`; the reproducible
collector/workflow is on `analysis/webp-original-20261110`.

| Setting | Total bytes | Saving vs 82/4 | Mean SSIM vs original PNG |
| --- | ---: | ---: | ---: |
| 82/4 | 988,234 | — | 0.973534 |
| 82/6 | 971,736 | 1.67% | 0.973260 |
| 78/6 | 878,504 | 11.10% | 0.970299 |

The inspected contour labels, wind barbs, titles and legends remained readable
at native size at 78/6, with minor smoothing around line/color boundaries.
This is a limited model/time sample, not an assurance of identical pixels.
The +24 h sample has nighttime DSR. A second [daytime +12 h run 42734722198](https://github.com/futurist38/nwp-verify/actions/runs/42734722198)
added another 15 PNGs: 82/4 used 1,042,518 B, 78/6 used 924,112 B (11.36%
saving), with mean PNG SSIM 0.969012 and 0.965680 respectively. Native-pixel
DSR crops from all three models retained readable coastlines/legends and the
solar shading pattern. Combined 30-image byte saving is 11.23%.
Savings enter production gradually as newly rendered PNGs replace older images.

Local validation: 67 Python tests + 51 JavaScript tests passed. New cases cover
KST date boundaries, independent model runs, stale R2 listings, numerical-data
preservation, panel-specific selection, timestamp key normalization, a real
Git push race preserving both writers' rows and the original working tree,
PNG conversion failure recovery and a real shell publication proving physical
R2 deletion follows the successful Git publication.

## Final rollout checks

- Final code: `3c541406526a27c1091c9b3294ed77364f4697cb`.
- [Hourly run 42735202834](https://github.com/futurist38/nwp-verify/actions/runs/42735202834): all jobs succeeded; 10:00 KST observations present;
  22,004 monthly ASOS rows saved. Verification persistence saved two files on
  main in one attempt (`5fc3bd84`). The R2 plan found zero remaining obsolete
  keys, and none of the 2,192 retired ordinary maps reappeared.
- [Pages 42736056555](https://github.com/futurist38/nwp-verify/actions/runs/42736056555): success after the final hourly publisher.
- The first NWP publication on `783b0f042f2b2bbbf0fe97debd705165cb4b9687`
  replaced 678 regenerated model images: 29,087,804 B → 25,798,974 B, an 11.31%
  reduction. All 678 kept the same paths; no other archive file was removed or
  added in that comparison. Total archive after these additional model data
  and new encodings was 660,625,774 B. This differs from the retention-only
  baseline above because the ordinary pipeline also brought in 243 additional
  model images between measurements.
- Browser checks: Nov 4 ordinary panels offered one run per model; Nov 6 kept
  multiple runs. All three models loaded at 925/850/700/500/300 hPa.
