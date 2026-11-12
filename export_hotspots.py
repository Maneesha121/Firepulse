"""Export cleaned hotspot points for a box and date range as CSV (the challenge's CSV output).
  python export_hotspots.py WEST SOUTH EAST NORTH START END [out.csv]   (add FIREPULSE_DEMO=1 for demo data)
"""
import sys, pandas as pd
from firepulse.config import CLEAN

w, s, e, n = map(float, sys.argv[1:5]); d0, d1 = sys.argv[5:7]
out = sys.argv[7] if len(sys.argv) > 7 else "hotspots_export.csv"
parts = [pd.read_csv(f) for f in CLEAN.glob("*.csv.gz")]
df = pd.concat(parts)
m = df.lat.between(s, n) & df.lon.between(w, e) & (df.date >= d0) & (df.date <= d1)
df[m].sort_values("date").to_csv(out, index=False)
print(f"wrote {m.sum()} rows to {out}")
