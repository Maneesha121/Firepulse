"""Central settings. Edit here, not in the other modules."""
import os
from pathlib import Path

DEMO = os.environ.get("FIREPULSE_DEMO") == "1"      # synthetic data mode
DATA = Path("data_demo" if DEMO else "data")
RAW, CLEAN, OUT = DATA / "raw", DATA / "clean", DATA / "out"
WEB_DATA = Path("web/data")

BBOX = (79.5, 5.8, 82.0, 9.9)         # west, south, east, north (Sri Lanka, rough)
SOURCES = {"modis": "MODIS_SP", "viirs": "VIIRS_SNPP_SP"}   # FIRMS standard-processing
EXTRA_SOURCES = {"VIIRS_NOAA20_SP": "viirs", "VIIRS_NOAA21_NRT": "viirs"}   # {folder name: family}. Source names are in the FIRMS OpenAPI source list (verified 2026-11-13); there is no NOAA-21 SP source
GRID = 0.1                            # degrees; cell size for precomputed counts
CHUNK_DAYS = 5                        # FIRMS area API DAY_RANGE: the OpenAPI spec says 1..5 (an older page note says 10); 5 is safe for both

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

# --- NASA-DOCUMENTED platform facts (NOT inferred from detections). Retrieved 2026-11-13 from the pages named in "source".
# Only facts stated on those pages are listed; None = not verified here (do not fill in from memory).
DOCUMENTED_AVAILABILITY = {
    "TERRA": {"launch": None, "documented_start": None, "documented_end": None, "note": "No start/end date verified in the resources reviewed.", "source": None},
    "AQUA": {"launch": None, "documented_start": None, "documented_end": None,
             "note": "NASA FIRMS states that Aqua will eventually reach end of operations (no date verified here); VIIRS on NOAA-20/21 is the stated continuity.",
             "source": "https://www.earthdata.nasa.gov/news/blog/transitioning-from-suomi-npp-viirs-omps-what-firms-users-need-know"},
    "SNPP": {"launch": "2011-10-28", "documented_start": None, "documented_end": "2026-11-02",
             "note": "Delivery of new Suomi NPP observations ceased on 2 November 2026; historical products remain available. Use NOAA-21 / NOAA-20 for newer periods.",
             "source": "https://www.earthdata.nasa.gov/data/instruments/viirs/transition-resources"},
    "NOAA20": {"launch": "2017-11-18", "documented_start": "2018-04-01", "documented_end": None,
               "note": "FIRMS lists VIIRS 375 m NOAA-20 data from 1 April 2018.", "source": "https://firms.modaps.eosdis.nasa.gov/active_fire/"},
    "NOAA21": {"launch": "2022-11-10", "documented_start": "2024-01-17", "documented_end": None,
               "note": "FIRMS lists VIIRS 375 m NOAA-21 data from 17 January 2024. The area API lists no NOAA-21 standard-processing (SP) source, only NRT.",
               "source": "https://firms.modaps.eosdis.nasa.gov/active_fire/"},
}
DOCUMENTED_RETRIEVED = "2026-11-13"

# --- attribution requested by NASA FIRMS (wording from the FIRMS "About" page) and project statements
ATTRIBUTION = {
    "acknowledgment": ("We acknowledge the use of data and/or imagery from NASA's Fire Information for Resource Management System (FIRMS) "
                       "(https://earthdata.nasa.gov/firms), part of NASA's Land, Atmosphere Near real-time Capability for Earth observations (LANCE) "
                       "(https://earthdata.nasa.gov/lance) and NASA's Earth Science Data and Information System (ESDIS)."),
    "disclaimer": ("FIRMS is operated by the ESDIS project. The information presented through LANCE, GIBS, Worldview, and FIRMS are provided "
                   "\u201cas is\u201d and users bear all responsibility and liability for their use of data. Full disclaimer: "
                   "https://www.earthdata.nasa.gov/data/projects/lance/disclaimer"),
    "non_endorsement": ("FirePulse is an independent project. NASA does not endorse any non-U.S. Government entity and is not responsible for "
                        "information contained on non-U.S. Government websites. Users must comply with the data-use parameters of the respective website."),
}

# --- FIRMS 'type' attribute (inferred hotspot type). Meanings below were read on 2026-11-13 in MIRRORS/COPIES of the FIRMS attribute
# tables (several independent third-party pages agreed); the official FIRMS page itself was NOT read. Verify before citing.
# Codes not listed here are kept raw and labelled undocumented; they are never classified by guessing.
FIRE_TYPE_DOC = {0: "presumed vegetation fire", 1: "active volcano", 2: "other static land source", 3: "offshore"}
FIRE_TYPE_KEEP = {0}      # filter assumption: keep only presumed vegetation fires (report shows what is excluded)
FIRE_TYPE_BASIS = "meanings from copies of the FIRMS attribute table, official page not read (verify)"
