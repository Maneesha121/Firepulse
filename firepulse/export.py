"""Write the files the website reads (web/data) and human-readable CSVs (data/out)."""
import json, datetime as dt
import pandas as pd
from .config import GRID, BBOX, WEB_DATA, OUT, SPLICE, MIN_BASELINE, DEMO, MODIS_MIN_CONF, ACTIVE_PROFILE, QUALITY_PROFILES


def export_web(agg, region, tables, val_summary, avail, statuses=None, cleaning=None, product_availability=None, source_coverage=None):
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    months = list(region.index)
    midx = {str(p): i for i, p in enumerate(months)}
    a = agg[agg["month"].isin(midx)]
    piv = a.pivot_table(index=["ci", "cj", "month"], columns="sensor", values="n",
                        aggfunc="sum", fill_value=0).reset_index()
    for k in ("modis", "viirs"):
        if k not in piv:
            piv[k] = 0
    cells = piv[["ci", "cj"]].drop_duplicates().reset_index(drop=True)
    cid = {(r.ci, r.cj): i for i, r in cells.iterrows()}
    rec = [[cid[(r.ci, r.cj)], midx[r.month], int(r.modis), int(r.viirs)] for r in piv.itertuples()]
    json.dump({"grid": GRID, "cells": [[round(r.ci * GRID, 4), round(r.cj * GRID, 4)] for r in cells.itertuples()],
               "rec": rec}, open(WEB_DATA / "cells.json", "w"), separators=(",", ":"))
    sp = midx.get(str(pd.Period(SPLICE, "M"))) if SPLICE else None
    meta = {"demo": DEMO, "generated": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "grid": GRID, "bbox": list(BBOX), "months": [str(p) for p in months],
            "avail": {k: [midx[str(a)], midx[str(b)]] for k, (a, b) in avail.items()},
            "splice_idx": sp, "ratios": tables, "validation": val_summary,
            "data_origin": "SYNTHETIC_DEMO" if DEMO else "NASA_FIRMS",
            "status": {k: [str(v) for v in st["status"]] for k, st in (statuses or {}).items()},
            "coverage_evidence": {k: (st["evidence"].mode().iat[0] if len(st) else "NONE") for k, st in (statuses or {}).items()},
            "product_availability": product_availability, "source_coverage": source_coverage or [],
            "cleaning": cleaning, "ratio_basis": "REGION (whole processing region)",
            "min_baseline": MIN_BASELINE, "filters": {"modis_min_conf": MODIS_MIN_CONF,
                                                      "viirs_keep": ["nominal", "high"]},
            "active_profile": (cleaning or {}).get("active_profile", ACTIVE_PROFILE),
            "quality_profiles": {k: {"label": v["label"], "description": v["description"], "exploratory": bool(v.get("exploratory"))}
                                 for k, v in QUALITY_PROFILES.items()},
            "evidence_by_month": {k: [str(v) for v in st["evidence"]] for k, st in (statuses or {}).items()}}
    json.dump(meta, open(WEB_DATA / "meta.json", "w"), indent=1)


def export_tables(region, hz, anomalies, val_df, statuses=None):
    OUT.mkdir(parents=True, exist_ok=True)
    cal = region.join(hz).join(anomalies)
    for k, st in (statuses or {}).items():
        cal[f"{k}_status"] = st["status"]
    cal["data_origin"] = "SYNTHETIC_DEMO" if DEMO else "NASA_FIRMS"
    cal.index = cal.index.astype(str)
    cal.to_csv(OUT / "regional_calendar.csv")
    if not val_df.empty:
        val_df.to_csv(OUT / "validation_loo.csv", index=False)


def export_quality(qrep, sens_region):
    """Quality report (counts per rule) and the region-wide filter sensitivity, as JSON for the page and CSV for people."""
    OUT.mkdir(parents=True, exist_ok=True)
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    json.dump({"report": qrep, "sensitivity_region": sens_region}, open(WEB_DATA / "quality.json", "w"), separators=(",", ":"), default=str)
    rows = []
    for k, per in qrep.get("flags", {}).items():
        for name, v in per.items():
            rows.append({"sensor": k, "flag": name, "records_flagged": v["n"], "share_pct": v["share_pct"],
                         "by_platform": json.dumps(v["by_platform"]), "data_origin": qrep.get("data_origin")})
    pd.DataFrame(rows).to_csv(OUT / "quality_flags_summary.csv", index=False)
    rows = []
    for pid, prof in qrep.get("profiles", {}).items():
        for k, v in prof["sensors"].items():
            rows.append({"profile": pid, "label": prof["label"], "exploratory": prof["exploratory"], "active": prof["active"], "sensor": k,
                         "valid_records": v["valid_records"], "retained": v["retained"], "excluded": v["excluded"],
                         "rules": "; ".join(f"{r['rule']}: fails={r['records_failing_rule']}, removed_in_sequence={r['removed_in_sequence']}" for r in v["rules"]),
                         "data_origin": qrep.get("data_origin")})
    pd.DataFrame(rows).to_csv(OUT / "quality_profiles_summary.csv", index=False)
    if sens_region and sens_region.get("available"):
        rows = []
        for p in sens_region["profiles"]:
            for m in p["monthly"]:
                rows.append({"profile": p["id"], **m, "data_origin": sens_region["data_origin"]})
        pd.DataFrame(rows).to_csv(OUT / "quality_sensitivity_monthly.csv", index=False)       # empty cell = unknown, never 0
        rows = []
        for p in sens_region["profiles"]:
            va, r = p.get("vs_active") or {}, p.get("ratio") or {}
            rows.append({"profile": p["id"], "label": p["label"], "retained_records": p["records"]["retained"],
                         "ratio_median": r.get("median"), "usable_overlap_months": r.get("usable_overlap_months"), "ratio_basis": p["ratio_basis"],
                         "anomaly_months_assessed": p["anomalies"]["months_assessed"], "much_above": len(p["anomalies"]["much_above"]),
                         "much_below": len(p["anomalies"]["much_below"]), **{f"vs_active_{k}": v for k, v in va.items() if not isinstance(v, list)}})
        pd.DataFrame(rows).to_csv(OUT / "quality_sensitivity_summary.csv", index=False)
