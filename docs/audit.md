# FirePulse repository audit (Stage 1)

Audited commit: `backup-original` (the project as uploaded). 683 lines of code, 5 tests (all pass), demo pipeline runs.

## Existing working features
- `run_pipeline.py`: one-command pipeline (demo or FIRMS download); `--demo` works offline.
- `clean.py`: confidence/type/BBOX filters -> standard columns. `aggregate.py`: 0.1-degree cell x month counts and region series.
- `harmonize.py`: calendar-month VIIRS/MODIS ratio (median, IQR band, pooled fallback), splice, leave-one-year-out (LOO) validation.
- `anomaly.py`: same-calendar-month median/MAD robust z, percentile, zero-MAD and short-baseline guards.
- `web/index.html`: Leaflet map with draw tools, calendar heat-map (harmonised or z), chart, anomaly card, CSV/PNG/HTML downloads, red SYNTHETIC banner.

## Partially implemented
- Area selection: polygon/rectangle drawn, but filtered in the browser by **cell-centre point-in-polygon on 0.1-degree cells** (approximate, not on observations).
- Sensor comparison: raw vs harmonised chart exists; no ratio chart, no per-platform view, no LOO chart in the UI.
- Data status: months inside an *assumed* availability window are treated as observed with 0 detections.
- Downloads: monthly CSV, chart PNG, minimal HTML report. No GeoJSON, data dictionary, provenance in exports.

## Missing
Platform preservation (Terra/Aqua/SNPP/NOAA-20/21), provenance and synthetic/genuine tagging per record, input validation command, cleaning accounting,
exact polygon analysis, area summaries, yearly/seasonal tables, sensitivity experiments, area-specific ratios, map modes (cells, anomaly, time slider), docs, most tests.

## Scientific weaknesses
1. Cell-centre polygon filtering misattributes edge cells; not labelled as approximate.
2. Zero vs missing: absence of rows inside the assumed window becomes 0 (no coverage evidence).
3. Ratio estimated for the whole region and applied to any drawn area (stated in the UI, but unstable for small areas).
4. Terra+Aqua pooled; VIIRS = S-NPP only; NOAA-20/21 not represented.
5. Anomaly card (past years only) and calendar (all other years) use different baselines -> inconsistent z for the same month.
6. MODIS confidence >= 30 and VIIRS nominal/high are unverified assumptions (documented as such).
7. NOT tested against live FIRMS.

## Engineering weaknesses
- Harmonisation and anomaly logic duplicated in Python and JavaScript.
- `download.py` caches an *error reply* as an empty file, so a transient failure becomes permanent until the file is deleted.
- `clean.load_raw` silently drops exact duplicate rows; filter removals are only printed as totals.
- Region hard-coded in `config.BBOX`; `export_hotspots.py` supports boxes only.
- 5 tests cover only harmonise/anomaly.

## Do not change
Leaflet + Leaflet.draw + Chart.js from cdnjs, pandas/numpy/requests, static-site deployment, visual identity (colours, layout), existing method definitions and `config.py` as the single settings file.

## Implementation order used
Stage 2 provenance/validation/coverage -> Stage 3 exact spatial filtering + local API -> Stage 4 area calendar/summaries -> then Stages 5-12.
