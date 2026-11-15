"""Stage 6: stream-aware check of the NRT -> standard-processing (SP) join, per VIIRS platform.

Why: FIRMS NRT uses predictive orbit information and NOAA-21 has no SP stream, so the recent record of a platform can be
NRT while its history is SP. If the two streams differ systematically, the join looks like a level shift in the
VIIRS/MODIS ratio and leaks straight into the harmonised index.

Method (an ENGINEERING CHOICE, not a published standard; thresholds are reported in the output):
  1. For each VIIRS platform, label every month by the product stream(s) present in the whole processing region:
     SP, NRT, or MIXED (both, or an unknown stream). MIXED months are excluded from both arms.
  2. Platform ratio r(m) = platform detections / MODIS detections for months where the platform is available, both
     sensor families are observed and MODIS >= MIN_COUNT (the same usable-month rule as the family ratio).
  3. For every usable NRT month, compare r(m) with the median SP ratio of the SAME calendar month (needs
     >= MIN_SP_YEARS SP years), which removes the seasonal cycle from the comparison.
  4. shift = median(r_nrt / r_sp_same_month) - 1, with the interquartile range of the individual comparisons.
     Needs >= MIN_PAIRS compared months, otherwise INSUFFICIENT_EVIDENCE (no number is reported).

A flagged shift is a detection-level difference. It can come from NRT versus standard processing, but also from real
changes in activity, platform ageing, filters or sampling; this check cannot tell which. Unknown is null, never 0.
"""
import numpy as np, pandas as pd
from . import harmonize, sensor_transition
from .config import MIN_COUNT

MIN_PAIRS = 6            # compared NRT months needed before a shift is reported
MIN_SP_YEARS = 2         # SP years needed for a calendar month to serve as reference
SHIFT_FLAG = 0.25        # |shift| at or above this is flagged (same size as the 25 % spread flag used elsewhere)
VIIRS_PLATFORMS = ("SNPP", "NOAA20", "NOAA21")
THRESHOLDS = {"min_compared_nrt_months": MIN_PAIRS, "min_sp_years_per_calendar_month": MIN_SP_YEARS,
              "flag_abs_shift": SHIFT_FLAG, "min_modis_count": MIN_COUNT}


def stream_labels(ds, platform):
    """Series(Period -> 'SP'|'NRT'|'MIXED') for months that have rows of this platform anywhere in the processing region."""
    pts = ds.points
    sub = pts[pts["platform"] == platform]
    if sub.empty or "product_stream" not in sub.columns:
        return pd.Series(dtype=object)
    g = sub.groupby("month")["product_stream"].agg(lambda s: set(s))
    lab = g.map(lambda st: next(iter(st)) if st in ({"SP"}, {"NRT"}) else "MIXED")
    lab.index = pd.PeriodIndex(lab.index, freq="M")
    return lab


def _platform(ds, base, avail, p, a, b):
    lab = stream_labels(ds, p)
    row = {"platform": p, "label": sensor_transition.LABEL[p], "first_nrt_month": None, "last_sp_month": None,
           "sp_months": 0, "nrt_months": 0, "mixed_months": 0, "compared_months": 0, "status": None,
           "shift_pct": None, "shift_iqr_pct": None, "nrt_months_in_range": 0}
    if lab.empty:
        row["status"] = "NO_STREAM_INFORMATION"
        row["reason"] = "No detections with a recorded product stream for this platform."
        return row
    sp, nrt = lab[lab == "SP"], lab[lab == "NRT"]
    row.update(sp_months=int(len(sp)), nrt_months=int(len(nrt)), mixed_months=int((lab == "MIXED").sum()),
               first_nrt_month=str(nrt.index.min()) if len(nrt) else None, last_sp_month=str(sp.index.max()) if len(sp) else None)
    row["nrt_months_in_range"] = int(((nrt.index >= a) & (nrt.index <= b)).sum())
    if not len(nrt) or not len(sp):
        row["status"] = "NOT_APPLICABLE"
        row["reason"] = ("NRT-only in this record: there is no standard-processing reference, so a join cannot be tested." if len(nrt)
                         else "SP-only in this record: no NRT months to compare.")
        return row
    modis, plat = base["modis"], base["n_" + p].where(avail[p])
    ok = modis.notna() & plat.notna() & (modis >= MIN_COUNT)
    r = (plat / modis).where(ok)
    sp_r = r[r.index.isin(sp.index)].dropna()
    ref = {m: g for m, g in sp_r.groupby(sp_r.index.month) if len(g) >= MIN_SP_YEARS}
    rel = []
    for per, v in r[r.index.isin(nrt.index)].dropna().items():
        g = ref.get(per.month)
        if g is not None and g.median() > 0:
            rel.append(v / g.median())
    row["compared_months"] = len(rel)
    if len(rel) < MIN_PAIRS:
        row["status"] = "INSUFFICIENT_EVIDENCE"
        row["reason"] = (f"Only {len(rel)} NRT months could be compared with SP months of the same calendar month "
                         f"(minimum {MIN_PAIRS}); no shift is reported.")
        return row
    rel = np.array(rel)
    shift = float(np.median(rel) - 1)
    row.update(shift_pct=round(shift * 100, 1), shift_iqr_pct=[round(float(np.quantile(rel, .25) - 1) * 100, 1),
                                                                round(float(np.quantile(rel, .75) - 1) * 100, 1)])
    flagged = abs(shift) >= SHIFT_FLAG
    row["status"] = "LEVEL_SHIFT_FLAGGED" if flagged else "NO_LARGE_SHIFT_DETECTED"
    row["reason"] = (f"Median NRT/SP ratio comparison {shift * 100:+.1f}% (IQR {row['shift_iqr_pct'][0]:+.1f}% to {row['shift_iqr_pct'][1]:+.1f}%) "
                     f"over {len(rel)} months." + (" This is at or above the flag threshold." if flagged else
                                                   " Below the flag threshold; this does not prove the streams are equivalent."))
    return row


def build(ds, base, a, b):
    """-> dict with one row per VIIRS platform. ``base`` is area.full_series output for the selection (whole record)."""
    if "product_stream" not in ds.points.columns:
        return {"available": False, "rows": [], "thresholds": THRESHOLDS,
                "notes": ["NRT/SP join check not possible: cleaned data has no product_stream column (re-run the pipeline)."]}
    avail = sensor_transition.platform_availability(ds)
    rows = [_platform(ds, base, avail, p, a, b) for p in VIIRS_PLATFORMS]
    notes = []
    for r in rows:
        if r["status"] == "LEVEL_SHIFT_FLAGGED":
            notes.append(f"{r['label']}: the NRT months (from {r['first_nrt_month']}) sit {r['shift_pct']:+.1f}% from the SP level of the same calendar "
                         "months. A shift at the NRT join feeds the harmonised index; treat the NRT-period index as provisional. "
                         "The cause (processing, activity, filters) cannot be separated here.")
        elif r["status"] == "INSUFFICIENT_EVIDENCE":
            notes.append(f"{r['label']}: NRT/SP join not testable for this selection ({r['reason']})")
    return {"available": True, "rows": rows, "thresholds": THRESHOLDS, "notes": notes,
            "caution": "Observed detection-level comparison for this selection; not a validation of NRT against standard processing."}
