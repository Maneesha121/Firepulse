"""One command for the whole pipeline.
  python run_pipeline.py --demo                       # synthetic data, offline
  python run_pipeline.py --download 2000-11-01 2025-10-31   # real FIRMS (needs FIRMS_MAP_KEY)
  python run_pipeline.py                              # reuse already-downloaded raw files
  python run_pipeline.py --profile all_valid          # choose which quality-filter profile feeds the calendar (default: baseline)
  python run_pipeline.py --fetch-availability         # only fetch + store FIRMS availability, then exit
"""
import os, sys, argparse

ap = argparse.ArgumentParser()
ap.add_argument("--demo", action="store_true", help="use synthetic data in data_demo/")
ap.add_argument("--download", nargs=2, metavar=("START", "END"))
ap.add_argument("--fetch-availability", action="store_true", help="fetch FIRMS product availability (needs FIRMS_MAP_KEY), store it and EXIT")
ap.add_argument("--profile", default=None, help="quality-filter profile feeding the calendar (see config.QUALITY_PROFILES); default baseline")
args = ap.parse_args()
if args.demo:
    os.environ["FIREPULSE_DEMO"] = "1"
else:
    os.environ.pop("FIREPULSE_DEMO", None)
if args.profile:
    os.environ["FIREPULSE_QUALITY_PROFILE"] = args.profile

from firepulse import clean, aggregate, harmonize, anomaly, export, download, availability, coverage  # noqa: E402
from firepulse.config import SOURCES, EXTRA_SOURCES, RAW  # noqa: E402

if args.fetch_availability:
    key = os.environ.get("FIRMS_MAP_KEY", "")
    if not key:
        sys.exit("Set FIRMS_MAP_KEY first (see README). The key is never printed or stored in the project.")
    rec = availability.save(download.availability(key))
    print("Stored availability for", len(rec["sources"]), "sources in", availability.DATA / "availability.json", "(raw reply: availability_raw.csv). Done.")
    sys.exit(0)          # availability only: no cleaning, no aggregation

if args.demo:
    import demo_data
    demo_data.make()
elif args.download:
    download.download(*args.download)

dfs = clean.run()
if set(dfs) != {"modis", "viirs"}:
    sys.exit("Need cleaned data for both sensors. Download first or use --demo.")
avail = aggregate.availability(dfs)
agg = aggregate.cell_monthly(dfs, avail)
region = aggregate.region_monthly(agg, avail)
statuses = aggregate.month_statuses(dfs, region.index)
region = aggregate.mask_unobserved(region, statuses)      # unverified months become unknown (NaN), never 0
tables = harmonize.ratio_tables(region)
hz = harmonize.harmonize(region, tables)
val_df, val_sum = harmonize.loo_validation(region)
an = anomaly.series_anomalies(hz["harmonized"])
export.export_tables(region, hz, an, val_df, statuses)
import json as _json
cleaning = _json.loads((clean.CLEAN / 'cleaning_report.json').read_text())
src_cov = [coverage.source_summary(RAW / n) for n in list(SOURCES.values()) + list(EXTRA_SOURCES)]
export.export_web(agg, region, tables, val_sum, avail, statuses, cleaning, availability.load(), src_cov)
# observation quality: counts per rule + sensitivity of calendar / ratio / anomalies to the filter profile (whole region)
from firepulse import area as _area  # noqa: E402
_q = _json.loads((clean.CLEAN / "quality_report.json").read_text())
_ds = _area.Dataset()
_sens = _area.quality_sensitivity(_ds)
export.export_quality(_q, _sens)
print("\nQuality: active profile =", _q["active_profile"], "| retained/valid per sensor:",
      {k: f"{v['retained']}/{v['valid_records']}" for k, v in _q["profiles"][_q["active_profile"]]["sensors"].items()})
print("\nGlobal VIIRS/MODIS ratio:", {k: round(v, 2) for k, v in tables["global"].items()})
print("Leave-one-year-out validation:", val_sum)
print("Done. Open the site:  python -m http.server -d web 8000   ->  http://localhost:8000")
