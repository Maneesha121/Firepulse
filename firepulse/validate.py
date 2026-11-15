"""Validate raw FIRMS CSV files before processing (manual-import workflow).

Run:  python validate_inputs.py [folder]      (default folder: the RAW directory in config.py)
Reports, per file: columns present/missing, row count, invalid coordinates/dates, unknown platform codes,
confidence vocabulary. Nothing is modified or deleted.
"""
import json
import pandas as pd

REQUIRED = ["latitude", "longitude", "acq_date"]
EXPECTED = ["acq_time", "satellite", "confidence", "frp", "daynight", "version"]


def validate_file(path):
    rep = {"file": str(path), "ok": True, "problems": [], "notes": []}
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except Exception as e:   # unreadable / empty / malformed
        return {**rep, "ok": False, "problems": [f"cannot read file: {e}"], "rows": 0}
    cols = [c.strip().lower() for c in df.columns]
    df.columns = cols
    rep["rows"] = int(len(df))
    rep["columns"] = cols
    miss = [c for c in REQUIRED if c not in cols]
    if miss:
        return {**rep, "ok": False, "problems": [f"missing required columns: {miss}"]}
    rep["missing_expected_columns"] = [c for c in EXPECTED if c not in cols]
    lat = pd.to_numeric(df["latitude"], errors="coerce")
    lon = pd.to_numeric(df["longitude"], errors="coerce")
    bad_fmt = int((lat.isna() | lon.isna()).sum())
    bad_rng = int(((lat.abs() > 90) | (lon.abs() > 180)).sum())
    dates = pd.to_datetime(df["acq_date"], format="%Y-%m-%d", errors="coerce")
    rep.update(invalid_coordinate_format=bad_fmt, coordinates_out_of_range=bad_rng,
               invalid_dates=int(dates.isna().sum()),
               date_range=[str(dates.min().date()), str(dates.max().date())] if dates.notna().any() else None,
               exact_duplicate_rows=int(df.duplicated().sum()))
    if "satellite" in cols:
        rep["satellite_values"] = df["satellite"].value_counts().head(10).to_dict()
    if "confidence" in cols:
        rep["confidence_values_top"] = df["confidence"].value_counts().head(8).to_dict()
    if "version" in cols:
        rep["versions"] = df["version"].value_counts().head(5).to_dict()
        if df["version"].str.contains("NRT", case=False).any():
            rep["notes"].append("file contains NRT records: standard-processing data are preferred for history")
    for k in ("invalid_coordinate_format", "coordinates_out_of_range", "invalid_dates"):
        if rep[k]:
            rep["problems"].append(f"{rep[k]} rows with {k.replace('_', ' ')} (will be removed and counted by clean.py)")
    return rep


def validate_folder(folder):
    files = sorted(p for p in folder.rglob("*.csv") if p.stat().st_size > 0)
    return {"folder": str(folder), "files_checked": len(files), "reports": [validate_file(f) for f in files],
            "empty_files": sorted(str(p) for p in folder.rglob("*.csv") if p.stat().st_size == 0)}


def main(folder):
    out = validate_folder(folder)
    print(json.dumps(out, indent=1, default=str))
    bad = [r for r in out["reports"] if not r["ok"]]
    return 1 if bad or not out["files_checked"] else 0
