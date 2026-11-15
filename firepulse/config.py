"""Central settings. Edit here, not in the other modules."""
import os
from pathlib import Path

DEMO = os.environ.get("FIREPULSE_DEMO") == "1"      # synthetic data mode
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA = PROJECT_ROOT / ("data_demo" if DEMO else "data")
RAW, CLEAN, OUT = DATA / "raw", DATA / "clean", DATA / "out"
WEB_DATA = PROJECT_ROOT / "web" / "data"

BBOX = (79.5, 5.8, 82.0, 9.9)         # west, south, east, north (Sri Lanka, rough)
SOURCES = {"modis": "MODIS_SP", "viirs": "VIIRS_SNPP_SP"}   # FIRMS standard-processing
EXTRA_SOURCES = {"VIIRS_NOAA20_SP": "viirs", "VIIRS_NOAA21_SP": "viirs"}   # {folder name: family}. Standard-processing (SP) streams only; NRT is never mixed into the historical record. The FIRMS availability response retrieved 2026-11-13 listed MODIS_SP, VIIRS_SNPP_SP, VIIRS_NOAA20_SP and VIIRS_NOAA21_SP (NOAA-21 SP from 2023-03-01). Re-check with: python run_pipeline.py --fetch-availability
GRID = 0.1                            # degrees; cell size for precomputed counts
CHUNK_DAYS = 5                        # FIRMS area API DAY_RANGE: the OpenAPI spec says 1..5 (an older page note says 10); 5 is safe for both

# --- analytical confidence filters (PROJECT ASSUMPTIONS, configurable; not universal scientific standards)
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
               "note": "FIRMS lists VIIRS 375 m NOAA-21 data from 17 January 2024 (documentation page). The FIRMS availability response retrieved 2026-11-13 listed VIIRS_NOAA21_SP beginning 2023-03-01; confirm with --fetch-availability before relying on either date.",
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


# =====================================================================================================================
# OBSERVATION QUALITY (firepulse/quality.py, firepulse/sensitivity.py)
# Everything below is an ENGINEERING CHOICE unless a comment says otherwise. None of these thresholds is a NASA standard.
# Flags are stored separately from the observations and never alter them. Only INVALID records (unparseable or impossible
# coordinates/dates, exact duplicate rows) are removed; every other rule is a flag and/or an optional analytical filter.
# =====================================================================================================================
# Confidence classes. FIRMS documents that MODIS confidence is 0-100 % and is assigned to three classes (low / nominal / high),
# and that VIIRS confidence is l / n / h. The numeric MODIS class boundaries below are the commonly cited MCD14ML values; they
# were NOT re-read in the official user guide in this repository, so they are configurable.
MODIS_CONF_CLASSES = {"low_below": 30, "high_from": 80}
VIIRS_CONF_CLASSES = {"l": "low", "low": "low", "n": "nominal", "nominal": "nominal", "h": "high", "high": "high"}
# FIRMS documents that VIIRS low-confidence NIGHT pixels occur only between 11 E and 110 W and 7 N to 55 S. A low-confidence
# night VIIRS record outside that box contradicts the documentation and is flagged (flag only).
VIIRS_LOW_NIGHT_BOX = {"lon_from": 11.0, "lon_to": -110.0, "lat_south": -55.0, "lat_north": 7.0}   # lon_from eastward to lon_to

NEAR_DUP_M = {"modis": 500.0, "viirs": 150.0}   # same platform, same date, within NEAR_DUP_MINUTES and this distance = suspicious
NEAR_DUP_MINUTES = 10.0
ISOLATION_KM = 5.0          # exploratory isolation: no other detection (any platform, either family) within this radius ...
ISOLATION_DAYS = 2          # ... and within +/- this many days
FRP_EXTREME_K = 5.0         # extreme-high FRP: log(FRP) above median + K * 1.4826 * MAD, per sensor+platform (statistical flag only)
FRP_EXTREME_MIN_N = 100     # minimum positive-FRP records per sensor+platform before an extreme threshold is computed
LARGE_PIXEL_FACTOR = 2.0    # scan*track pixel area above this multiple of the platform median is flagged (edge-of-scan proxy)
LARGE_PIXEL_MIN_N = 20
DAYNIGHT_MAX_ABS_LAT = 66.0   # day/night vs clock-time consistency is not assessed poleward of this latitude

# Optional analytical filter profiles. A profile only changes what enters the analysis; flags and raw records are unchanged.
#   type_keep: FIRMS 'type' codes kept (None = keep all)   modis_min_conf / viirs_keep: confidence rule (None = keep all)
#   drop_flags: records carrying any of these flags are excluded      exploratory: shown with a warning in the UI
QUALITY_PROFILES = {
    "baseline": {"label": "Project default", "type_keep": sorted(FIRE_TYPE_KEEP), "modis_min_conf": MODIS_MIN_CONF,
                 "viirs_keep": sorted(VIIRS_KEEP), "drop_flags": [],
                 "description": "Type 0 only (unverified project assumption), MODIS confidence >= 30, VIIRS nominal/high. Same rules as earlier FirePulse versions."},
    "all_valid": {"label": "All valid records", "type_keep": None, "modis_min_conf": None, "viirs_keep": None, "drop_flags": [],
                  "description": "No analytical filter: every record with valid coordinates and date."},
    "no_type_filter": {"label": "Default without type rule", "type_keep": None, "modis_min_conf": MODIS_MIN_CONF,
                       "viirs_keep": sorted(VIIRS_KEEP), "drop_flags": [],
                       "description": "Project default confidence rules but the FIRMS type code is not used. Isolates the effect of the type assumption."},
    "high_confidence": {"label": "High confidence only", "type_keep": sorted(FIRE_TYPE_KEEP), "modis_min_conf": MODIS_CONF_CLASSES["high_from"],
                        "viirs_keep": ["h", "high"], "drop_flags": [],
                        "description": "MODIS high-confidence class and VIIRS 'h' only (stricter than the default)."},
    "default_no_duplicates": {"label": "Default minus near-duplicates", "type_keep": sorted(FIRE_TYPE_KEEP), "modis_min_conf": MODIS_MIN_CONF,
                              "viirs_keep": sorted(VIIRS_KEEP), "drop_flags": ["near_duplicate_later", "dup_cross_source_later"],
                              "description": "Default rules, and within each suspicious near-duplicate group only the first record is kept."},
    "default_valid_frp": {"label": "Default with valid FRP", "type_keep": sorted(FIRE_TYPE_KEEP), "modis_min_conf": MODIS_MIN_CONF,
                          "viirs_keep": sorted(VIIRS_KEEP), "drop_flags": ["frp_missing", "frp_negative"],
                          "description": "Default rules, and records whose FRP is missing or negative are excluded. High FRP values are NOT excluded."},
    "default_no_isolated": {"label": "Default minus isolated (exploratory)", "type_keep": sorted(FIRE_TYPE_KEEP), "modis_min_conf": MODIS_MIN_CONF,
                            "viirs_keep": sorted(VIIRS_KEEP), "drop_flags": ["isolated"], "exploratory": True,
                            "description": "EXPLORATORY ONLY: also drops detections with no neighbour within the isolation radius and window. Isolated detections can be real small fires; use this only to see how sensitive results are."},
}
ACTIVE_PROFILE = os.environ.get("FIREPULSE_QUALITY_PROFILE", "baseline")   # the profile that feeds the calendar, ratios and anomalies
