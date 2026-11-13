# Limitations (current)

- Detections are satellite hotspot records, not fires, burned area or fire danger. Agricultural burning and other heat sources are included.
- Nothing has been run against real NASA FIRMS data or the live API. All numbers in the shipped demo are SYNTHETIC.
- Harmonisation: a calendar-month VIIRS/MODIS ratio (engineering choice, not a published standard). An area-specific ratio is used only when the selection has
  >= 36 usable overlap months; otherwise the regional ratio is applied and this is stated. Small areas give unstable ratios.
- Terra+Aqua are pooled for the ratio; platform counts are preserved for display. VIIRS = S-NPP only unless EXTRA_SOURCES is configured with verified FIRMS source names.
- Coverage is taken from download windows or a user-written coverage.json, not from FIRMS observation-opportunity data. Without evidence, empty months are INSUFFICIENT_EVIDENCE.
- Anomaly baseline = same calendar month in all other years of the processed record (not past-only); needs >= 10 years and non-zero MAD.
- Geometry: antimeridian-crossing shapes are rejected; holes are checked only by vertex containment; shapes above 3000 vertices are rejected.
- The processing region is one bounding box (config.BBOX). Other regions need a re-run with a different BBOX; shapes outside it return empty or unobserved results.
- The web page was verified headlessly (jsdom with stubbed map/chart libraries), not in a real browser; map visuals are unverified.

## Sensor Intelligence (Stage 5) limits
- Everything shipped was exercised only on SYNTHETIC data and synthetic test fixtures. No real NASA FIRMS file or live API call has been tested, so no statement about real MODIS/VIIRS behaviour is made.
- Ratios are observed detection ratios for one area and period, not universal correction factors; they depend on the filters in `config.py`, on small counts and on season. A change in the ratio is not evidence of a change in fire activity.
- Platform availability (first/last month) is inferred from the first and last detection in the processed record, not from official mission dates or observation-opportunity data. Coverage evidence is still per sensor family, not per platform.
- With the demo data only Terra, Aqua and S-NPP exist (the generator labels Terra/Aqua at random); NOAA-20 and NOAA-21 show as unavailable. Real FIRMS source names for NOAA-20/21 must be verified and added through `EXTRA_SOURCES` before they appear.
- The harmonised index is family-level and uses the whole-record ratio; the platform selection changes the comparison, ratio, validation and sensitivity panels, not the index.
- Leave-one-year-out validation is cross-validation across years (other years include later ones), evaluates only months with MODIS >= 5, and pooled/within-year correlations mostly reflect the seasonal cycle. Short or sparse areas often have no metrics, by design.
- Sensitivity spreads and the evidence labels use engineering thresholds (see `docs/methodology.md`); they are not statistical tests or confidence intervals.
- Platform contribution compares detection counts over each platform's own observing period; it is not a like-for-like efficiency comparison.
- The web page was checked headlessly (jsdom smoke test) and by rendering the charts with Chart.js on a Node canvas; it has not been opened in a real browser.

## Platform transition and provenance (Stage 5b)
- NASA states that delivery of new Suomi NPP observations ceased on 2 November 2026. The default download config still lists only MODIS_SP and VIIRS_SNPP_SP; recent VIIRS needs NOAA-20 (SP) and NOAA-21 (NRT only; the API lists no NOAA-21 SP source) via `EXTRA_SOURCES`. Not yet run on real data.
- NRT and standard-processing (SP) detections must not be assumed identical. The record now stores `product_stream`, and the page warns when a platform mixes streams, but there is no automatic level-shift test yet.
- Documented availability (`config.DOCUMENTED_AVAILABILITY`) is hand-copied from NASA pages retrieved on 2026-11-13; unverified dates are left blank. Replace it with the `/api/data_availability` output.
- The FIRMS area API day range is documented inconsistently (1..5 in the OpenAPI spec, 1..10 on an older note); `CHUNK_DAYS` is 5.
- `scan`, `track`, `version` and `type` are preserved but not yet used for pixel footprints, type filtering or exports.
- NASA acknowledgment, disclaimer and non-endorsement text are shown on the page and returned by the API; keep them in any report.

## Stage 6 limits
- The NRT/SP join check compares one platform's VIIRS/MODIS detection ratio in NRT months with SP months of the same calendar month. A flagged shift can come from NRT versus standard processing, real changes in activity, platform ageing, filters or sampling; the check cannot separate these. It does not correct the index. The 25 % flag, 6-month and 2-year minimums are engineering choices, not statistical tests.
- NOAA-21 has no SP source, so its whole record is NRT and the join cannot be tested for it ("not applicable"), and its NRT/SP behaviour is unknown.
- Past-only anomaly baseline: only the baseline is past-only. The VIIRS/MODIS ratio behind the harmonised index is fitted on the whole record (future years included). Early years show no anomaly (fewer than 10 earlier usable years).
- The FIRMS `data_availability` reply layout was not verified. `availability.parse` accepts a few plausible column names and raises otherwise. Availability dates for NRT sources may describe a rolling window (not verified); treat them as what FIRMS reports, not as mission dates.
- Platform comes from the `satellite` column; where that cannot be mapped, the VIIRS source name (e.g. VIIRS_NOAA20_SP) fills it, and disagreements are counted in the cleaning report. Terra/Aqua are never taken from the source name.
- Hotspot `type` meanings (0 vegetation fire, 1 volcano, 2 other static land, 3 offshore) come from copies of the FIRMS attribute table; the official page was not read. Only type 0 is kept (an assumption).
- Per-source download coverage is reported next to each platform, but family-level month status still uses the conservative intersection of all folders that have download windows.

## Not yet implemented (from the master prompt)
Harmonisation alternatives (monthly/seasonal/quantile), anomaly classification labels
(SENSOR_SENSITIVE / METHOD_SENSITIVE), grid-cell/anomaly/sensor map modes and time slider, grid-cell GeoJSON export, data dictionary export,
architecture/evaluation/research-evidence docs, observation-level Aqua/SNPP matching check, second region run, CI.
