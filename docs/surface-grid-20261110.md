# Variable maps: native fields rendered in the browser

The five surface panels (t2m, tcc, cloud3, dswrf, tp) now publish compressed
fields with `plot_charts.py --surface-grids`. The browser draws smooth filled
contours, or interpolated three-layer cloud colours. Upper-air and surface
pressure charts (`sfc`, `p925`, `p850`, `p700`, `p500`, `p300`) keep their existing
images and retention. City forecasts and verification keep their existing data.

## Data and publication

- `surface_grid.py` exports little-endian float32 arrays, north-to-south rows,
  west-to-east columns, gzip compressed. Missing values are NaN. Grid resolution
  and values are unchanged; interpolation affects display only.
- Three-layer files concatenate low, middle, high cloud arrays. Solar frames
  remain strict 3-hour means through +120h; rain records its actual interval.
- Immutable content-hashed files live under
  `grids/YYYYMMDD/model_YYYYMMDDHH/`. Each complete export writes `index.json` last.
- Only the latest successfully exported run per model is advertised. Partial
  retries of that run preserve frames already received; stale jobs cannot revert
  a newer run. Hourly publication preserves grids from restored `site-data`.
- Legacy variable images expire under existing retention, so the full storage
  saving is gradual. They are not requested after that model has a valid grid.
- The renderer, pinned D3 7.9.0 (ISC license), clipped Natural Earth 50m coastline
  and grid files are served from the same Pages origin. No new external service.
- Existing browser manifests may reference an expired run after publication;
  a 404 offers a page reload to load the latest manifest.

## Validation and measured baseline

Python tests cover native-value round trips, orientation, missing values, solar
intervals, incomplete exports, stale jobs, partial retries and upper preservation.
Node tests cover decoding, interpolation/missing values, cloud composition and
the existing app's grid/image routing. Publisher integration tests also pass.

Local matched GFS sample: run 2026-11-09 18 UTC, +12/+36/+60h, all five panels
(15 frames). Existing WebP settings: quality 78, method 6.

| Operation | Seconds | Bytes |
|---|---:|---:|
| Shared GRIB read | 0.885 | — |
| PNG rendering | 2.663 | 2,323,718 |
| PNG to WebP | 1.180 | 568,214 |
| New grid export (including index) | 0.087 | 81,226 |

Payload reduction for this sample is 85.7%. These CPU timings are local tests,
not a claim about GitHub runners or browser performance for every model.

Recent production baseline: [daily run 42737497001](https://github.com/futurist38/nwp-verify/actions/runs/42737497001),
2026-11-10, main job 32m27s excluding its 10m11s queue.

| Stage | Observed duration |
|---|---:|
| Setup and validation | 1m17s |
| Surface acquisition, decoding, images, city archive | 5m52s |
| First publication | 3m54s |
| Upper acquisition and rendering | 6m49s |
| Verification, observation and forecast cache | ~13s |
| Forecast-change API collection | ~8m19s |
| Verification maps and midrange | ~24s |
| Satellite solar | ~1m27s |
| Verification persistence | 4s |
| Second publication | 4m04s |

The surface image stage took about 2m39s including decoding. WebP conversion
also happened in both publications (678 surface frames in the first; the same
surface frames plus upper charts in the second). The migration removes those
surface image operations, but not source acquisition, upper charts, forecast
change collection or hourly nowcast inference. Initial whole-job estimate is
roughly 4–5 minutes saved, to be checked against the new `[timing]` log lines.
Pages build/deployment is separate, typically 2–4 minutes in recent successful
runs, with larger delays possible from queues or retries.

## First production publication after migration

[Run 42760431162](https://github.com/futurist38/nwp-verify/actions/runs/42760431162)
completed surface acquisition/export in **3m15s** and its first publication in
**2m59s** (6m14s combined, versus 9m46s for the baseline). Setup took 6m23s,
including an unusually long 5m25s system-package step; do not attribute that
setup delay to grid generation.

The resulting 678 frames contain 8,997,004 bytes of compressed field payloads
(plus small JSON indexes), compared with 25,798,974 bytes of previous latest
surface images. This is approximately **65% less** across all models. The 86%
matched-sample result above applies to GFS only, not all models.

| Model | Published run (UTC) | Grid | Frames | Payload bytes |
|---|---|---|---:|---:|
| ECMWF | 2026-11-09 12 | 61 × 53 | 192 | 400,115 |
| GFS | 2026-11-10 00 | 61 × 53 | 243 | 1,085,279 |
| KIM | 2026-11-09 12 | 181 × 157 | 243 | 7,511,610 |

The existing Pages tree before migration contained 782,313,966 bytes, of which
8,435 variable-map images occupied 359,408,536 bytes (45.9%). These legacy
images age out gradually under the existing seven-day retention. Upper charts
are not included in that surface-image saving. A 25–28 minute normal whole-job
estimate excludes unusual setup delays, queues and the separate Pages service;
only the first-stage timings above are measured for the migrated run so far.

The first grid publication's [Pages run 42761803329](https://github.com/futurist38/nwp-verify/actions/runs/42761803329)
finished successfully at 05:25:19 UTC, 2m08s after publication triggered it.
Production browser checks confirmed all available variable panels, common valid
times across models, forecast-step navigation, cloud legends, and unchanged
500hPa WebP charts for all three models. No native-cell display mode is exposed.
