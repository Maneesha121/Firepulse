"""How much do the quality-filter choices change the monthly calendar, the VIIRS/MODIS ratio and the anomalies?

For one selection (or the whole processing region) every profile in config.QUALITY_PROFILES is applied to the SAME set of
valid observations, and the whole chain is recomputed: monthly counts -> ratio -> harmonised index -> robust anomaly.
Nothing here changes the observations or the flags, and no profile is presented as "the correct" one: the output shows how
far results move, relative to the profile that feeds the main calendar (the active profile).

Everything is a comparison of observed detections. A profile that removes more records is not "more accurate"; it answers a
different question (see docs/data_quality.md).
"""
import numpy as np, pandas as pd
from . import harmonize, anomaly, quality, coverage
from .config import QUALITY_PROFILES, MIN_BASELINE

ANOM_Z = 2.0          # |robust z| at or above this = "much above / below normal" (same cut as anomaly.band)
MAX_LISTED = 24       # months listed per anomaly-difference list


def _f(v):
    return None if v is None or (isinstance(v, (float, np.floating)) and not np.isfinite(v)) else float(v)


def _rows(base, hz, z, rng_mask):
    out = []
    for i, p in enumerate(base.index):
        if rng_mask[i]:
            out.append({"month": str(p), "modis": _f(base["modis"].iloc[i]), "viirs": _f(base["viirs"].iloc[i]),
                        "harmonized": _f(hz["harmonized"].iloc[i]), "z": _f(z["z"].iloc[i]), "band": z["band"].iloc[i]})
    return out


def _one(ds, pid, prof, sel_mask, rng_mask, baseline, series_fn, tables_fn):
    keep = ds.profile_keep(pid)
    pts = ds.q_points[sel_mask & keep]
    base = series_fn(ds, pts)
    ev = getattr(ds, "evidence_by_month", None)
    for k in ("modis", "viirs"):                       # a month whose "observed" status rests on rows alone is unknown if the profile leaves no rows
        if ev and k in ev:
            rows_only = (ds.status[k] == "OBSERVED_WITH_DETECTIONS").to_numpy() & (np.asarray(ev[k]) == "NONE") & (base[k].to_numpy() == 0)
            if rows_only.any():
                base.loc[rows_only, k] = np.nan
    tables, basis = tables_fn(ds, base, pid)
    reg = base[["modis", "viirs"]]
    if tables is None:
        hz = pd.DataFrame({"harmonized": np.nan, "h_lo": np.nan, "h_hi": np.nan, "source_used": ""}, index=base.index)
    else:
        hz = harmonize.harmonize(reg, tables, splice=ds.splice)
    past = baseline == "past_only"
    z = anomaly.series_anomalies(hz["harmonized"], past_only=past)
    res = {"id": pid, "label": prof["label"], "description": prof["description"], "exploratory": bool(prof.get("exploratory")),
           "records": {"retained": int(len(pts)), "modis": int((pts["sensor"] == "modis").sum()), "viirs": int((pts["sensor"] == "viirs").sum()),
                       "by_platform": {p: int(c) for p, c in pts["platform"].value_counts().items()}},
           "monthly": _rows(base, hz, z, rng_mask),
           "ratio_basis": basis}
    if tables is None:
        res["ratio"] = None
        res["ratio_note"] = "No usable overlap months under this profile: the VIIRS/MODIS ratio, and therefore the harmonised index, cannot be computed."
    else:
        g = tables["global"]
        res["ratio"] = {"median": _f(g["med"]), "q25": _f(g["q25"]), "q75": _f(g["q75"]), "usable_overlap_months": int(g["n"]),
                        "by_calendar_month": [(_f(tables["by_month"][m]["med"]) if m in tables["by_month"] else None) for m in range(1, 13)]}
    zz = z["z"].to_numpy(float)
    sel = rng_mask & np.isfinite(zz)
    months = np.array([str(p) for p in base.index])
    res["anomalies"] = {"months_assessed": int(sel.sum()), "much_above": months[sel & (zz >= ANOM_Z)].tolist(),
                        "much_below": months[sel & (zz <= -ANOM_Z)].tolist()}
    res["_h"] = hz["harmonized"].to_numpy(float)
    res["_flagged"] = set(months[sel & (np.abs(zz) >= ANOM_Z)].tolist())
    return res


def _compare(p, a, rng_mask):
    """Differences of profile ``p`` against the active profile ``a`` over the selected months."""
    hp, ha = p["_h"][rng_mask], a["_h"][rng_mask]
    both = np.isfinite(hp) & np.isfinite(ha)
    c = {"months_compared": int(both.sum()), "index_correlation": None, "median_abs_change_pct": None, "max_abs_change_pct": None,
         "total_index_change_pct": None, "ratio_change_pct": None, "anomaly_jaccard": None, "anomaly_only_here": [], "anomaly_only_active": []}
    if both.sum() >= 3 and np.std(hp[both]) > 0 and np.std(ha[both]) > 0:
        c["index_correlation"] = _f(np.corrcoef(hp[both], ha[both])[0, 1])
    pos = both & (ha > 0)
    if pos.any():
        ch = np.abs(hp[pos] - ha[pos]) / ha[pos] * 100
        c["median_abs_change_pct"], c["max_abs_change_pct"] = _f(np.median(ch)), _f(np.max(ch))
    if both.any() and ha[both].sum() > 0:
        c["total_index_change_pct"] = _f((hp[both].sum() / ha[both].sum() - 1) * 100)
    if p.get("ratio") and a.get("ratio") and a["ratio"]["median"]:
        c["ratio_change_pct"] = _f((p["ratio"]["median"] / a["ratio"]["median"] - 1) * 100)
    sp, sa = p["_flagged"], a["_flagged"]
    if sp or sa:
        c["anomaly_jaccard"] = _f(len(sp & sa) / len(sp | sa))
    c["anomaly_only_here"] = sorted(sp - sa)[:MAX_LISTED]
    c["anomaly_only_active"] = sorted(sa - sp)[:MAX_LISTED]
    return c


def analyze(ds, sel=None, a=None, b=None, baseline="all_other_years", series_fn=None, tables_fn=None, profiles=None):
    """Sensitivity of the calendar, ratio and anomalies to the quality profile.

    ``sel`` None = whole processing region. ``a``/``b`` = first/last month (Period) shown; None = whole record.
    ``series_fn(ds, points) -> monthly frame`` and ``tables_fn(ds, base, profile_id) -> (tables|None, basis text)`` are supplied by area.py.
    """
    profiles = profiles or QUALITY_PROFILES
    if getattr(ds, "q_points", None) is None:
        return {"available": False, "data_origin": ds.origin,
                "reason": getattr(ds, "quality_error", None) or "No quality layer found. Re-run python run_pipeline.py (it writes data/clean/all_valid and data/clean/quality).",
                "limitations": []}
    q = ds.q_points
    sel_mask = ds.mask_q(sel) if sel is not None else np.ones(len(q), bool)
    first, last = ds.months[0], ds.months[-1]
    a, b = a or first, b or last
    rng_mask = np.asarray((ds.months >= a) & (ds.months <= b))
    active = ds.active_profile if ds.active_profile in profiles else "baseline"
    results = {pid: _one(ds, pid, prof, sel_mask, rng_mask, baseline, series_fn, tables_fn) for pid, prof in profiles.items()}
    act = results[active]
    for pid, r in results.items():
        r["vs_active"] = None if pid == active else _compare(r, act, rng_mask)
    all_valid = int(sel_mask.sum())
    for r in results.values():
        r["records"]["excluded_vs_all_valid"] = all_valid - r["records"]["retained"]
        r["records"]["share_retained_pct"] = _f(100 * r["records"]["retained"] / all_valid) if all_valid else None
        r.pop("_h"); r.pop("_flagged")
    fl = {name: int(q.loc[sel_mask, "flag_" + name].sum()) for name in quality.FLAG_INFO}
    return {
        "available": True, "data_origin": ds.origin, "active_profile": active, "baseline_mode": baseline,
        "range": {"start": str(a), "end": str(b)}, "valid_records_in_selection": all_valid,
        "selection": "whole processing region" if sel is None else sel.description,
        "flags": [{"flag": k, "label": quality.FLAG_INFO[k][0], "group": quality.FLAG_INFO[k][1], "meaning": quality.FLAG_INFO[k][2],
                   "records": n, "share_pct": _f(100 * n / all_valid) if all_valid else None,
                   "exploratory": k in quality.EXPLORATORY_FLAGS} for k, n in fl.items()],
        "profiles": list(results.values()),
        "min_baseline_years": MIN_BASELINE,
        "notes": [
            "Each profile is applied to the same valid observations and the whole chain is recomputed: monthly counts, VIIRS/MODIS ratio, harmonised index, anomaly.",
            "Differences are shown against the active profile (the one behind the main calendar). A larger or smaller retained count is not 'more accurate'.",
            "Months without coverage evidence stay unknown (null), never zero, under every profile.",
        ],
        "limitations": [
            "Flags are exploratory data-quality indicators. High FRP and isolated detections are not assumed to be errors.",
            "The observed/unknown status of a month comes from retrieval-window evidence, which does not depend on the filter. Only months that rest on rows alone (no download-window evidence) can become unknown under a stricter profile.",
            "Percent changes in months with very small counts can be large and are not meaningful on their own; read them with the record counts.",
            "The VIIRS/MODIS ratio is an observed relationship for this area, period and profile, not a physical constant.",
        ],
    }
