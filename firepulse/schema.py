"""Common record schema, platform vocabulary and data-origin labels."""
import pandas as pd

# Cleaned point records (data/clean/*.csv.gz). Original FIRMS columns are kept where available.
CLEAN_COLUMNS = ["date", "lat", "lon", "frp", "daynight", "sensor", "platform", "confidence_raw",
                 "acq_time", "src", "data_origin", "month"]
# Optional source attributes kept when the raw FIRMS file has them (never altered): product_stream (NRT/SP, from the source name),
# version (FIRMS 'version', e.g. 2.0NRT), scan/track (nominal pixel size in km along/across scan), fire_type (FIRMS 'type').
CLEAN_OPTIONAL = ["product_stream", "version", "scan", "track", "fire_type"]


def product_stream(src):
    """NRT / SP from the FIRMS source (folder) name, e.g. VIIRS_NOAA20_NRT -> NRT. Anything else -> UNKNOWN (never guessed)."""
    s = pd.Series(src).astype(str).str.upper()
    return s.where(s.str.endswith("_NRT") | s.str.endswith("_SP"), "UNKNOWN").str.rsplit("_", n=1).str[-1].where(
        s.str.endswith("_NRT") | s.str.endswith("_SP"), "UNKNOWN").values

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


_SRC_PLATFORM = {"VIIRS_SNPP": "SNPP", "VIIRS_NOAA20": "NOAA20", "VIIRS_NOAA21": "NOAA21"}


def platform_from_src(src):
    """Platform named by a FIRMS VIIRS source (folder) name, e.g. VIIRS_NOAA20_SP -> NOAA20; anything else -> None.
    MODIS sources do not name Terra/Aqua, so MODIS platforms come only from the 'satellite' column."""
    s = pd.Series(src).astype(str).str.upper()
    stem = s.where(s.str.endswith("_NRT") | s.str.endswith("_SP"), "").str.rsplit("_", n=1).str[0]
    return stem.map(_SRC_PLATFORM).values
