"""SYNTHETIC FIRMS-like data so the pipeline and website can be tested offline.
NOT real observations. Run via:  python run_pipeline.py --demo
"""
import calendar, json
import numpy as np, pandas as pd
from firepulse.config import RAW, SOURCES, BBOX


def season(m):  # two burning seasons (Feb-Mar, Jul-Aug) + low background
    return 0.25 + 1.6 * np.exp(-((m - 2.5) ** 2) / 2) + 1.0 * np.exp(-((m - 7.5) ** 2) / 2)


def make(seed=42, last=(2025, 10)):
    rng = np.random.default_rng(seed)
    rng2 = np.random.default_rng(seed + 1)   # platform labels only; keeps the original draws identical
    w, s, e, n = BBOX
    centers = np.column_stack([rng.uniform(s + .5, n - .5, 8), rng.uniform(w + .3, e - .3, 8)])
    yf = {y: float(np.exp(rng.normal(0, .25))) for y in range(2000, 2026)}
    yf[2023] = 2.6  # injected anomaly so the demo shows something unusual
    for key, start, scale in (("modis", (2000, 12), 90.0), ("viirs", (2012, 2), 560.0)):
        rows = []
        for y in range(start[0], last[0] + 1):
            for m in range(1, 13):
                if (y, m) < start or (y, m) > last:
                    continue
                dim = calendar.monthrange(y, m)[1]
                k = rng.poisson(scale * season(m) * (yf[y] if not (y == 2023 and m != 2) else 1.0))
                k = max(k, 3)
                c = centers[rng.integers(0, len(centers), k)]
                lat = np.clip(c[:, 0] + rng.normal(0, .25, k), s, n)
                lon = np.clip(c[:, 1] + rng.normal(0, .25, k), w, e)
                day = rng.integers(1, dim + 1, k)
                day[0] = dim  # guarantees a detection on the last day (month looks complete)
                conf = (rng.integers(5, 101, k) if key == "modis"
                        else rng.choice(["l", "n", "h"], k, p=[.15, .65, .2]))
                rows.append(pd.DataFrame({
                    "latitude": lat.round(5), "longitude": lon.round(5),
                    "acq_date": [f"{y}-{m:02d}-{d:02d}" for d in day], "acq_time": 1030,
                    "confidence": conf, "frp": rng.gamma(2, 6, k).round(1),
                    "daynight": rng.choice(["D", "N"], k), "type": 0,
                    "satellite": (rng2.choice(["Terra", "Aqua"], k) if key == "modis" else "N")}))
        folder = RAW / SOURCES[key]
        folder.mkdir(parents=True, exist_ok=True)
        pd.concat(rows).to_csv(folder / "demo.csv", index=False)
        # declared coverage: the generator covers every day from the first month to the last day of `last`
        end = f"{last[0]}-{last[1]:02d}-{calendar.monthrange(*last)[1]:02d}"
        (folder / "coverage.json").write_text(json.dumps(
            {"windows": [{"start": f"{start[0]}-{start[1]:02d}-01", "end": end}], "origin": "SYNTHETIC_DEMO"}))
    print("synthetic demo data written to", RAW)
