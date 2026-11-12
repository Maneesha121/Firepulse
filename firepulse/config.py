"""Central settings. Edit here, not in the other modules."""
import os
from pathlib import Path

DEMO = os.environ.get("FIREPULSE_DEMO") == "1"      # synthetic data mode
DATA = Path("data_demo" if DEMO else "data")
RAW, CLEAN, OUT = DATA / "raw", DATA / "clean", DATA / "out"
WEB_DATA = Path("web/data")

BBOX = (79.5, 5.8, 82.0, 9.9)         # west, south, east, north (Sri Lanka, rough)
SOURCES = {"modis": "MODIS_SP", "viirs": "VIIRS_SNPP_SP"}   # FIRMS standard-processing
GRID = 0.1                            # degrees; cell size for precomputed counts
CHUNK_DAYS = 10                       # FIRMS area API: day range up to 10

# --- quality filters (ASSUMPTIONS: confirm in the MODIS C6 / VIIRS 375 m user guides)
MODIS_MIN_CONF = 30
VIIRS_KEEP = {"n", "h", "nominal", "high"}

# --- record coverage (first FULL month with data)
MODIS_START = "2000-12"
VIIRS_START = "2012-02"

# --- harmonization
SPLICE = "2012-02"    # from this month use VIIRS/ratio (MODIS-equivalent). None = MODIS wherever present
MIN_COUNT = 5         # min MODIS monthly count for a month to be used when estimating the ratio
MIN_YEARS = 5         # min overlap years to trust a calendar-month-specific ratio

# --- anomaly
MIN_BASELINE = 10     # min baseline years (same calendar month) for a robust z-score
