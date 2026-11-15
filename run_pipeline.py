"""One-command pipeline for the NASA FIRMS analysis."""
import argparse
import os
import sys

ap = argparse.ArgumentParser()
ap.add_argument('--demo', action='store_true', help='use synthetic data in data_demo/')
ap.add_argument('--download', nargs=2, metavar=('START', 'END'))
ap.add_argument('--fetch-availability', action='store_true', help='fetch and store FIRMS availability, then exit')
ap.add_argument('--profile', default=None, help='quality-filter profile feeding the calendar; default baseline')
args = ap.parse_args()

if args.demo:
    os.environ['FIREPULSE_DEMO'] = '1'
else:
    os.environ.pop('FIREPULSE_DEMO', None)
if args.profile:
    os.environ['FIREPULSE_QUALITY_PROFILE'] = args.profile

from firepulse import aggregate, anomaly, availability, clean, coverage, download, export, harmonize  # noqa: E402
from firepulse.config import EXTRA_SOURCES, RAW, SOURCES  # noqa: E402

if args.fetch_availability:
    key = os.environ.get('FIRMS_MAP_KEY', '')
    if not key:
        sys.exit('Set FIRMS_MAP_KEY first (see README). The key is never printed or stored in the project.')
    rec = availability.save(download.availability(key))
    print('Stored availability for', len(rec['sources']), 'sources in', availability.DATA / 'availability.json', '(raw reply: availability_raw.csv). Done.')
    sys.exit(0)

if args.download:
    failed = download.download(*args.download)
    if failed:
        sys.exit(f'Download incomplete: {len(failed)} FIRMS window(s) failed. No analysis was generated; re-run after checking the errors above.')

if not args.demo:
    missing = [name for name in [*SOURCES.values(), *EXTRA_SOURCES] if not any((RAW / name).glob('*.csv'))]
    if missing:
        sys.exit('Missing NASA FIRMS source CSVs: ' + ', '.join(missing) + '. Add official FIRMS SP CSVs or run --download; --demo is synthetic and for testing only.')

if args.demo:
    import demo_data
    demo_data.make()

# Normal analysis pipeline

dfs = clean.run()
if set(dfs) != {'modis', 'viirs'}:
    sys.exit('Need cleaned data for both sensors. Download NASA FIRMS data first or use --demo for a synthetic test run.')

avail = aggregate.availability(dfs)
agg = aggregate.cell_monthly(dfs, avail)
region = aggregate.region_monthly(agg, avail)
statuses = aggregate.month_statuses(dfs, region.index)
region = aggregate.mask_unobserved(region, statuses)
tables = harmonize.ratio_tables(region)
hz = harmonize.harmonize(region, tables)
val_df, val_sum = harmonize.loo_validation(region)
an = anomaly.series_anomalies(hz['harmonized'])
export.export_tables(region, hz, an, val_df, statuses)

import json as _json  # noqa: E402
from firepulse import area as _area  # noqa: E402

cleaning = _json.loads((clean.CLEAN / 'cleaning_report.json').read_text())
src_cov = [coverage.source_summary(RAW / n) for n in list(SOURCES.values()) + list(EXTRA_SOURCES)]
export.export_web(agg, region, tables, val_sum, avail, statuses, cleaning, availability.load(), src_cov)
_q = _json.loads((clean.CLEAN / 'quality_report.json').read_text())
_ds = _area.Dataset()
_sens = _area.quality_sensitivity(_ds)
export.export_quality(_q, _sens)

print('\nQuality: active profile =', _q['active_profile'], '| retained/valid per sensor:',
      {k: f"{v['retained']}/{v['valid_records']}" for k, v in _q['profiles'][_q['active_profile']]['sensors'].items()})
print('\nGlobal VIIRS/MODIS ratio:', {k: round(v, 2) for k, v in tables['global'].items()})
print('Leave-one-year-out validation:', val_sum)
print('Done. Open http://localhost:8000 with: python serve.py')
