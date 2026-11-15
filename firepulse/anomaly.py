"""Robust seasonal anomaly: same-calendar-month baseline, median + MAD."""
import numpy as np, pandas as pd
from .config import MIN_BASELINE


def _clean(h):
    h = np.asarray(h, dtype=float)
    return h[~np.isnan(h)]


def robust_z(hist, x):
    h = _clean(hist)
    if len(h) < MIN_BASELINE or x is None or np.isnan(x):
        return None
    med = np.median(h)
    mad = np.median(np.abs(h - med))
    if mad == 0:
        return None
    return float(0.6745 * (x - med) / mad)


def percentile(hist, x):
    h = _clean(hist)
    if len(h) < MIN_BASELINE or x is None or np.isnan(x):
        return None
    return float((h <= x).mean() * 100)


def band(z):
    if z is None:
        return "insufficient data"
    if z >= 2: return "much above normal"
    if z >= 1: return "above normal"
    if z <= -2: return "much below normal"
    if z <= -1: return "below normal"
    return "normal"


def series_anomalies(s, past_only=False):
    """s: Series indexed by monthly Period. Baseline = same calendar month in other (or earlier) years."""
    rows = []
    for ts, x in s.items():
        mask = (s.index.month == ts.month) & ((s.index.year < ts.year) if past_only else (s.index.year != ts.year))
        base = s[mask].values
        z = robust_z(base, x)
        rows.append((ts, z, percentile(base, x), band(z)))
    return pd.DataFrame(rows, columns=["month", "z", "percentile", "band"]).set_index("month")
