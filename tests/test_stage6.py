"""Stage 6: anomaly baseline modes, NRT/SP join check, FIRMS availability ingestion, platform cross-check, per-source coverage.
All data are SYNTHETIC fixtures; the FIRMS availability CSV layout below is an ASSUMED fixture (the real layout is not verified)."""
import numpy as np, pandas as pd, pytest
from firepulse import area, api, clean, coverage, availability, schema, spatial as S, stream_join
from conftest import SQUARE
from test_sensor_transition import build_ds, run


def wavy(p, plat, zone):
    """Terra + S-NPP with a year-dependent level so MAD > 0 (needed for an anomaly)."""
    if zone != "W": return 0
    lvl = 8 + (p.year % 5) + (p.month % 3)
    if plat == "TERRA": return lvl
    if plat == "SNPP": return lvl * 6 if p >= pd.Period("2012-01", "M") else 0
    return 0


# ------------------------------------------------------------------------------------------------ baseline modes
def test_past_only_baseline_uses_only_earlier_years(tmp_path):
    ds = build_ds(tmp_path, wavy)
    allo = area.analyze(ds, S.parse_geometry(SQUARE))
    past = area.analyze(ds, S.parse_geometry(SQUARE), baseline="past_only")
    assert allo["baseline_mode"] == "all_other_years" and past["baseline_mode"] == "past_only"
    a = {r["month"]: r for r in allo["months"]}; b = {r["month"]: r for r in past["months"]}
    assert a["2015-06"]["baseline_n"] == 13 and b["2015-06"]["baseline_n"] == 5          # 2010..2023 minus 2015 vs 2010..2014
    assert a["2015-06"]["z"] is not None and b["2015-06"]["z"] is None                    # < 10 earlier years -> disabled
    assert b["2022-06"]["baseline_n"] == 12 and b["2022-06"]["z"] is not None
    assert "retrospective" in " ".join(past["summary"]["limitations"]) and "earlier years only" in past["method"]["baseline"]


def test_past_only_z_ignores_future_values(tmp_path):
    """Unit level: a LATER year never changes a past-only score; it does change the all-other-years score."""
    from firepulse import anomaly
    idx = pd.period_range("2005-01", "2020-12", freq="M")
    vals = np.array([10 + (p.year * 7) % 13 + p.month for p in idx], dtype=float)
    s0 = pd.Series(vals, index=idx)
    s1 = s0.copy(); s1[s1.index.year >= 2018] += 500                                     # change the last three years only
    assert anomaly.series_anomalies(s0, past_only=True).loc[pd.Period("2014-06", "M"), "z"] is not None and np.isnan(anomaly.series_anomalies(s0, past_only=True).loc[pd.Period("2014-06", "M"), "z"])   # only 9 earlier years
    p0, p1 = (anomaly.series_anomalies(x, past_only=True).loc[pd.Period("2016-06", "M"), "z"] for x in (s0, s1))
    a0, a1 = (anomaly.series_anomalies(x, past_only=False).loc[pd.Period("2016-06", "M"), "z"] for x in (s0, s1))
    assert not np.isnan(p0) and p0 == pytest.approx(p1)
    assert a0 != pytest.approx(a1)


def test_past_only_through_area_does_not_use_later_years(tmp_path):
    """Area level, raw VIIRS score (no ratio involved): doubling the 2023 VIIRS detections changes no earlier past-only score.
    The harmonised-index score also depends on the whole-record VIIRS/MODIS ratio, which is NOT past-only (stated in the output)."""
    ds = build_ds(tmp_path, wavy)
    run_ = lambda: {r["month"]: r["z_viirs"] for r in area.analyze(ds, S.parse_geometry(SQUARE), baseline="past_only")["months"]}
    before = run_()
    pts = ds.points
    boost = (pts["month"] >= "2023-01") & (pts["platform"] == "SNPP")
    ds.points = pd.concat([pts, pts[boost]], ignore_index=True)
    ds._lat = ds.points["lat"].to_numpy(); ds._lon = ds.points["lon"].to_numpy()
    after = run_()
    early = [m for m in before if m < "2023-01" and before[m] is not None]
    assert len(early) == 12 and all(      # only 2022 has the 10 earlier VIIRS years needed
        before[m] == pytest.approx(after[m]) for m in early)
    assert any(before[m] != after[m] for m in before if m >= "2023-01" and before[m] is not None and after[m] is not None)


def test_invalid_baseline_rejected_and_api_passes_it(tmp_path):
    ds = build_ds(tmp_path, wavy)
    with pytest.raises(area.AreaError):
        area.analyze(ds, S.parse_geometry(SQUARE), baseline="future")
    out = api.handle_area(ds, {"geometry": SQUARE, "baseline": "past_only"})
    assert out["baseline_mode"] == "past_only"
    assert api.handle_area(ds, {"geometry": SQUARE})["baseline_mode"] == "all_other_years"


# ------------------------------------------------------------------------------------------------ NRT/SP join
def join_fixture(tmp_path, nrt_from="2023-06", nrt_level=60, modis=10, mixed_month=None):
    def f(p, plat, zone):
        if zone != "W": return 0
        if plat == "TERRA": return modis if p < pd.Period(nrt_from, "M") else modis
        if plat == "NOAA20" and p >= pd.Period("2018-04", "M"):
            return nrt_level if p >= pd.Period(nrt_from, "M") else 60
        return 0
    ds = build_ds(tmp_path, f)
    ds.points["product_stream"] = np.where((ds.points["platform"] == "NOAA20") & (ds.points["month"] >= nrt_from), "NRT", "SP")
    if mixed_month:
        i = ds.points.index[(ds.points["platform"] == "NOAA20") & (ds.points["month"] == mixed_month)][:5]
        ds.points.loc[i, "product_stream"] = "SP"
    return ds


def row(si, plat="NOAA20"):
    return {r["platform"]: r for r in si["stream_join"]["rows"]}[plat]


def test_synthetic_step_at_nrt_join_is_flagged(tmp_path):
    si = run(join_fixture(tmp_path, nrt_level=36))                                       # NRT = 60 % of SP level
    r = row(si)
    assert r["status"] == "LEVEL_SHIFT_FLAGGED" and r["shift_pct"] == pytest.approx(-40.0, abs=0.2)
    assert r["first_nrt_month"] == "2023-06" and r["last_sp_month"] == "2023-05" and r["compared_months"] == 7
    assert any("NOAA" in n and "-40.0%" in n and "provisional" in n for n in si["notes"])


def test_no_step_is_not_flagged_and_wording_is_cautious(tmp_path):
    r = row(run(join_fixture(tmp_path, nrt_level=60)))
    assert r["status"] == "NO_LARGE_SHIFT_DETECTED" and abs(r["shift_pct"]) < 0.5
    assert "does not prove" in r["reason"]


def test_too_few_nrt_months_gives_no_number(tmp_path):
    r = row(run(join_fixture(tmp_path, nrt_from="2023-10", nrt_level=36)))
    assert r["status"] == "INSUFFICIENT_EVIDENCE" and r["shift_pct"] is None and r["compared_months"] == 3


def test_low_modis_months_are_not_used_for_the_comparison(tmp_path):
    ds = join_fixture(tmp_path, nrt_level=36)
    t = ds.points
    drop = (t["platform"] == "TERRA") & (t["month"] >= "2023-06")
    keep = t.index[drop][~t.loc[drop].groupby("month").cumcount().lt(3).reindex(t.index[drop]).values]   # leave 3 Terra rows/month
    ds.points = t.drop(keep).reset_index(drop=True)
    ds._lat = ds.points["lat"].to_numpy(); ds._lon = ds.points["lon"].to_numpy()
    r = row(run(ds))
    assert r["compared_months"] == 0 and r["status"] == "INSUFFICIENT_EVIDENCE" and r["shift_pct"] is None


def test_mixed_month_is_excluded_from_both_arms(tmp_path):
    r = row(run(join_fixture(tmp_path, nrt_level=36, mixed_month="2023-06")))
    assert r["mixed_months"] == 1 and r["compared_months"] == 6 and r["first_nrt_month"] == "2023-07"


def test_nrt_only_and_missing_platforms_are_not_applicable(tmp_path):
    ds = join_fixture(tmp_path, nrt_from="2018-04")
    r = row(run(ds))
    assert r["status"] == "NOT_APPLICABLE" and "NRT-only" in r["reason"] and r["shift_pct"] is None
    assert row(run(ds), "SNPP")["status"] == "NO_STREAM_INFORMATION" and row(run(ds), "NOAA21")["shift_pct"] is None


def test_join_check_unavailable_without_product_stream_column(tmp_path):
    ds = build_ds(tmp_path, wavy)
    sj = run(ds)["stream_join"]
    assert sj["available"] is False and "product_stream" in sj["notes"][0]


# ------------------------------------------------------------------------------------------------ availability ingestion
ASSUMED_CSV = "data_id,min_date,max_date\nVIIRS_NOAA20_SP,2018-04-01,2025-10-31\nVIIRS_NOAA21_NRT,2024-01-17,2026-11-12\nMODIS_SP,2000-11-01,2025-10-31\n"


def test_parse_availability_keeps_source_identity():
    p = availability.parse(ASSUMED_CSV)
    assert p["VIIRS_NOAA20_SP"] == {"first": "2018-04-01", "last": "2025-10-31", "platform": "NOAA20", "stream": "SP"}
    assert p["VIIRS_NOAA21_NRT"]["platform"] == "NOAA21" and p["VIIRS_NOAA21_NRT"]["stream"] == "NRT"
    assert p["MODIS_SP"]["platform"] is None                       # MODIS platform is not in the source name: not guessed


def test_unknown_availability_layout_raises_instead_of_guessing():
    with pytest.raises(availability.AvailabilityFormatError):
        availability.parse("foo,bar\n1,2\n")
    with pytest.raises(availability.AvailabilityFormatError):
        availability.parse("data_id,min_date,max_date\n")


def test_availability_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(availability, "DATA", tmp_path)
    assert availability.load() is None
    rec = availability.save(ASSUMED_CSV, retrieved="2026-11-13T00:00:00+00:00")
    assert availability.load()["sources"]["MODIS_SP"]["first"] == "2000-11-01" and rec["origin"] == "FIRMS data_availability API"
    assert (tmp_path / "availability_raw.csv").read_text() == ASSUMED_CSV


def test_timeline_prefers_firms_availability_and_flags_disagreement(tmp_path):
    ds = join_fixture(tmp_path)
    ds.meta["product_availability"] = {"retrieved": "2026-11-13T00:00:00+00:00", "sources": availability.parse(ASSUMED_CSV)}
    t = {r["platform"]: r for r in run(ds)["platform_timeline"]["rows"]}
    assert t["NOAA20"]["documented_start"] == "2018-04-01" and "FIRMS data_availability API" in t["NOAA20"]["documented_start_basis"]
    assert t["NOAA20"]["firms_availability"][0]["stream"] == "SP" and t["NOAA20"]["flags"] == []
    ds.meta["product_availability"]["sources"]["VIIRS_NOAA20_SP"]["first"] = "2018-05-01"
    t = {r["platform"]: r for r in run(ds)["platform_timeline"]["rows"]}
    assert any("stored documented start" in f for f in t["NOAA20"]["flags"]) and any("precede the FIRMS-reported" in f for f in t["NOAA20"]["flags"])
    assert t["SNPP"]["documented_start_basis"] == "not verified" and t["SNPP"]["firms_availability"] == []


def test_timeline_without_availability_falls_back_to_config(tmp_path):
    t = {r["platform"]: r for r in run(join_fixture(tmp_path))["platform_timeline"]["rows"]}
    assert t["NOAA20"]["documented_start_basis"].startswith("config") and t["NOAA20"]["config_documented_start"] == "2018-04-01"


# ------------------------------------------------------------------------------------------------ platform cross-check, coverage
def raw(sat, src):
    return pd.DataFrame({"latitude": [7.5], "longitude": [80.5], "acq_date": ["2020-03-01"], "acq_time": [100], "satellite": [sat],
                         "confidence": ["n"], "frp": [1.0], "daynight": ["D"], "type": [0], "src": src})


def test_platform_filled_from_source_name_and_counted():
    rep = {}
    out = clean.clean(raw("zzz", "VIIRS_NOAA20_SP"), "viirs", rep)
    assert list(out["platform"]) == ["NOAA20"] and rep["platform_checks"] == {"filled_from_source_name": 1, "conflicts_satellite_vs_source": 0}


def test_platform_conflict_keeps_satellite_value_and_is_reported():
    rep = {}
    out = clean.clean(raw("N21", "VIIRS_NOAA20_SP"), "viirs", rep)
    assert list(out["platform"]) == ["NOAA21"] and rep["platform_checks"]["conflicts_satellite_vs_source"] == 1


def test_modis_platform_never_taken_from_source_name():
    rep = {}
    out = clean.clean(raw("zzz", "MODIS_SP").assign(confidence=["80"]), "modis", rep)
    assert list(out["platform"]) == ["UNKNOWN"] and rep["platform_checks"]["filled_from_source_name"] == 0
    assert list(schema.platform_from_src(["VIIRS_SNPP_SP", "MODIS_SP", "VIIRS_NOAA21_NRT", "VIIRS_X_SP"])) == ["SNPP", None, "NOAA21", None] or [None if pd.isna(x) else x for x in schema.platform_from_src(["VIIRS_SNPP_SP", "MODIS_SP", "VIIRS_NOAA21_NRT", "VIIRS_X_SP"])] == ["SNPP", None, "NOAA21", None]


def test_source_summary_reports_windows_per_source(tmp_path):
    f = tmp_path / "VIIRS_NOAA21_NRT"; f.mkdir()
    for d in ("2024-01-01_5", "2024-01-06_5", "2024-01-11_5", "2024-01-16_5", "2024-01-21_5", "2024-01-26_5", "2024-01-31_5"):
        (f / f"{d}.csv").write_text("latitude,longitude\n")
    s = coverage.source_summary(f)
    assert s["source"] == "VIIRS_NOAA21_NRT" and s["evidence"] == "DOWNLOAD_WINDOWS" and s["windows"] == 7
    assert s["first_covered_day"] == "2024-01-01" and s["fully_covered_months"] == 1 and s["first_full_month"] == "2024-01"
    assert coverage.source_summary(tmp_path / "missing")["evidence"] == "NONE"


# ------------------------------------------------------------------------------------------------ hotspot type accounting
def test_type_breakdown_counts_raw_codes_and_never_guesses_unknown_ones():
    df = pd.concat([raw("N", "VIIRS_SNPP_SP").assign(type=c) for c in (0, 0, 1, 2, 3, 7)], ignore_index=True)
    df["latitude"] = [7.5 + i / 100 for i in range(len(df))]
    rep = {}
    out = clean.clean(df, "viirs", rep)
    tb = {r["raw_code"]: r for r in rep["type_breakdown"]}
    assert tb[0]["count"] == 2 and tb[0]["kept"] and tb[1]["documented_meaning"] == "active volcano" and not tb[1]["kept"]
    assert tb[7]["documented_meaning"].startswith("undocumented") and tb[7]["count"] == 1 and not tb[7]["kept"]
    assert sum(r["count"] for r in rep["type_breakdown"]) == 6 and len(out) == 2
    assert {s["step"]: s["removed"] for s in rep["steps"]}["type_filter"] == 4
    assert "official page not read" in tb[0]["basis"]
