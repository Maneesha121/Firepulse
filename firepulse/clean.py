"""Load raw FIRMS CSVs, apply quality filters, standardise columns."""
import numpy as np, pandas as pd
from .config import RAW, CLEAN, SOURCES, BBOX, MODIS_MIN_CONF, VIIRS_KEEP, MODIS_START, VIIRS_START

START = {"modis": MODIS_START, "viirs": VIIRS_START}


def load_raw(key):
    folder = RAW / SOURCES[key]
    frames = [pd.read_csv(f, dtype={"confidence": str}) for f in sorted(folder.glob("*.csv"))
              if f.stat().st_size > 0]
    return pd.concat(frames, ignore_index=True).drop_duplicates() if frames else pd.DataFrame()


def clean(df, key):
    if df.empty:
        return df
    n0 = len(df)
    if "type" in df.columns:                      # 0 = presumed vegetation fire
        df = df[df["type"] == 0]
    if key == "modis":
        df = df[pd.to_numeric(df["confidence"], errors="coerce") >= MODIS_MIN_CONF]
    else:
        df = df[df["confidence"].astype(str).str.lower().isin(VIIRS_KEEP)]
    w, s, e, n = BBOX
    df = df[df.latitude.between(s, n) & df.longitude.between(w, e)]
    out = pd.DataFrame({
        "date": pd.to_datetime(df["acq_date"]).values,
        "lat": df["latitude"].values, "lon": df["longitude"].values,
        "frp": df["frp"].values if "frp" in df else np.nan,
        "daynight": df["daynight"].values if "daynight" in df else "",
        "sensor": key})
    out["month"] = out["date"].dt.to_period("M").astype(str)
    out = out[out["month"] >= START[key]]
    print(f"{key}: kept {len(out)} of {n0} detections after filters")
    return out.reset_index(drop=True)


def run():
    CLEAN.mkdir(parents=True, exist_ok=True)
    res = {}
    for key in SOURCES:
        df = clean(load_raw(key), key)
        if not df.empty:
            df.to_csv(CLEAN / f"{key}.csv.gz", index=False)
            res[key] = df
    return res
