"""Write the files the website reads (web/data) and human-readable CSVs (data/out)."""
import json, datetime as dt
import pandas as pd
from .config import GRID, BBOX, WEB_DATA, OUT, SPLICE, MIN_BASELINE, DEMO, MODIS_MIN_CONF


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
                                                      "viirs_keep": ["nominal", "high"]}}
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
