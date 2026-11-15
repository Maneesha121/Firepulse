"""Deterministic SYNTHETIC fixtures for tests (never real NASA data)."""
import json
import numpy as np, pandas as pd, pytest

SQUARE = {"type": "Polygon", "coordinates": [[[80.0, 7.0], [81.0, 7.0], [81.0, 8.0], [80.0, 8.0], [80.0, 7.0]]]}
TRIANGLE = {"type": "Polygon", "coordinates": [[[80.0, 7.0], [81.0, 7.0], [80.0, 8.0], [80.0, 7.0]]]}   # lower-left half of SQUARE


def _month_counts(p):
    """Known, deterministic monthly counts: seasonal + small year effect."""
    base = 8 + 6 * (p.month in (2, 3)) + (p.year % 4)
    return base, base * 6        # (modis, viirs) inside the square


@pytest.fixture
def fake_dataset(tmp_path):
    """Dataset with MODIS 2010-01..2023-12, VIIRS from 2012-01; points inside SQUARE and one cluster outside."""
    from firepulse.area import Dataset
    months = pd.period_range("2010-01", "2023-12", freq="M")
    rows = []
    for p in months:
        nm, nv = _month_counts(p)
        for sensor, n, plats in (("modis", nm, ["Terra", "Aqua"]), ("viirs", nv, ["N"])):
            if sensor == "viirs" and p < pd.Period("2012-01", "M"):
                continue
            for i in range(n):
                # inside SQUARE; upper-right half (lat > lon-73) for odd i so TRIANGLE (lower-left) gets only even ones
                lon = 80.1 + 0.8 * ((i % 10) / 10)
                lat = 7.1 + 0.8 * ((i % 10) / 10) * (1 if i % 2 == 0 else 0) + (0.7 if i % 2 else 0)
                rows.append((p.to_timestamp() + pd.Timedelta(days=i % 27), lat, lon, sensor,
                             "TERRA" if plats[i % len(plats)] == "Terra" else "AQUA" if plats[i % len(plats)] == "Aqua" else "SNPP", str(p)))
        rows.append((p.to_timestamp() + pd.Timedelta(days=5), 9.5, 82.5, "modis", "TERRA", str(p)))   # outside, every month
    pts = pd.DataFrame(rows, columns=["date", "lat", "lon", "sensor", "platform", "month"])
    pts["frp"] = 5.0; pts["daynight"] = "D"; pts["confidence_raw"] = "n"; pts["acq_time"] = 1000
    pts["src"] = "x"; pts["data_origin"] = "SYNTHETIC_DEMO"
    clean = tmp_path / "clean"; clean.mkdir()
    pts.to_csv(clean / "all.csv.gz", index=False)
    status = {"modis": ["OBSERVED_WITH_DETECTIONS"] * len(months),
              "viirs": ["MISSING_DATA" if p < pd.Period("2012-01", "M") else "OBSERVED_WITH_DETECTIONS" for p in months]}
    meta = {"data_origin": "SYNTHETIC_DEMO", "months": [str(p) for p in months], "status": status,
            "coverage_evidence": {"modis": "DECLARED", "viirs": "DECLARED"}, "splice_idx": 24,
            "ratios": {"global": {"med": 6.0, "q25": 6.0, "q75": 6.0, "n": 100},
                       "by_month": {str(m): {"med": 6.0, "q25": 6.0, "q75": 6.0, "n": 10} for m in range(1, 13)}}}
    mp = tmp_path / "meta.json"; mp.write_text(json.dumps(meta))
    return Dataset(clean_dir=clean, meta_path=mp)
