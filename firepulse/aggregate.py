"""Aggregate cleaned detections to monthly counts per grid cell and per region."""
import numpy as np, pandas as pd
from .config import GRID, MODIS_START, VIIRS_START
from . import coverage
from .clean import folders_for

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


def platform_monthly(dfs, index):
    """Monthly detections per platform over the region (platform identity preserved)."""
    parts = []
    for k, df in dfs.items():
        g = df.groupby(["month", "platform"]).size().unstack(fill_value=0)
        g.index = pd.PeriodIndex(g.index, freq="M")
        parts.append(g.reindex(index).fillna(0).astype(int))
    return pd.concat(parts, axis=1) if parts else pd.DataFrame(index=index)


def month_statuses(dfs, index):
    """{sensor: DataFrame(status, covered_days, days_in_month, evidence)} from coverage evidence (see coverage.py)."""
    out = {}
    for k, df in dfs.items():
        c = df.groupby("month").size()
        c.index = pd.PeriodIndex(c.index, freq="M")
        cov, ev = coverage.family_coverage(folders_for(k))
        out[k] = coverage.month_status(index, c, cov, ev, pd.Period(START[k], "M"))
    return out


def mask_unobserved(region, statuses):
    """Months that are not OBSERVED_* become NaN (unknown), never 0."""
    region = region.copy()
    for k, st in statuses.items():
        ok = st["status"].isin(coverage.OBSERVED)
        region.loc[~ok.reindex(region.index).fillna(False).values, k] = np.nan
    return region
