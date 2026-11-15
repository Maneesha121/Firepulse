# Observation quality: noise, outliers and filter sensitivity

Code: `firepulse/quality.py` (flags, profiles), `firepulse/clean.py` (layers), `firepulse/sensitivity.py` (comparison),
settings in `firepulse/config.py`. Tests: `tests/test_quality.py`. Everything below is tested on synthetic data only;
no real NASA data has been processed with it yet.

## Three layers, kept apart

| Layer | What happens | Reversible? |
|---|---|---|
| 1. Invalid / redundant records | Removed: non-numeric or impossible coordinates, unparseable dates, exact duplicate rows **within one source** | Records and reasons are written to `data/clean/quality/<sensor>_rejected.csv.gz`; raw files are untouched |
| 2. Scope | Removed: outside the processing region, before the configured product start | Same |
| 3. Optional analytical filter | A **profile** (`config.QUALITY_PROFILES`) decides which valid records enter the calendar, ratio and anomalies | Yes: pick another profile, nothing is deleted |

Raw downloads in `data/raw/` are never modified. `data/clean/all_valid/<sensor>.csv.gz` holds every valid record with its
original confidence, FRP, source, platform, type, scan and track. **Flags live in a separate table**
(`data/clean/quality/<sensor>_flags.csv.gz`, joined on `rec_id` = `source/file#row`). `data/clean/<sensor>.csv.gz` holds only
what the active profile keeps (same schema as before plus `rec_id`).

SP and NRT copies of a detection are never merged silently: exact-duplicate removal looks inside one source only; the same
detection in two sources is flagged (`dup_cross_source`).

## Flags (none removes a record)

| Requirement | Flag(s) |
|---|---|
| 1 Invalid coordinates / timestamps | removed (layer 1); kept-but-flagged: `null_island`, `acq_time_invalid`, `future_date` |
| 2 Duplicate records from source identifiers and acquisition attributes | `dup_key_conflict` (same source, location, date, time, platform, different attributes), `dup_cross_source`, `dup_cross_source_later` |
| 3 Suspicious / near-duplicate detections | `near_duplicate`, `near_duplicate_later` (same platform, same date, within 10 min and 500 m MODIS / 150 m VIIRS) |
| 4 FRP | `frp_missing`, `frp_negative`, `frp_zero`, `frp_extreme_high`, `frp_extreme_uncorroborated` |
| 5 Confidence classes | `conf_class` (low / nominal / high / unknown), `conf_low`, `conf_invalid`; raw confidence never changed |
| 6 Day/night and context | `daynight_invalid`, `daynight_time_mismatch`; day/night shares and FRP by platform in the report |
| 7 Isolation (exploratory) | `n_neighbours`, `isolated`: no other detection (either family, any platform) within 5 km and +/- 2 days |
| 8 Source-specific | `viirs_low_night_outside_documented_area`, `type_not_vegetation`, `type_undocumented`, `large_pixel`; per-platform table |

### What the documentation says, and what was not verified
Read on the NASA FIRMS attribute page (retrieved 2026-11-14): MODIS confidence is 0-100 % and assigned to three classes;
VIIRS confidence is low / nominal / high; low-confidence **night** VIIRS pixels occur only between 11 E and 110 W and 7 N to
55 S (used for `viirs_low_night_outside_documented_area`, read as "eastward from 11 E to 110 W"); FRP is pixel-integrated
power in MW; `type` 0-3 meanings; `type` is stated to be available only for MODIS standard-quality data.
**Not verified here:** the numeric MODIS class limits (30 / 80 are the commonly cited values, configurable in
`MODIS_CONF_CLASSES`) and whether VIIRS SP files carry a `type` column. No document read states that high FRP is an error,
so high FRP is only flagged statistically (log-FRP above median + 5 x 1.4826 MAD per sensor and platform, at least 100
records) and is never excluded by any built-in profile.

### Isolation caveats
Isolation is not assessed for records within 5 km of the edge of the processing region or within 2 days of the first or last
date in the data (neighbours cannot be seen there). Gaps in coverage can make a detection look isolated. A pair of near-duplicates
counts as neighbours for each other. In the synthetic demo about 80 % of records are "isolated", which is exactly why this flag
must not be a deletion rule.

## Profiles

`baseline` (active by default, the rules of earlier versions), `all_valid`, `no_type_filter` (isolates the unverified
type-0 assumption), `high_confidence`, `default_no_duplicates`, `default_valid_frp`, `default_no_isolated` (exploratory only).
Choose the active one with `python run_pipeline.py --profile all_valid` (or `FIREPULSE_QUALITY_PROFILE`).
Add your own in `config.QUALITY_PROFILES`.

## Sensitivity analysis

`/api/quality` (and `data/quality.json` for the whole region) applies every profile to the same valid observations and recomputes
monthly counts, the VIIRS/MODIS ratio (area ratio when the area has enough usable overlap months, otherwise regional, per profile),
the harmonised index and the robust anomaly. Each profile is compared with the active profile: records kept, ratio, median and
maximum percent change of the index, correlation, and anomaly months that appear or disappear (Jaccard agreement).
A profile that keeps fewer records is not "more accurate". Unknown months stay `null`/empty everywhere, never zero.

## Reports and exports
`data/clean/quality_report.json` (removal steps with kinds, flag counts per sensor and platform, confidence classes, day/night,
FRP statistics and thresholds, retained / excluded per profile and per rule) and, in `data/out/`: `quality_flags_summary.csv`,
`quality_profiles_summary.csv`, `quality_sensitivity_monthly.csv`, `quality_sensitivity_summary.csv`. The page adds a
sensitivity CSV with header lines naming the data origin, area, dates, profiles and baseline.

## Limits
All thresholds are engineering choices. Duplicate judgements have no official record id to rely on. Percent changes in sparse
months are unstable. The ratio is an observed, area- and period-specific relationship, not a constant. The sensitivity view shows
spread across rules; it is not an uncertainty interval.
