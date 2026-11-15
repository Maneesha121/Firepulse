# FirePulse

Sensor-aware calendar of satellite hotspot activity (MODIS + VIIRS) with seasonal anomaly scores,
for the 2026 NASA Space Apps challenge "Harmonization of MODIS and VIIRS Hot Spots".

**Hotspots are satellite detections, not fire events and not burned area.** They include agricultural
burning and other heat sources. This project is an application-level contribution built on existing
methods; it does not improve fire detection.

## Quick start (included NASA FIRMS data)

The repository includes NASA FIRMS Standard Processing (SP) CSVs for MODIS, Suomi-NPP VIIRS, NOAA-20 VIIRS and NOAA-21 VIIRS in `data/raw/`. No API key or download is required to process these files.

    pip install -r requirements.txt
    python run_pipeline.py
    python serve.py                           # open http://localhost:8000 (exact area analysis)

`python serve.py` serves the site AND a small local API (standard library only). Without it, `python -m http.server -d web 8000`
still works but area selections fall back to an APPROXIMATE cell-centre mode, clearly labelled in the page.

Run the commands from the `firepulse` project folder. The processing command reads the raw inputs without changing them, writes cleaned/quality tables under `data/clean/`, and regenerates the calendar, quality report and metadata under `web/data/`. Data and output paths are resolved relative to the project folder even if a script is launched by path from another working directory. The local server refuses to present stale synthetic output in normal mode; use `python serve.py --demo` only when intentionally demonstrating generated data.

### Optional offline synthetic demo

    python run_pipeline.py --demo
    python serve.py --demo

Demo output is synthetic and illustrative only. It must not be presented as NASA observations.

## Data quality and filter sensitivity (new)

Raw records are never changed. Invalid records are removed and counted; everything else is **flagged in a separate table**
and an optional **profile** decides what enters the analysis. The page has a section that shows what was removed, flagged
and kept, and how each profile changes the monthly calendar, the VIIRS/MODIS ratio and the anomalies for the area you draw.
Details, thresholds and what was and was not verified against NASA documentation: `docs/data_quality.md`.

    python run_pipeline.py --profile all_valid     # choose the profile behind the calendar (default: baseline)
    python serve.py                            # quality section: scroll down; API: POST /api/quality

## Updating the NASA FIRMS inputs

The supplied source folders use FIRMS SP-style columns and chunk-window filenames. To refresh or extend them, get a free MAP_KEY from NASA FIRMS, set `FIRMS_MAP_KEY` in your shell (never store it in the repository), and run:

    python run_pipeline.py --fetch-availability
    python run_pipeline.py --download 2000-11-01 2026-07-31

Downloads are resumable and cached under `data/raw/`. After adding or downloading inputs, run `python run_pipeline.py` to regenerate the analysis. Outputs include `data/out/regional_calendar.csv`, `data/out/validation_loo.csv`, and `web/data/*.json`.

Point-level CSV for a box: `python export_hotspots.py 79.8 6.5 80.6 7.5 2020-01-01 2020-12-31 my.csv`

The included raw files were inspected for source folders, FIRMS headers, valid chunk-window CSVs and empty (zero-detection) replies; they have not been independently revalidated against live FIRMS or official attribute tables. Filter thresholds and type handling remain configurable project assumptions in `firepulse/config.py`.

## Method

| Step | What | Where |
|---|---|---|
| Filter | Invalid records removed; default profile: MODIS confidence >= 30, VIIRS nominal/high, type 0 (unverified assumptions; switchable) | `clean.py`, `quality.py` |
| Aggregate | monthly counts per 0.1 degree cell and per region | `aggregate.py` |
| Harmonize | ratio(calendar month) = median over overlap years of VIIRS/MODIS; MODIS-equivalent = VIIRS / ratio; band = ratio IQR; pooled fallback if < 5 years | `harmonize.py` |
| Validate | leave-one-year-out: predict a year's MODIS counts from VIIRS using ratios fitted without that year | `harmonize.loo_validation` |
| Anomaly | robust z = 0.6745 (x - median) / MAD vs the same calendar month in other years; needs >= 10 baseline years and non-zero MAD | `anomaly.py` |

These are engineering choices, not published standards. Read the literature (MODIS C6 Fire User Guide,
Schroeder et al. 2014, Giglio et al. 2016, Fu et al. 2020) before defending them in front of judges.

Known limits: ratio is estimated for the whole region and applied to any drawn area; months before 2012
cannot be checked against VIIRS; small counts make ratios unstable; Terra and Aqua are pooled as "MODIS";
Aqua/Terra overpass drift in recent years is not modelled; the `SPLICE` setting decides where VIIRS replaces MODIS.

## Customize

Everything is in `firepulse/config.py`: `BBOX` (other countries), `GRID`, thresholds, `SPLICE` (set `None` to use
MODIS wherever it exists), coverage start months. For South Asia use a larger box and `GRID = 0.25`.

## Deploy

`web/` is a static site. GitHub Pages or Vercel: publish the `web/` folder after running the real pipeline.
On first load, an animated satellite-awareness screen remains visible while the app loads its data and prepares the explorer; it does not simulate progress or delay the dashboard. If initialization fails, the screen reports the error and offers a retry.

## Layout

    run_pipeline.py        one-command pipeline         demo_data.py   synthetic data generator
    firepulse/             config, download, clean, aggregate, harmonize, anomaly, export
    web/index.html         map, calendar, chart, anomaly card, downloads (Leaflet + Chart.js from cdnjs)
    tests/test_core.py     harmonization and anomaly unit tests

## Area explorer (exact analysis)

Draw a polygon/rectangle, click a point (explicit +/- km square or the 0.1 degree cell), enter a box, or load a GeoJSON polygon.
The server filters the actual detections with point-in-polygon (points on an edge count as inside; holes excluded), validates the
geometry (self-intersection, range, antimeridian, size) and returns monthly MODIS/VIIRS/platform counts, the harmonised index,
anomalies, yearly and seasonal tables, missing-data periods and an area summary. Click a calendar month to see that month's
individual detections on the map (capped and labelled if sampled). The anomaly baseline (same calendar month, all other years in the
processed record) does not change when you change the date range.

Data status per month and sensor: OBSERVED_WITH_DETECTIONS, OBSERVED_ZERO_DETECTIONS, INCOMPLETE_PERIOD, MISSING_DATA,
INSUFFICIENT_EVIDENCE (see `firepulse/coverage.py`). Unknown months are empty, never 0. Coverage evidence comes from download windows
(`<start>_<days>.csv` files) or a `coverage.json` you write next to manually placed files:

    {"windows": [{"start": "2018-01-01", "end": "2025-10-31"}]}

## Sensor Intelligence (Stage 5)

A section below the dashboard explains how OBSERVED detections change across the MODIS-to-VIIRS transition for the selected area,
date range and platforms. It needs `python serve.py` (platform-level detections); the static site shows an explicit "unavailable" message.

| Panel | Shows |
|---|---|
| A. Monthly comparison | MODIS, VIIRS, raw combined (MODIS+VIIRS) and the harmonised index, with overlap and missing/incomplete months marked |
| B. Ratio by calendar month | median, 25th/75th percentile of VIIRS/MODIS, usable observations and years, exclusions, evidence label |
| C. Ratio over time | monthly ratio, unstable (low-MODIS) months, annual median, overlap period, descriptive rank trend |
| D. Platform contribution | detections and share per platform (Terra, Aqua, S-NPP, NOAA-20, NOAA-21), unavailable platforms flagged |
| E. Leave-one-year-out | held-out year, actual vs predicted MODIS by month, correlation (if defined), sMAPE, absolute bias, valid months, baseline |
| F. Sensitivity | spread of the ratio across time windows and platform pairs |

Platforms are ticked in the section; all five = family comparison, a subset is strict (every ticked platform must have data that month).
The same `/api/area` call returns `sensor_intelligence`; send `"platforms": {"modis": ["TERRA"], "viirs": ["SNPP"]}` to select a subset.
If the selection has fewer than 36 usable overlap months, the regional ratio is used and the page says so (chip "Index calibration: REGION").
Ratios are observed detection ratios, not correction factors; a difference in detections is not a difference in fires. Formulas, thresholds and
chart interpretation: `docs/methodology.md`; limits: `docs/limitations.md`. Synthetic data are labelled and illustrative only.

## Stage 6: transition-aware additions
- `baseline` option on `/api/area` (`all_other_years` default, or `past_only`) and a selector in the UI. Anomalies need 10 usable baseline years.
- `sensor_intelligence.stream_join`: per VIIRS platform, compares NRT months with standard-processing months of the same calendar month and flags a level shift (see `firepulse/stream_join.py`, `docs/stage6.md`).
- `python run_pipeline.py --fetch-availability` (needs `FIRMS_MAP_KEY`) stores the FIRMS availability reply; the platform timeline then shows FIRMS-reported first/last dates per source next to the stored NASA-page dates.
- `EXTRA_SOURCES` now lists `VIIRS_NOAA20_SP` and `VIIRS_NOAA21_SP` (standard processing only; the FIRMS availability response of 2026-11-13 listed NOAA-21 SP from 2023-03-01 — re-check with `--fetch-availability`). `python run_pipeline.py --download START END` fetches them too.
- The cleaning report lists raw hotspot `type` codes with counts and what was excluded.

## NASA data attribution
FirePulse uses NASA FIRMS data. The page footer, the `/api/area` response and any report carry NASA's requested acknowledgment, the "as is" disclaimer and the statement
that NASA does not endorse FirePulse (text in `firepulse/config.py`, `ATTRIBUTION`). Next steps for the project and a full AI build prompt: `docs/MASTER_PROMPT_V2.md`.

## Windows (Command Prompt)

    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    python run_pipeline.py --demo
    python serve.py --demo
    python -m pytest -q tests

Then open http://localhost:8000 and scroll to **Sensor Intelligence**. Optional headless page check (needs Node): `npm i jsdom` then
`node tests\web_smoke.mjs http://127.0.0.1:8000/index.html` while the server runs.

## Hackathon-day procedure (real NASA data)

1. Get the official files. Check product, platform names, columns and dates in the challenge resources. Do not assume they match this README.
2. Either download: `set FIRMS_MAP_KEY=your_key` then `python run_pipeline.py --download 2000-11-01 2025-10-31`;
   or place CSVs in `data\raw\MODIS_SP\` and `data\raw\VIIRS_SNPP_SP\` and add a `coverage.json` (above) to each folder.
3. Validate the inputs (nothing is modified): `python validate_inputs.py` and read the satellite/confidence/version values it prints.
   Compare them with `firepulse/schema.py` (platform codes) and `firepulse/config.py` (filters, folder names, BBOX).
4. Process: `python run_pipeline.py` (reuses raw files). Read `data\clean\cleaning_report.json` for every row removed and why.
5. Run `python -m pytest -q tests`, then `python serve.py` and open http://localhost:8000. Check the origin chip says NASA FIRMS data.
6. Inspect the ratio/validation printout, `data\out\regional_calendar.csv` (status columns) and any INCOMPLETE/INSUFFICIENT months before presenting.

NOT YET TESTED against the live FIRMS API or any real NASA file. Run a one-week download first.

## Files added in this version

    firepulse/schema.py     platform vocabulary, data-origin labels      firepulse/coverage.py   coverage evidence and month status
    firepulse/validate.py   input validation (validate_inputs.py)        firepulse/spatial.py    geometry validation, area, point-in-polygon
    firepulse/area.py       area calendar, summaries, month detections   firepulse/api.py        request handling for serve.py
    serve.py                local server + API                           docs/audit.md, docs/limitations.md
    firepulse/sensor_transition.py  Stage 5 sensor intelligence          docs/methodology.md, tests/test_sensor_transition.py
