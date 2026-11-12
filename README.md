# FirePulse

Sensor-aware calendar of satellite hotspot activity (MODIS + VIIRS) with seasonal anomaly scores,
for the 2026 NASA Space Apps challenge "Harmonization of MODIS and VIIRS Hot Spots".

**Hotspots are satellite detections, not fire events and not burned area.** They include agricultural
burning and other heat sources. This project is an application-level contribution built on existing
methods; it does not improve fire detection.

## Quick start (offline demo, synthetic data)

    pip install -r requirements.txt
    python run_pipeline.py --demo
    python -m http.server -d web 8000        # open http://localhost:8000
    python -m pytest -q tests

The repo ships with demo output in `web/data/` so the site opens immediately. A red banner marks it as
SYNTHETIC. Replace it with real data before presenting.

## Real data

1. Get a free MAP_KEY from NASA FIRMS and `export FIRMS_MAP_KEY=...`.
2. Check real coverage: `python -c "from firepulse.download import availability; import os; print(availability(os.environ['FIRMS_MAP_KEY']))"`
3. Run: `python run_pipeline.py --download 2000-11-01 2025-10-31`
   (resumable; raw files are cached in `data/raw/`; the MODIS 2000-2011 part is the slow bit).
4. Serve `web/` as above. Outputs: `data/out/regional_calendar.csv`, `data/out/validation_loo.csv`, `web/data/*.json`.
5. Point-level CSV for a box: `python export_hotspots.py 79.8 6.5 80.6 7.5 2020-01-01 2020-12-31 my.csv`

NOT YET TESTED against the live FIRMS API (written without network access). Run a one-week download first.
Confirm: source names, CSV columns (`type`, `confidence`, `acq_date`), and the filter thresholds in `firepulse/config.py`.

## Method

| Step | What | Where |
|---|---|---|
| Filter | MODIS confidence >= 30 (assumption), VIIRS nominal/high, type 0 (vegetation fire) if present | `clean.py` |
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

## Layout

    run_pipeline.py        one-command pipeline         demo_data.py   synthetic data generator
    firepulse/             config, download, clean, aggregate, harmonize, anomaly, export
    web/index.html         map, calendar, chart, anomaly card, downloads (Leaflet + Chart.js from cdnjs)
    tests/test_core.py     harmonization and anomaly unit tests
