# FirePulse 🔥

**Sensor-Aware Harmonization and Seasonal Anomaly Detection of Satellite Fire Activity**

FirePulse is a satellite fire-activity analysis application developed for the **2026 NASA Space Apps Challenge — “Harmonization of MODIS and VIIRS Hot Spots.”**

It processes NASA Fire Information for Resource Management System (FIRMS) active-fire observations from the MODIS and VIIRS satellite instruments to support historical fire-activity analysis, sensor comparison, data-quality assessment, and seasonal anomaly exploration.

The application provides an interactive way to explore satellite hotspot observations across geographic areas and time periods.

> **Important:** Satellite hotspots are thermal detections, not confirmed fire events, fire perimeters, or burned-area measurements. They may include agricultural burning and other heat sources. FirePulse does not improve the underlying satellite fire-detection algorithms.

---

## The Problem

MODIS and VIIRS provide valuable satellite observations of active fire locations. However, their observations differ because of sensor characteristics, spatial resolution, observation frequency, and other factors.

Directly comparing their detection counts can therefore produce misleading interpretations.

FirePulse addresses this challenge at the application level by organizing and processing observations from both sensors, examining their differences, and presenting historical activity patterns with data-quality information.

## What FirePulse Does

- **Historical fire-activity calendar:** Explore monthly patterns in satellite hotspot observations.
- **MODIS and VIIRS comparison:** Examine differences between observations from the two satellite instruments.
- **Seasonal anomaly analysis:** Explore unusual patterns in historical activity using the application's anomaly scores.
- **Geographic exploration:** Investigate fire-activity patterns for selected geographic areas.
- **Data-quality assessment:** Review removed, flagged, and retained records and explore how filtering profiles affect analytical results.
- **Interactive dashboard:** Explore generated results through a browser-based interface.

The outputs are intended for exploratory analysis and should not be interpreted as confirmed fire-event records or operational fire warnings.

---

## Data Sources

FirePulse uses active-fire observations from **NASA FIRMS Standard Processing (SP)** datasets:

- **MODIS:** Moderate Resolution Imaging Spectroradiometer observations.
- **VIIRS:** Visible Infrared Imaging Radiometer Suite observations.

NASA FIRMS provides satellite-based active-fire and thermal-anomaly information.

Official data source: [NASA Fire Information for Resource Management System (FIRMS)](https://firms.modaps.eosdis.nasa.gov/)

The application processes the supplied FIRMS-format CSV files. The raw input files are kept separate from the generated cleaned datasets and dashboard outputs.

**Data coverage and availability depend on the FIRMS files supplied to the project.** Refer to the included data and generated metadata for the actual coverage of a particular run.

## How It Works

The FirePulse workflow consists of the following stages:

1. **Input:** Read MODIS and VIIRS FIRMS-format CSV observations.
2. **Validation and quality checks:** Identify invalid records and record quality-related flags.
3. **Filtering:** Apply the selected analysis profile without modifying the original raw records.
4. **Analysis:** Generate sensor comparison, monthly activity summaries, and seasonal anomaly outputs.
5. **Visualization:** Produce dashboard datasets and make them available through the interactive web application.

The processing pipeline generates cleaned and quality-related outputs under `data/clean/` and dashboard datasets under `web/data/`.

---

## Getting Started

### Requirements

- Python 3.10 or later (use a compatible Python version for the pinned project dependencies).
- Git.
- NASA FIRMS Standard Processing CSV inputs for MODIS and VIIRS.

### 1. Clone the repository

```bash
git clone https://github.com/Maneesha121/Firepulse.git
cd Firepulse
```

### 2. Create a virtual environment

Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
```

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Provide the NASA FIRMS input data

Place the required MODIS and VIIRS FIRMS Standard Processing CSV files in the configured source folders under `data/raw/`.

The raw input files are not necessarily included in the repository. Users must obtain the appropriate datasets from NASA FIRMS and place them in the expected locations.

### 5. Run the processing pipeline

```bash
python run_pipeline.py
```

This reads the raw inputs without modifying them, generates cleaned and quality-related tables, and regenerates the dashboard datasets.

### 6. Validate the generated outputs

```bash
python validate_submission.py
```

The preflight validation checks the expected input structure, generated outputs, and provenance labels. It is a structural and labeling check; it does **not independently authenticate the original NASA source files**.

### 7. Start FirePulse

```bash
python serve.py
```

Open the application:

[http://localhost:8000](http://localhost:8000)

The local server provides both the web dashboard and a lightweight API for area-specific analysis.

Alternatively, the static dashboard can be served with:

```bash
python -m http.server -d web 8000
```

When using the static server, area selections use the dashboard's clearly labelled approximate cell-centre mode instead of the exact-area API.

---

## Data Quality and Filter Sensitivity

FirePulse preserves the original raw observations.

Invalid records are removed from the analysis and counted. Other quality concerns are recorded separately as flags. The selected filtering profile determines which records are included in the analytical outputs.

The dashboard provides information about:

- Records removed, flagged, and retained.
- Differences between filtering profiles.
- Changes in monthly activity summaries.
- Changes in the VIIRS/MODIS observation ratio.
- Changes in seasonal anomaly results for selected areas.

This allows users to examine how data-quality decisions influence the resulting analysis rather than treating every satellite detection as equally reliable.

## Optional: Synthetic Demo Mode

FirePulse includes an offline synthetic-data mode for demonstrating the application without real FIRMS inputs.

```bash
python run_pipeline.py --demo
python serve.py --demo
```

**Warning:** Synthetic demo outputs are illustrative only. They are not NASA observations and must not be presented as real satellite data or scientific findings.

After using demo mode, regenerate the real-data outputs before a real-data presentation:

```bash
python run_pipeline.py
python validate_submission.py
python serve.py
```

## Updating NASA FIRMS Inputs

To download or refresh FIRMS inputs, obtain a free NASA FIRMS MAP_KEY and configure it as the `FIRMS_MAP_KEY` environment variable.

Windows CMD:

```cmd
set FIRMS_MAP_KEY=YOUR_MAP_KEY
```

Then run:

```bash
python run_pipeline.py --fetch-availability
python run_pipeline.py --download 2000-11-01 2026-07-31
python run_pipeline.py
```

Downloads are resumable and cached under `data/raw/`.

Use a valid date range appropriate to the available FIRMS products and the intended analysis.

## NASA Data Attribution

FirePulse uses NASA FIRMS data.

NASA data acknowledgments, applicable disclaimers, and the statement that NASA does not endorse FirePulse are included in the application's attribution information and relevant outputs.

FirePulse is an independent project and is not an official NASA application.

## Project Limitations

- Active-fire detections do not represent confirmed fire events or burned areas.
- MODIS and VIIRS observations have different sensor characteristics and should not be assumed to be directly equivalent.
- Results depend on the coverage, quality, and availability of the supplied input datasets.
- Seasonal anomaly scores are exploratory analytical outputs, not predictions of future fires.
- The application does not replace official fire monitoring, emergency-response systems, or ground verification.

## Repository Structure

```text
Firepulse/
├── firepulse/
│   ├── schema.py
│   └── coverage.py
├── data/
│   ├── raw/
│   └── clean/
├── web/
│   └── data/
├── docs/
│   └── real_data_preflight.md
├── run_pipeline.py
├── serve.py
├── validate_submission.py
├── requirements.txt
└── README.md
```

## Built For

**NASA Space Apps Challenge 2026**

Challenge: *Harmonization of MODIS and VIIRS Hot Spots*

**Project:** FirePulse

**Repository:** [github.com/Maneesha121/Firepulse](https://github.com/Maneesha121/Firepulse)

---

*FirePulse — Exploring satellite fire activity through multi-sensor data analysis.*
