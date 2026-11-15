# FirePulse

Sensor-aware calendar of satellite hotspot activity (MODIS + VIIRS) with seasonal anomaly scores,
for the 2026 NASA Space Apps challenge "Harmonization of MODIS and VIIRS Hot Spots".

**Hotspots are satellite detections, not fire events and not burned area.** They include agricultural
burning and other heat sources. This project is an application-level contribution built on existing
methods; it does not improve fire detection.

## Quick start (real NASA FIRMS data)

The repository is designed to run from real NASA FIRMS Standard Processing (SP) CSVs in `data/raw/`.
The normal submission path is:

    pip install -r requirements.txt
    python run_pipeline.py
    python validate_submission.py
    python serve.py                           # open http://localhost:8000

The validation step checks that the generated dashboard metadata and cleaned outputs are labeled as
`NASA_FIRMS` and that raw FIRMS-format inputs exist for the MODIS/VIIRS sources. It prevents accidental
submission with synthetic demo artifacts.

`python serve.py` serves the site AND a small local API (standard library only). Without it,
`python -m http.server -d web 8000` still works but area selections fall back to an APPROXIMATE cell-centre
mode, clearly labelled in the page.

Run the commands from the project root. The processing command reads the raw inputs without changing them,
writes cleaned/quality tables under `data/clean/`, and regenerates the dashboard outputs in `web/data/`.

### Optional offline synthetic demo

    python run_pipeline.py --demo
    python serve.py --demo

Demo output is synthetic and illustrative only. It must not be presented as NASA observations.

## Data quality and filter sensitivity

Raw records are never changed. Invalid records are removed and counted; everything else is **flagged in a
separate table** and an optional **profile** decides what enters the analysis. The page has a section that
shows what was removed, flagged and kept, and how each profile changes the monthly calendar, the VIIRS/MODIS
ratio and the anomalies for the area you draw.

The validation helper is deliberately strict about provenance: after a real-data run, the generated private
metadata and cleaned outputs need to remain in the expected NASA FIRMS state. Synthetic demo files are
explicitly marked as such and should never be used in evaluation.

## Updating the NASA FIRMS inputs

The supplied source folders use FIRMS SP-style columns and chunk-window filenames. To refresh or extend them,
get a free MAP_KEY from NASA FIRMS, set `FIRMS_MAP_KEY` in your shell and run:

    python run_pipeline.py --fetch-availability
    python run_pipeline.py --download 2000-11-01 2026-07-31

Downloads are resumable and cached under `data/raw/`. After adding or downloading inputs, run
`python run_pipeline.py` to regenerate the analysis.

## NASA data attribution

FirePulse uses NASA FIRMS data. The page footer, the `/api/area` response and any report carry NASA's
requested acknowledgment, the "as is" disclaimer and the statement that NASA does not endorse FirePulse.

## Hackathon-day procedure (real NASA data)

1. Download or place the official FIRMS files into the configured source folders.
2. Run `python run_pipeline.py` to generate the cleaned tables and the dashboard dataset.
3. Run `python validate_submission.py` before opening the site for presentation.
4. Run `python serve.py` and open http://localhost:8000.
5. Confirm the origin chip says NASA FIRMS data and not the synthetic demo banner.

## Files added in this version

    firepulse/schema.py     platform vocabulary, data-origin labels
    firepulse/coverage.py   coverage evidence and month status
    validate_submission.py  submission preflight guarding against synthetic data
    docs/real_data_preflight.md

