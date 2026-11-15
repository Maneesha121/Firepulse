# FIREPULSE MASTER PROMPT v2 (NASA Space Apps 2026: Harmonization of MODIS and VIIRS Hot Spots)

Use this prompt with an AI coding agent working INSIDE the existing FirePulse repository (branch `feature/area-explorer`).
It supersedes the v1 master prompt where they differ. Read PART 0 to 3 before touching code.

---

## PART 0. ROLE AND RULES

You are a senior team (geospatial engineer, EO data scientist, statistician, UX designer, technical writer, QA engineer).
FirePulse is an EXISTING project. Never rebuild it. Preserve working code and tests; fix what is wrong; add what is missing.

Non-negotiable rules (all of v1 still applies):
1. No fabricated data, results, citations, DOIs, product fields, availability dates or API behaviour. If unverified, write "not verified" and say how to verify.
2. Synthetic data is always labelled; it is never described as NASA data or used to claim real sensor performance.
3. Missing is not zero. Unknown coverage, unavailable platforms and months outside a product record are null and shown as such.
4. A hotspot is a satellite thermal-anomaly detection: not a unique fire, burned area, fire size or fire danger.
5. The harmonised index is a MODIS-equivalent analytical index, not a physical fire count. Ratios are observed detection ratios, not universal correction factors.
6. Never weaken or delete tests. If a test encodes an assumption that proved wrong, pin the assumption inside the test and report it.
7. No secrets in the repo. FIRMS MAP_KEY comes from the `FIRMS_MAP_KEY` environment variable only.
8. Do not mix burned-area, aerosol, geostationary or HLS products into the active-fire harmonised index. They are separate optional modules.
9. Do not imply NASA endorsement. Keep the NASA acknowledgment, disclaimer and non-endorsement text visible (see `config.ATTRIBUTION`).
10. Mark nothing COMPLETE unless it is implemented AND tested; real-data features are PARTIAL until run on real FIRMS files.

Working method: audit, plan, implement in small increments, run `python -m pytest -q tests` after every increment, report changed files, formulas, test results, failed/skipped tests, and what is still synthetic-only.

---

## PART 1. FACTS VERIFIED ON 2026-11-13 (cite the page; re-check before relying on them)

[V] = read on an official NASA page or API specification during the audit. [U] = not verified; verify before use.

| # | Fact | Status | Where |
|---|---|---|---|
| 1 | Delivery of new Suomi NPP observations ceased on 2 November 2026; historical S-NPP products stay available; users must move to NOAA-21 (primary) and NOAA-20 | V | earthdata.nasa.gov VIIRS transition resources; FIRMS Active Fire page; Earthdata banner |
| 2 | FIRMS VIIRS 375 m NOAA-20 data: from 1 April 2018; NOAA-21: from 17 January 2024 | V | firms.modaps.eosdis.nasa.gov/active_fire |
| 3 | Launches: S-NPP 2011-10-28, NOAA-20 2017-11-18, NOAA-21 2022-11-10; VIIRS on NOAA-21 "joined NOAA-20 and Suomi NPP in the same orbit"; NOAA-21 about 50 min ahead of NOAA-20 with S-NPP between | V | FIRMS FAQ; VIIRS 375 m page |
| 4 | Aqua will eventually reach end of operations; VIIRS NOAA-20/21 is the stated afternoon-orbit continuity. No end date verified | V (statement), U (date) | FIRMS S-NPP transition article |
| 5 | Area API: `/api/area/csv/{MAP_KEY}/{SOURCE}/{west,south,east,north}/{DAY_RANGE}/{DATE}`; OpenAPI spec says DAY_RANGE 1..5, an older page note says 1..10 | V (conflict) | FIRMS API page; OpenAPI listing. Use 5 |
| 6 | Source enum: MODIS_NRT, MODIS_SP, VIIRS_SNPP_NRT, VIIRS_SNPP_SP, VIIRS_NOAA20_NRT, VIIRS_NOAA20_SP, VIIRS_NOAA21_NRT, LANDSAT_NRT. No NOAA-21 SP | V | OpenAPI listing |
| 7 | Rate limit 5000 transactions per 10 minutes; multi-day requests may count as several transactions | V | OpenAPI listing |
| 8 | `/api/data_availability/csv/{MAP_KEY}/ALL` reports product date availability (already called by `download.availability`) | V | FIRMS API page |
| 9 | NRT uses predictive orbit information for geolocation; standard (SP) products are science quality; NASA says to prefer standard products when latency is not a concern. For MODIS, L2 Fire NRT is "nearly identical" to the operational product because the fire code uses no ancillary data | V | Earthdata data-latency and NRT-vs-standard pages |
| 10 | MODIS pixel is 1 km, VIIRS 375 m (nominal). Footprint formula uses 0.375 km (VIIRS), 1.0 km (MODIS), 111.32 km per degree; actual size varies with scan angle, and CSV columns `scan`/`track` carry the along/across-scan pixel size | V (formula), V (columns seen in API sample) | FIRMS footprint tutorial; API sample |
| 11 | Static thermal anomalies (volcanoes, gas flares, industrial heat, incinerators) exist and FIRMS added "type" identification (March 2025 announcement) | V (existence), U (exact `type` code meanings per product) | ARSET pages. Fetch the official attribute tables before coding classification |
| 12 | FIRMS requires this acknowledgment and shows the "as is" disclaimer (full text in `config.ATTRIBUTION`) | V | FIRMS About page |
| 13 | MODIS and VIIRS confidence are not on the same scale (MODIS 0-100 percent, VIIRS low/nominal/high) | V (third-party summary of FIRMS FAQ), U (re-check FAQ) | firms FAQ |
| 14 | An open per-country yearly archive (no key) exists for MODIS and VIIRS S-NPP | U (third-party library docs only) | verify on firms.modaps.eosdis.nasa.gov/download before depending on it |

Not available in this audit: live FIRMS data (no MAP_KEY in the sandbox, outbound access limited). Every real-data item below is therefore UNTESTED.

---

## PART 2. CORRECTIONS TO ASSUMPTIONS IN v1 / THE OLD BUILD

1. `CHUNK_DAYS` was 10; the API specification says 5. Fixed to 5 (the one caching test that assumed 10 now pins it).
2. S-NPP is now a closed archive. The old default (MODIS_SP + VIIRS_SNPP_SP only) cannot represent recent VIIRS. Add NOAA-20 (SP) and NOAA-21 (NRT only) through `EXTRA_SOURCES`, with `product_stream` recorded.
3. NRT and SP must not be pooled silently. NOAA-21 has no SP stream; the recent record will be NRT. Treat the join as a possible level shift and test it.
4. "Platform availability inferred from detections" is not operational coverage. Keep documented availability (NASA pages) and detected availability (the record) side by side. Neither proves clear-sky observation of an area.
5. Aqua and Terra will not last: design for a MODIS family that ends, with VIIRS continuing, not only MODIS history plus VIIRS.
6. MODIS confidence (percent) and VIIRS confidence (categories) are different scales; filters are assumptions until checked against the user guides.

---

## PART 3. CURRENT BUILD STATUS (be honest; update this table)

Legend: COMPLETE = implemented and tested; PARTIAL = implemented, not verified on real data or in a real browser; NOT IMPLEMENTED.

| Area | Status | Notes |
|---|---|---|
| Interactive map, polygon/point/search area selection, exact point-in-polygon | PARTIAL | Tested via API tests and jsdom; not opened in a real browser |
| FIRMS downloader (resumable, error replies not cached) | PARTIAL | Never run against the live API |
| Cleaning with row accounting; platform mapping | PARTIAL | Raw `satellite` values for N20/N21 unverified on real files |
| Provenance columns (product_stream, version, scan, track, fire_type) | PARTIAL | Kept by the cleaner (tested on synthetic rows); not yet used by exports/UI beyond product-stream notes |
| Harmonisation (calendar-month VIIRS/MODIS ratio, area vs regional calibration) | PARTIAL | Synthetic only. Stage 6 adds a per-platform NRT/SP join check (detects a level shift, does not correct it) |
| FIRMS availability ingestion (`--fetch-availability`), per-source download coverage, NOAA-20 SP + NOAA-21 NRT in EXTRA_SOURCES | PARTIAL | Stage 6: parser fails loudly on unknown layout; the real reply layout is NOT verified; fixtures are assumed. Never run against the live API |
| Hotspot `type` accounting (raw code kept, documented meaning, excluded count) | PARTIAL | Stage 6: meanings from copies of the FIRMS table, official page not read; `confidence`, `daynight`, `version`, `scan`, `track` definitions still to be documented from the official page |
| Historical calendar, anomaly (same-month; all-other-years or past-only baseline) | PARTIAL | Stage 6: baseline selectable in API and UI; anomaly withheld below 10 usable years; synthetic only. Past-only applies to the baseline, not to the whole-record VIIRS/MODIS ratio |
| Sensor Intelligence A-G (comparison, ratio, over time, contribution, LOYO, sensitivity, platform timeline) | PARTIAL | Synthetic only; documented vs detected availability implemented |
| Attribution/disclaimer/non-endorsement | COMPLETE (page + API) | Keep in reports |
| Exports | PARTIAL | CSV; no PDF, no JSON metadata |
| Two-experience UI (citizen vs scientific), intro screen, world landing | NOT IMPLEMENTED | Single dashboard |
| Scientific PDF report | NOT IMPLEMENTED | |
| Observation coverage (swath outlines), hotspot type filter, hotspot detail popup with pixel footprint | NOT IMPLEMENTED | |
| Real-browser end-to-end tests, CI | NOT IMPLEMENTED | |

---

## PART 4. PRIORITISED BACKLOG WITH ACCEPTANCE CRITERIA

Work top to bottom. Each item: implement in the existing architecture, add tests, update docs.

### P0. Real data and scientific correctness (blocks every claim)
1. Real-data smoke run. With `FIRMS_MAP_KEY` set: download one week for MODIS_SP, VIIRS_NOAA20_SP and VIIRS_NOAA21_NRT over the BBOX; run `validate_inputs.py`; record actual `satellite`, `confidence`, `type`, `version`, `scan`, `track` values in `docs/real_data_findings.md`. Acceptance: platform mapping confirmed or fixed; no UNKNOWN platforms; monthly counts equal a manual count of the CSV.
2. Ingest `/api/data_availability` per source into `web/data/meta.json` as `product_availability` (first/last date per source). Show it in the platform timeline as the authoritative "documented availability" instead of hard-coded dates; keep the config values as fallback with retrieval date.
3. Stream-aware harmonisation. Estimate and display the VIIRS/MODIS ratio separately for SP-only overlap and report the level shift where NRT begins (per platform). Acceptance: a test with a synthetic step at the NRT join is flagged; a real-data note explains the result.
4. Add NOAA-20 SP and NOAA-21 NRT via `EXTRA_SOURCES`; make coverage evidence per platform, not only per family (download windows per source). Acceptance: S-NPP ending and NOAA-21 start appear correctly in coverage and in the ratio composition warnings.
5. Fetch the official FIRMS attribute tables and document `type`, `confidence`, `daynight`, `version`, `scan`, `track`. Implement type handling only with those definitions: preserve the raw code, show a documented display category, never classify unknown codes by guessing. Add a user-visible "excluded by type" count from the cleaning report.
6. Anomaly baseline options: all-other-years (current) and past-only. Show which was used; disable the anomaly when the baseline has fewer than 10 usable years; keep the "retrospective, not forecast" wording.

### P1. Citizen experience and the calendar (the NASA deliverable)
7. Landing: skippable branded intro (CSS only, honours `prefers-reduced-motion`), then the world map, search (country/city/coordinates), area drawing, date range, sensor filter (MODIS / VIIRS / all), legend.
8. Two entries: "Explore Fire Activity" (plain language) and "Scientific Analysis & Reports" (existing Sensor Intelligence). One backend, no duplicated calculation.
9. Calendar: year-by-month grid with an accessible sequential colour ramp (plus numbers and patterns, never colour alone), explicit states for "no detections in observed data", "missing source data", "incomplete", "coverage unknown", "outside product record", and a same-month-across-years comparison (e.g. August of three years) with the baseline stated in words.
10. Hotspot detail popup: show only attributes present in the record (date, time, platform, instrument, confidence, FRP, day/night, type, version). Draw the pixel footprint from `scan`/`track` (km) using the FIRMS footprint formula; label it "nominal pixel footprint, not fire size". No arbitrary radius.
11. Plain-language sensor explainer and the NASA attribution in the footer of every page.

### P2. Reports and exports
12. Server-side PDF report for the current area, dates and platform selection (ReportLab or WeasyPrint plus matplotlib figures; check what is installable on Windows). Sections as in v1 PART 14. Demo data produces a watermarked "DEMONSTRATION REPORT". Acceptance: values in the PDF equal the API JSON for the same request (tested); NASA attribution, limitations and verified references only.
13. JSON metadata sidecar (geometry, dates, platforms, thresholds, product ids and availability, software version, git commit, timestamp, SHA-256 of inputs) and CSV exports that match the screen row for row.
14. Reproducibility: `reproduce.md` with exact commands; the metadata JSON can re-run the analysis.

### P3. Optional, only after P0 to P2
15. Observation-coverage assessment from FIRMS swath outlines if the product is accessible; never infer clear-sky coverage.
16. Separate modules (never merged into the index): VIIRS/MODIS burned area, OMPS aerosol/pyroCb context, geostationary imagery, HLS indices (NDVI, NDMI, NBR, NBR2). Treat as context layers.
17. Second region (change `BBOX`/`GRID`), performance work (pre-aggregation, spatial index, request cache), Playwright tests, GitHub Actions CI.

---

## PART 5. STRATEGY FOR A GLOBAL-FINALIST SUBMISSION

Judges reward: a clear problem, a working demo, scientific honesty, usefulness to real users, and polish. Differentiators FirePulse can own:
1. **Uncertainty-first harmonisation.** Every number shows its evidence (usable years, ratio spread, calibration source, missing months). Say it in the first 20 seconds: "We do not claim sensors are equivalent; we show how much we can and cannot say."
2. **Transition-aware.** Built for the real 2026 situation: S-NPP delivery ended 2 Nov 2026, NOAA-20/21 continue, MODIS eventually ends. Few teams will model platform retirement, NRT/SP joins and documented vs detected availability.
3. **Two audiences, one engine.** A student can read the calendar in 10 seconds; a scientist can open the validation, sensitivity and platform timeline and download the report.
4. **Reproducible and honest.** One command to run, a metadata JSON per report, tests, and an explicit limitations page. A real-data run (even one region, one decade) is worth more than any extra feature.
5. **Demo script (3 minutes):** pick an area, show calendar and same-month years, show an anomaly with its evidence, open Sensor Intelligence to show why raw counts mislead (ratio and platform changes), show the S-NPP to NOAA transition, generate the PDF, download CSV.
6. **Avoid:** claims of validation on synthetic data, "fire danger" wording, unique-fire counts, mixing burned area into the index, decorative features that delay real data.
7. **Accessibility and robustness:** keyboard-usable map controls, text alternatives to colour, reduced-motion, readable on a laptop, a bundled small real-data sample so the demo works offline.

---

## PART 6. TEST AND QUALITY PLAN

- Keep all existing tests; run the full suite before and after each increment.
- Golden-file test on a small REAL FIRMS CSV committed with its provenance note (public NASA data; check licence and attribution).
- Unit tests for every formula (ratio, quartiles, sMAPE, bias, share), leakage, zero denominators, incomplete years, platform start/end, NRT/SP join, type filter, footprint geometry.
- API tests for invalid geometry, empty areas, platform selection errors.
- Real-browser tests (Playwright) on desktop, laptop and tablet widths: map, draw, dates, calendar, Sensor Intelligence, report download. A jsdom pass is not a visual check.
- Report tests: PDF text contains the selected area, dates, platforms and attribution; numbers equal the API.

---

## PART 7. FINAL OUTPUT REQUIRED FROM THE AGENT

1. Files changed; features implemented; formulas; test results (counts, failed, skipped).
2. Whether real NASA data was run (state "no" unless it was), and exactly what remains synthetic-only.
3. Windows commands to install, run, test and demo.
4. Status table with only COMPLETE / PARTIAL / BLOCKED / NOT IMPLEMENTED, each with evidence.
5. Known limitations.

Begin with PART 4 item 1 if a MAP_KEY is available; otherwise begin with items 2 to 6 and mark real-data items BLOCKED.
