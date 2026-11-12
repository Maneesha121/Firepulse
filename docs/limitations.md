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

## Not yet implemented (from the master prompt)
Sensor-transition panel and ratio/contribution charts, harmonisation alternatives (monthly/seasonal/quantile) and sensitivity table, anomaly classification labels
(SENSOR_SENSITIVE / METHOD_SENSITIVE), grid-cell/anomaly/sensor map modes and time slider, grid-cell GeoJSON export, data dictionary and methodology exports,
architecture/evaluation/research-evidence docs, observation-level Aqua/SNPP matching check, second region run, CI.
