"""Data-coverage evidence and per-month data status.

A detection-only CSV cannot prove that a month was observed: a month with no rows may be a quiet month OR
missing data. Coverage is therefore taken only from evidence:
  DOWNLOAD_WINDOWS  raw files named '<start-date>_<days>.csv' from download.py (non-empty file = the FIRMS reply
                    for that window was received, even if it has zero rows)
  DECLARED          a user-written 'coverage.json' next to the raw files: {"windows": [{"start": "...", "end": "..."}]}
  NONE              no evidence

Status codes (per sensor family and month):
  OBSERVED_WITH_DETECTIONS  >=1 detection and (full coverage evidence OR no evidence of gaps)
  OBSERVED_ZERO_DETECTIONS  full coverage evidence and zero detections
  INCOMPLETE_PERIOD         coverage evidence for only part of the month
  MISSING_DATA              month before the product's configured start (sensor not in the record)
  INSUFFICIENT_EVIDENCE     no rows and no coverage evidence, so zero cannot be claimed
"""
import json, re, datetime as dt
import pandas as pd

OBSERVED = ("OBSERVED_WITH_DETECTIONS", "OBSERVED_ZERO_DETECTIONS")
STATUSES = OBSERVED + ("INCOMPLETE_PERIOD", "MISSING_DATA", "INSUFFICIENT_EVIDENCE")
_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d+)\.csv$")


def folder_windows(folder):
    """-> (list of (start_date, end_date), evidence label) for one raw folder."""
    wins, ev = [], "NONE"
    if not folder.exists():
        return wins, ev
    for f in sorted(folder.glob("*.csv")):
        m = _NAME.match(f.name)
        if m and f.stat().st_size > 0:
            d0 = dt.date.fromisoformat(m.group(1))
            wins.append((d0, d0 + dt.timedelta(days=int(m.group(2)) - 1)))
            ev = "DOWNLOAD_WINDOWS"
    side = folder / "coverage.json"
    if side.exists():
        for w in json.loads(side.read_text()).get("windows", []):
            wins.append((dt.date.fromisoformat(w["start"]), dt.date.fromisoformat(w["end"])))
        ev = "DECLARED" if ev == "NONE" else ev
    return wins, ev


def covered_days_by_month(windows):
    """Union of windows -> Series(Period month -> number of covered days)."""
    days = set()
    for a, b in windows:
        n = (b - a).days + 1
        days.update(a + dt.timedelta(days=i) for i in range(n))
    if not days:
        return pd.Series(dtype=int)
    s = pd.Series(1, index=pd.PeriodIndex(pd.to_datetime(sorted(days)), freq="M"))
    return s.groupby(level=0).sum()


def family_coverage(folders):
    """Conservative coverage for a sensor family: days covered by EVERY folder that has evidence."""
    per = [folder_windows(f) for f in folders]
    per = [(w, e) for w, e in per if w]
    if not per:
        return pd.Series(dtype=int), "NONE"
    sets = []
    for w, _ in per:
        d = set()
        for a, b in w:
            d.update(a + dt.timedelta(days=i) for i in range((b - a).days + 1))
        sets.append(d)
    common = set.intersection(*sets)
    s = pd.Series(1, index=pd.PeriodIndex(pd.to_datetime(sorted(common)), freq="M")) if common else pd.Series(dtype=int)
    ev = "DOWNLOAD_WINDOWS" if any(e == "DOWNLOAD_WINDOWS" for _, e in per) else "DECLARED"
    return (s.groupby(level=0).sum() if len(s) else s), ev


def month_status(index, counts, covered, evidence, start_period):
    """index: PeriodIndex of months; counts: Series(Period->n detections); covered: Series(Period->days)."""
    rows = []
    for p in index:
        n = int(counts.get(p, 0))
        cd = int(covered.get(p, 0)) if len(covered) else 0
        dim = p.days_in_month
        if p < start_period:
            st = "MISSING_DATA"
        elif cd >= dim:
            st = "OBSERVED_WITH_DETECTIONS" if n > 0 else "OBSERVED_ZERO_DETECTIONS"
        elif cd > 0:
            st = "INCOMPLETE_PERIOD"
        elif n > 0:
            st = "OBSERVED_WITH_DETECTIONS"       # rows exist; completeness unverified (evidence column says so)
        else:
            st = "INSUFFICIENT_EVIDENCE"
        rows.append((p, st, cd, dim, evidence if cd or n else "NONE"))
    return pd.DataFrame(rows, columns=["month", "status", "covered_days", "days_in_month", "evidence"]).set_index("month")
