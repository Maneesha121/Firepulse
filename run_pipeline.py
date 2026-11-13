"""One command for the whole pipeline.
  python run_pipeline.py --demo                       # synthetic data, offline
  python run_pipeline.py --download 2000-11-01 2025-10-31   # real FIRMS (needs FIRMS_MAP_KEY)
  python run_pipeline.py                              # reuse already-downloaded raw files
"""
import os, sys, argparse

ap = argparse.ArgumentParser()
ap.add_argument("--demo", action="store_true", help="use synthetic data in data_demo/")
ap.add_argument("--download", nargs=2, metavar=("START", "END"))
ap.add_argument("--fetch-availability", action="store_true", help="fetch FIRMS product availability (needs FIRMS_MAP_KEY) and store it")
args = ap.parse_args()
if args.demo:
    os.environ["FIREPULSE_DEMO"] = "1"

from firepulse import clean, aggregate, harmonize, anomaly, export, download, availability, coverage  # noqa: E402
from firepulse.config import SOURCES, EXTRA_SOURCES, RAW  # noqa: E402

if args.demo:
    import demo_data
    demo_data.make()
elif args.download:
    download.download(*args.download)

if args.fetch_availability:
    key = os.environ.get("FIRMS_MAP_KEY", "")
    if not key:
        sys.exit("Set FIRMS_MAP_KEY first.")
    rec = availability.save(download.availability(key))
    print("Stored availability for", len(rec["sources"]), "sources in data/availability.json")

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
print("\nGlobal VIIRS/MODIS ratio:", {k: round(v, 2) for k, v in tables["global"].items()})
print("Leave-one-year-out validation:", val_sum)
print("Done. Open the site:  python -m http.server -d web 8000   ->  http://localhost:8000")
