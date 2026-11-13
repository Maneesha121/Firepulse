# Methodology

This file documents the calculations behind FirePulse. Stage 5 (Sensor Intelligence) is described in full; earlier
stages are summarised in the README. **All thresholds are engineering choices, not published standards.** No
research papers are cited here because their bibliographic details have not been verified; use Semantic Scholar or
arXiv to find and verify sources before citing any.

## What is measured

A *detection* is a satellite hotspot record that passed the filters in `firepulse/clean.py`. A difference between MODIS and
VIIRS detections is a difference in **observed detections**. It is not evidence of a difference in actual fire occurrence,
burned area or fire danger. Ratios below are **observed detection ratios for one area and period**; they are not universal
sensor correction factors, and the harmonised index is a MODIS-equivalent *index*, not a physical fire count.

## Data flow (one pipeline)

`area.analyze` -> `area.full_series` (monthly counts per sensor family and per platform inside the selection)
-> `area._choose_tables` (calibration: AREA or REGION) -> `harmonize.harmonize` (index)
-> `sensor_transition.build` (Stage 5 section, returned as `sensor_intelligence` in the `/api/area` response).
The web page only draws what the API returns.

## Definitions

- **Platform identity.** TERRA, AQUA (MODIS); SNPP, NOAA20, NOAA21 (VIIRS); UNKNOWN when the `satellite` value is not recognised.
  Platform counts are never merged before platform-level statistics are computed.
- **Platform availability.** A platform-month is *available* when its sensor family has OBSERVED_* status for that month
  **and** the month lies between the platform's first and last detection in the processed record. These first/last
  months are inferred from the data, not official mission dates. Unavailable platform-months are `null`, never 0.
- **Usable overlap month.** Both sensor families observed (not MISSING_DATA / INCOMPLETE_PERIOD / INSUFFICIENT_EVIDENCE) and
  MODIS count >= 5 (`MIN_COUNT`). Implemented once in `harmonize.classify_overlap`; the existing `ratio_tables` uses the same rule.
- **Ratio status per month.** `USABLE`, `ZERO_DENOMINATOR` (MODIS = 0, no ratio), `LOW_DENOMINATOR` (MODIS 1-4: ratio shown as
  *unstable*, never used), `NOT_BOTH_OBSERVED` (no ratio).
- **Platform selection.** All five ticked = FAMILY mode (existing family totals, composition changes are reported). A subset is
  STRICT: a month counts only if every ticked platform of that family is available, so turn-on dates cannot leak into a ratio.
  The harmonised index always uses all available platforms.

## A. Monthly comparison

Per month in the selected range: MODIS count, VIIRS count, raw combined = MODIS + VIIRS (a mixed-scale sum, labelled as such),
harmonised index `VIIRS / r(m)` after the splice month (or MODIS before it) with band `VIIRS / q75` to `VIIRS / q25`, and the data
status. Missing and incomplete months are `null`; periods are listed explicitly.

## B. Ratio by calendar month

For calendar month *m*, over usable overlap months **in the selected date range**:
`ratio = VIIRS / MODIS`; median, 25th and 75th percentile (linear interpolation, same as `harmonize.ratio_tables`).
Reported with the number of usable observations, number of distinct years (equal by construction for monthly data),
and counts of excluded zero- and low-denominator months. Evidence label: fewer than 5 usable years = `INSUFFICIENT_EVIDENCE`
(no ratio computed), 5-9 = `EXPLORATORY`, 10+ = `ADEQUATE` (still descriptive). The whole-record version is also returned
because it is what the harmonised index uses; the index therefore does not change with the date range.

## C. Ratio over time

The monthly ratio series (usable months), unstable months (hollow) and, per year, the median ratio and the pooled ratio
`sum(VIIRS) / sum(MODIS)` over usable months when the year has >= 6 usable months. The overlap period is
the first to last month with both sensors observed. A descriptive Spearman rank correlation of year versus the annual median
ratio *relative to its calendar-month median* is reported when >= 5 years exist. There is no significance test and no causal claim.
Changes in the platform mix (for example a new VIIRS platform appearing) are listed because they can move the ratio.

## D. Platform contribution

Absolute detections and `share = platform detections / total detections of all platforms with data` over the selected range, per
year and for the overlap period only. Platforms with no data are `UNAVAILABLE` (null, no share). A higher share means more
**detections**, not more fires; platforms differ in resolution, overpass time and observing period.

## E. Leave-one-year-out validation

For each held-out year *y*: ratio tables are fitted on the other years only (`ratio_tables(..., exclude_year=y)`, which also
fixes the global fallback ratio), then each usable month of *y* is predicted as `VIIRS / r(m)` and compared with actual MODIS.
A fit needs >= 5 other usable years, otherwise the year is `NO_CALIBRATION`. Metrics need >= 6 valid months
(`INSUFFICIENT_VALID_MONTHS` otherwise; all metrics are null):

- sMAPE = mean(200 * |p - a| / (|p| + |a|)), range 0-200 %.
- bias = sum(p) - sum(a) (detections); absolute bias = |bias|; bias % = 100 * (sum(p) / sum(a) - 1).
- Pearson correlation of predicted vs actual months, only if both series vary; dominated by the seasonal cycle.
- Baseline: sMAPE of predicting each month with the median MODIS of the same calendar month in other years (needs >= 5 years).

Held-out years shown are those in the selected date range; each is still predicted with a ratio fitted on all other overlap years
of the record. Only months with MODIS >= 5 are evaluated, which flatters the method slightly (months with very low MODIS are excluded).
This is cross-validation across years, not forward-in-time forecasting.

**Calibration source.** If the selection has >= 36 usable overlap months the area's own ratio is used (`AREA`; validation fits on
the area's other years). Otherwise the regional ratio is applied (`REGION`) and validation uses the regional ratio fitted without the
held-out year (`REGION_TRANSFER_LOYO`), applied to the area's VIIRS counts. In a platform subset the area's own subset data are used
and evidence labels apply.

## F. Sensitivity

Time windows (whole record, selected range, earlier and later half of the overlap years, plus drop-one-year medians) and platform
pairs (Terra / Aqua / both against S-NPP / NOAA-20 / NOAA-21) each give a global median ratio when they have >= 12 usable
months. The relative spread (max - min) / reference is flagged `LARGE_SPREAD` above 25 %. It describes how much the estimate moves; it is not a
confidence interval.

## G. Platform timeline and product streams

`platform_timeline` lists, for each platform, NASA-documented facts (launch, documented start/end, with the source page and retrieval date;
blank when not verified) next to the first and last month with a detection in the processed record. They are different evidence and are not merged.
A flag is raised if detections precede a documented start or follow a documented end. `platform_endings` lists platforms with no detections after a month
while their sensor family continues (family totals then come from the remaining platforms). `product_streams` counts detections per platform and
FIRMS product stream (NRT or SP, taken from the source name, never guessed) and warns when a platform mixes streams, because NRT uses predictive orbit
information and may differ from standard processing.

## Provenance

`sensor_intelligence.provenance` states whether the data are `SYNTHETIC_DEMO` or `NASA_FIRMS`. Synthetic results are labelled
illustrative only and never describe real sensor performance. The repository has not been run against real NASA files; see
`docs/limitations.md`.

## Thresholds

`min_modis_count_for_ratio` 5 | `min_years_per_calendar_month` 5 | exploratory below 10 years | annual ratio >= 6 months | trend >= 5 years |
validation year >= 6 valid months and >= 5 fit years | sensitivity row >= 12 months | spread flag 25 % | area calibration >= 36 overlap months.
They are returned in every response under `thresholds`.
