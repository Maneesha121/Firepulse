import numpy as np, pandas as pd, pytest
from firepulse import harmonize as H, anomaly as A


def make_region(ratio=6.0, years=range(2012, 2024)):
    idx = pd.period_range("2010-01", "2023-12", freq="M")
    rng = np.random.default_rng(0)
    modis = pd.Series(rng.integers(50, 150, len(idx)).astype(float), index=idx)
    viirs = (modis * ratio).where(idx.year >= 2012)
    return pd.DataFrame({"modis": modis, "viirs": viirs})


def test_ratio_recovers_known_scale():
    t = H.ratio_tables(make_region(6.0))
    assert t["global"]["med"] == pytest.approx(6.0)
    assert all(abs(v["med"] - 6.0) < 1e-9 for v in t["by_month"].values())


def test_harmonized_matches_modis_scale_after_splice():
    region = make_region(6.0)
    hz = H.harmonize(region, H.ratio_tables(region), splice="2012-02")
    after = hz.loc["2013-01":"2013-12"]
    assert (after["source_used"] == "VIIRS").all()
    np.testing.assert_allclose(after["harmonized"], region.loc["2013-01":"2013-12", "modis"])
    assert (hz.loc[:"2011-12", "source_used"] == "MODIS").all()


def test_loo_validation_perfect_when_ratio_constant():
    _, s = H.loo_validation(make_region(6.0))
    assert s["median_smape_pct"] < 1e-6


def test_robust_z_needs_baseline_and_spread():
    assert A.robust_z([1, 2, 3], 5) is None            # too short
    assert A.robust_z([5.0] * 12, 9) is None            # zero MAD
    z = A.robust_z(list(range(10, 22)), 60)
    assert z is not None and z > 2 and A.band(z) == "much above normal"


def test_band_labels():
    assert A.band(None) == "insufficient data"
    assert A.band(0.2) == "normal" and A.band(-1.5) == "below normal"
