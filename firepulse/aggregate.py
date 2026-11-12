"""Aggregate cleaned detections to monthly counts per grid cell and per region."""
import numpy as np, pandas as pd
from .config import GRID, MODIS_START, VIIRS_START

START = {"modis": MODIS_START, "viirs": VIIRS_START}


def last_full_month(max_date):
    p = max_date.to_period("M")
    return p - 1 if max_date.day < p.days_in_month - 1 else p


def availability(dfs):
    """{sensor: (first_period, last_period)}; the last (possibly partial) month is dropped."""
    return {k: (pd.Period(START[k], "M"), last_full_month(df["date"].max())) for k, df in dfs.items()}


def cell_monthly(dfs, avail):
    parts = []
    for k, df in dfs.items():
        a, b = avail[k]
        d = df[(df["month"] >= str(a)) & (df["month"] <= str(b))].copy()
        d["ci"] = np.floor(d["lat"] / GRID).astype(int)
        d["cj"] = np.floor(d["lon"] / GRID).astype(int)
        parts.append(d.groupby(["ci", "cj", "month", "sensor"]).size().rename("n").reset_index())
    return pd.concat(parts, ignore_index=True)


def region_monthly(agg, avail):
    idx = pd.period_range(min(v[0] for v in avail.values()), max(v[1] for v in avail.values()), freq="M")
    out = pd.DataFrame(np.nan, index=idx, columns=["modis", "viirs"])
    for k, (a, b) in avail.items():
        s = agg[agg["sensor"] == k].groupby("month")["n"].sum()
        s.index = pd.PeriodIndex(s.index, freq="M")
        rng = pd.period_range(a, b, freq="M")
        out.loc[rng, k] = s.reindex(rng).fillna(0).values
    return out
