"""FIRMS product availability (what the FIRMS data_availability endpoint reports per source).

The exact column names of that endpoint were NOT verified in this repository (no live access during development).
parse() therefore accepts only a small set of known-plausible header names and RAISES on anything else instead of guessing.
Verify with:  python run_pipeline.py --fetch-availability   and compare data/availability_raw.csv with the parsed output.
"""
import json, datetime as dt
import pandas as pd
from .config import DATA

ID_COLS = ("data_id", "source", "dataset", "id")
FIRST_COLS = ("min_date", "first_date", "start_date", "start")
LAST_COLS = ("max_date", "last_date", "end_date", "end")
PLATFORM_OF = {"VIIRS_SNPP": "SNPP", "VIIRS_NOAA20": "NOAA20", "VIIRS_NOAA21": "NOAA21"}


class AvailabilityFormatError(ValueError):
    pass


def split_source(name):
    """VIIRS_NOAA20_SP -> (platform 'NOAA20', stream 'SP'); MODIS_SP -> (None, 'SP') (MODIS platform is not in the source name)."""
    n = str(name).strip().upper()
    stream = "SP" if n.endswith("_SP") else "NRT" if n.endswith("_NRT") else "UNKNOWN"
    stem = n.rsplit("_", 1)[0] if stream != "UNKNOWN" else n
    return PLATFORM_OF.get(stem), stream


def _pick(cols, options):
    for o in options:
        if o in cols:
            return o
    return None


def parse(text):
    """CSV text -> {source: {first, last, platform, stream}}. Raises AvailabilityFormatError for unknown layouts."""
    import io
    df = pd.read_csv(io.StringIO(text))
    cols = {c.strip().lower(): c for c in df.columns}
    i, a, b = _pick(cols, ID_COLS), _pick(cols, FIRST_COLS), _pick(cols, LAST_COLS)
    if not (i and a and b):
        raise AvailabilityFormatError(f"Unrecognised availability columns {list(df.columns)}; expected an id column {ID_COLS}, "
                                      f"a first-date column {FIRST_COLS} and a last-date column {LAST_COLS}. Not guessing.")
    out = {}
    for _, r in df.iterrows():
        first, last = pd.to_datetime(r[cols[a]], errors="raise"), pd.to_datetime(r[cols[b]], errors="raise")
        plat, stream = split_source(r[cols[i]])
        out[str(r[cols[i]]).strip()] = {"first": str(first.date()), "last": str(last.date()), "platform": plat, "stream": stream}
    if not out:
        raise AvailabilityFormatError("Availability reply has no rows.")
    return out


def save(text, retrieved=None):
    """Keep the raw reply and its parsed form with a retrieval timestamp (never overwritten silently by a failed parse)."""
    parsed = parse(text)
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "availability_raw.csv").write_text(text)
    rec = {"retrieved": retrieved or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "origin": "FIRMS data_availability API", "sources": parsed}
    (DATA / "availability.json").write_text(json.dumps(rec, indent=1))
    return rec


def load():
    f = DATA / "availability.json"
    return json.loads(f.read_text()) if f.exists() else None
