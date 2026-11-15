# Stage 6 summary (master prompt P0 items 2 to 6)

The supplied `data/raw/` folders contain NASA FIRMS SP-format CSV windows for MODIS, Suomi-NPP VIIRS, NOAA-20 VIIRS and NOAA-21 VIIRS. The files were inspected for headers, readable windows and empty replies. The full pipeline has not yet been run on them; all analytical results and feature tests described below remain unverified on this real dataset.

| Item | What was added | Status |
|---|---|---|
| 6 Anomaly baseline | `baseline` = `all_other_years` or `past_only` (API, UI, output `baseline_mode`); anomaly withheld below `MIN_BASELINE` (10) usable years | PARTIAL (synthetic) |
| 3 Stream-aware harmonisation | `stream_join.py`: per-platform NRT vs SP level comparison, same calendar month, thresholds in output | PARTIAL (synthetic); detects, does not correct |
| 2 Availability ingestion | `availability.py`, `--fetch-availability`, `meta.product_availability`, timeline basis label, disagreement flags | PARTIAL; reply layout unverified |
| 4 NOAA-20 SP + NOAA-21 NRT | `EXTRA_SOURCES`, platform from source name with conflict count, per-source download coverage in `meta.source_coverage` | PARTIAL; raw `satellite` codes unverified |
| 5 Attribute tables | raw `type` code kept, documented meaning, excluded count in cleaning report and UI | PARTIAL; only `type` done, from copies of the table |

## Formulas
- Platform ratio r(m) = platform detections / MODIS detections, for months where the platform is available, both families observed and MODIS >= 5.
- NRT comparison for month m: r(m) / median of SP ratios of the same calendar month (>= 2 SP years). shift = median of those comparisons minus 1; reported only with >= 6 compared months; flagged at |shift| >= 25 %.
- Past-only z = 0.6745 (x - median) / MAD using only earlier years; unchanged otherwise.

## Still open
Run `python run_pipeline.py` (no MAP_KEY required for the supplied files) and inspect the resulting cleaning/coverage reports, harmonization and validation before presenting. Refreshing FIRMS coverage requires a MAP_KEY. Official attribute pages for confidence/daynight/version/scan/track, PDF report, Playwright/CI, two-experience UI remain open.
