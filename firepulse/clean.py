"""Load raw FIRMS CSVs, apply documented quality filters, standardise columns.

Every removal is counted per rule and written to <CLEAN>/cleaning_report.json (nothing is dropped silently).
"""
import json
import numpy as np, pandas as pd
from .config import (RAW, CLEAN, SOURCES, EXTRA_SOURCES, BBOX, MODIS_MIN_CONF, VIIRS_KEEP, MODIS_START,
                     VIIRS_START, DEMO, FIRE_TYPE_DOC, FIRE_TYPE_KEEP, FIRE_TYPE_BASIS)
from . import schema

START = {"modis": MODIS_START, "viirs": VIIRS_START}


def folders_for(key):
    """Raw folders feeding one sensor family (primary source + any configured extras)."""
    names = [SOURCES[key]] + [n for n, fam in EXTRA_SOURCES.items() if fam == key]
    return [RAW / n for n in names]


def load_raw(key):
    frames = []
    for folder in folders_for(key):
        for f in sorted(folder.glob("*.csv")) if folder.exists() else []:
            if f.stat().st_size > 0:
                d = pd.read_csv(f, dtype={"confidence": str})
                d["src"] = folder.name
                frames.append(d)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _type_breakdown(col):
    """Raw FIRMS 'type' codes with counts and the documented meaning; undocumented codes are labelled, never interpreted."""
    out = []
    for k, n in col.value_counts(dropna=False).sort_index().items():
        code = None if pd.isna(k) else (int(k) if float(k).is_integer() else float(k))
        out.append({"raw_code": code, "count": int(n), "kept": code in FIRE_TYPE_KEEP,
                    "documented_meaning": FIRE_TYPE_DOC.get(code, "undocumented code (kept raw, not interpreted)"), "basis": FIRE_TYPE_BASIS})
    return out


def clean(df, key, report=None):
    """Return cleaned points. ``report`` (dict) receives row accounting if given."""
    rep = report if report is not None else {}
    rep.update(sensor=key, rows_read=int(len(df)), steps=[])
    if df.empty:
        return df

    def step(name, rule, keep):
        nonlocal df
        removed = int((~keep).sum())
        rep["steps"].append({"step": name, "rule": rule, "removed": removed})
        df = df[keep]

    # exact duplicate rows (e.g. overlapping download windows) - counted, not silent
    keep = ~df.duplicated(subset=[c for c in df.columns if c != "src"])
    step("duplicate_rows", "exact duplicate rows across raw files", keep)
    lat = pd.to_numeric(df["latitude"], errors="coerce")
    lon = pd.to_numeric(df["longitude"], errors="coerce")
    step("invalid_coordinate_format", "latitude/longitude not numeric", lat.notna() & lon.notna())
    lat, lon = lat.loc[df.index], lon.loc[df.index]
    step("coordinates_out_of_range", "|lat|>90 or |lon|>180", (lat.abs() <= 90) & (lon.abs() <= 180))
    dates = pd.to_datetime(df["acq_date"], errors="coerce")
    step("invalid_date", "acq_date not parseable", dates.notna())
    if "type" in df.columns:                      # 0 = presumed vegetation fire (see config.FIRE_TYPE_DOC)
        rep["type_breakdown"] = _type_breakdown(df["type"])
        step("type_filter", "keep type == 0 (presumed vegetation fire)", df["type"].isin(FIRE_TYPE_KEEP))
    if key == "modis":
        step("confidence_filter", f"MODIS confidence >= {MODIS_MIN_CONF} (assumption)",
             pd.to_numeric(df["confidence"], errors="coerce") >= MODIS_MIN_CONF)
    else:
        step("confidence_filter", f"VIIRS confidence in {sorted(VIIRS_KEEP)}",
             df["confidence"].astype(str).str.lower().isin(VIIRS_KEEP))
    w, s, e, n = BBOX
    step("study_region_bbox", f"inside processing region {BBOX}", df.latitude.between(s, n) & df.longitude.between(w, e))
    out = pd.DataFrame({
        "date": pd.to_datetime(df["acq_date"]).values,
        "lat": df["latitude"].values, "lon": df["longitude"].values,
        "frp": df["frp"].values if "frp" in df else np.nan,
        "daynight": df["daynight"].values if "daynight" in df else "",
        "sensor": key,
        "platform": (schema.normalise_platform(df["satellite"], key).values if "satellite" in df else "UNKNOWN"),
        "confidence_raw": df["confidence"].astype(str).values,
        "acq_time": df["acq_time"].values if "acq_time" in df else "",
        "src": df["src"].values,
        "data_origin": schema.data_origin(DEMO)})
    out["product_stream"] = schema.product_stream(df["src"])
    # The VIIRS source name is the documented FIRMS product identity. It fills platforms the 'satellite' column could not
    # map (UNKNOWN) and is cross-checked against it; a disagreement keeps the column value and is counted, never silent.
    from_src = pd.Series(schema.platform_from_src(df["src"]), index=out.index)
    fill = (out["platform"] == "UNKNOWN") & from_src.notna()
    conflict = (out["platform"] != "UNKNOWN") & from_src.notna() & (out["platform"] != from_src)
    out.loc[fill, "platform"] = from_src[fill]
    rep["platform_checks"] = {"filled_from_source_name": int(fill.sum()), "conflicts_satellite_vs_source": int(conflict.sum())}
    if conflict.any():
        print(f"WARNING: {int(conflict.sum())} {key} rows have a 'satellite' value that disagrees with the source name; check schema._PLATFORM_MAP")
    for raw_col, dst in (("version", "version"), ("scan", "scan"), ("track", "track"), ("type", "fire_type")):
        if raw_col in df.columns:
            out[dst] = df[raw_col].values
    out["month"] = out["date"].dt.to_period("M").astype(str)
    before = len(out)
    out = out[out["month"] >= START[key]]
    rep["steps"].append({"step": "before_product_start", "rule": f"month >= {START[key]} (configured product start)",
                         "removed": int(before - len(out))})
    rep["rows_kept"] = int(len(out))
    print(f"{key}: kept {len(out)} of {rep['rows_read']} detections after filters")
    return out.reset_index(drop=True)


def run():
    CLEAN.mkdir(parents=True, exist_ok=True)
    res, reports = {}, {}
    for key in SOURCES:
        rep = {}
        df = clean(load_raw(key), key, rep)
        reports[key] = rep
        if not df.empty:
            df.to_csv(CLEAN / f"{key}.csv.gz", index=False)
            res[key] = df
    (CLEAN / "cleaning_report.json").write_text(json.dumps(
        {"data_origin": schema.data_origin(DEMO), "sensors": reports}, indent=1))
    return res
