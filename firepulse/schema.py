"""Common record schema, platform vocabulary and data-origin labels."""
import pandas as pd

# Cleaned point records (data/clean/*.csv.gz). Original FIRMS columns are kept where available.
CLEAN_COLUMNS = ["date", "lat", "lon", "frp", "daynight", "sensor", "platform", "confidence_raw",
                 "acq_time", "src", "data_origin", "month"]

PLATFORMS = ("TERRA", "AQUA", "SNPP", "NOAA20", "NOAA21", "UNKNOWN")
FAMILY_OF = {"TERRA": "modis", "AQUA": "modis", "SNPP": "viirs", "NOAA20": "viirs", "NOAA21": "viirs"}

# FIRMS 'satellite' column vocabulary (confirm against real files with validate_inputs.py).
_PLATFORM_MAP = {
    "modis": {"terra": "TERRA", "t": "TERRA", "aqua": "AQUA", "a": "AQUA"},
    "viirs": {"n": "SNPP", "snpp": "SNPP", "s-npp": "SNPP", "suomi-npp": "SNPP", "npp": "SNPP",
              "1": "NOAA20", "n20": "NOAA20", "noaa-20": "NOAA20", "noaa20": "NOAA20",
              "2": "NOAA21", "n21": "NOAA21", "noaa-21": "NOAA21", "noaa21": "NOAA21"},
}

ORIGIN_SYNTHETIC = "SYNTHETIC_DEMO"
ORIGIN_FIRMS = "NASA_FIRMS"


def normalise_platform(series, key):
    """Map a raw 'satellite' column to canonical platform names. Unknown values -> UNKNOWN (never guessed)."""
    if series is None:
        return None
    m = _PLATFORM_MAP[key]
    return series.astype(str).str.strip().str.lower().map(m).fillna("UNKNOWN")


def data_origin(demo):
    return ORIGIN_SYNTHETIC if demo else ORIGIN_FIRMS


def month_str(dates):
    return pd.to_datetime(dates).dt.to_period("M").astype(str)
