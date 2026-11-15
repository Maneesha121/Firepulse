"""Observation-quality tests. Offline, deterministic, synthetic fixtures only (never real NASA data)."""
import json
import numpy as np, pandas as pd, pytest
from firepulse import clean, quality, area, api, sensitivity, config


def obs(rows, sensor="viirs", src="VIIRS_SNPP_SP"):
    """rows: (lat, lon, date, acq_time, conf, frp, daynight, platform, type)"""
    d = pd.DataFrame(rows, columns=["lat", "lon", "date", "acq_time", "confidence_raw", "frp", "daynight", "platform", "fire_type"])
    d["date"] = pd.to_datetime(d["date"]); d["sensor"] = sensor; d["src"] = src; d["product_stream"] = src.rsplit("_", 1)[-1]
    d["rec_id"] = [f"{src}/f.csv#{i}" for i in range(len(d))]
    return d


def flags_for(rows, **kw):
    return quality.assess({"viirs": obs(rows, **kw)}, today="2025-01-01", bbox=(70, 0, 90, 20))["viirs"]


ANCHORS = [(12.0, 85.0, "2020-01-01", 730, "n", 5.0, "D", "SNPP", 0), (12.0, 85.0, "2020-06-01", 730, "n", 5.0, "D", "SNPP", 0)]   # widen the date range so isolation is assessable


R0 = (8.0, 80.0, "2020-03-10", 730, "n", 5.0, "D", "SNPP", 0)


# ---------------------------------------------------------------- parsers
def test_conf_classes_modis_and_viirs_and_invalid():
    c, bad = quality.conf_class(["10", "30", "79", "80", "100", "abc", "150"], ["modis"] * 7)
    assert list(c) == ["low", "nominal", "nominal", "high", "high", "unknown", "unknown"] and list(bad) == [0, 0, 0, 0, 0, 1, 1]
    c, bad = quality.conf_class(["l", "N", "high", "x", "80"], ["viirs"] * 5)
    assert list(c) == ["low", "nominal", "high", "unknown", "unknown"] and list(bad) == [0, 0, 0, 1, 1]


def test_parse_hhmm():
    m = quality.parse_hhmm([0, 30, 1030, 2359, 2400, 1260, -5, "x", 10.5])
    assert m[:4].tolist() == [0, 30, 630, 1439] and np.isnan(m[4:]).all()


# ---------------------------------------------------------------- pair search
def test_pair_search_distance_and_days():
    lat = np.array([8.0, 8.0, 8.0, 8.0]); lon = np.array([80.0, 80.0009, 80.1, 80.0])   # ~100 m, ~11 km, same place next day
    day = np.array([100, 100, 100, 101]); minute = np.array([600, 605, 600, 600.0])
    p = quality.pair_search(lat, lon, day, minute, 5000, 2)
    pairs = {(int(a), int(b)): (round(d), int(dd)) for a, b, d, dd in zip(p.a, p.b, p.dist_m, p.dday)}
    assert set(pairs) == {(0, 1), (0, 3), (1, 3)} and pairs[(0, 1)][0] in range(95, 105) and pairs[(0, 3)] == (0, 1)
    assert 2 not in {a for a, _ in pairs} | {b for _, b in pairs}                          # 11 km away: not a neighbour
    assert len(quality.pair_search(lat[:1], lon[:1], day[:1], minute[:1], 5000, 2)) == 0


# ---------------------------------------------------------------- flags
def test_near_duplicate_flagged_not_removed_and_isolated_separately():
    rows = [R0, (8.0004, 80.0, "2020-03-10", 735, "n", 6.0, "D", "SNPP", 0),          # ~45 m, 5 min: near-duplicate
            (9.0, 81.0, "2020-03-10", 730, "n", 5.0, "D", "SNPP", 0),                  # far from everything: isolated
            (8.5, 80.5, "2020-03-01", 730, "n", 5.0, "D", "SNPP", 0), (8.5, 80.5, "2020-03-20", 730, "n", 5.0, "D", "SNPP", 0)]
    f = flags_for(rows + ANCHORS)
    assert f["flag_near_duplicate"].tolist()[:2] == [True, True] and f["flag_near_duplicate_later"].tolist()[:2] == [False, True]
    assert f["flag_isolated"].tolist()[:5] == [False, False, True, True, True]
    assert len(f) == 7                                                                  # nothing removed by assessing


def test_near_duplicate_needs_same_platform_and_time():
    other = (8.0004, 80.0, "2020-03-10", 735, "n", 6.0, "D", "NOAA20", 0)
    late = (8.0004, 80.0, "2020-03-10", 1100, "n", 6.0, "D", "SNPP", 0)
    f = flags_for([R0, other, late])
    assert not f["flag_near_duplicate"].any()


def test_cross_source_duplicate_prefers_sp_copy():
    a = obs([R0], src="VIIRS_SNPP_NRT"); b = obs([R0], src="VIIRS_SNPP_SP")
    f = quality.assess({"viirs": pd.concat([a, b], ignore_index=True)}, today="2025-01-01", bbox=(70, 0, 90, 20))["viirs"]
    assert f["flag_dup_cross_source"].all() and f["flag_dup_cross_source_later"].tolist() == [True, False]     # NRT copy is the one dropped


def test_dup_key_conflict_same_source_different_attributes():
    f = flags_for([R0, (8.0, 80.0, "2020-03-10", 730, "h", 9.0, "D", "SNPP", 0), (8.1, 80.0, "2020-03-10", 730, "n", 5.0, "D", "SNPP", 0)])
    assert f["flag_dup_key_conflict"].tolist() == [True, True, False]


def test_frp_missing_negative_zero_and_extreme_not_assumed_error():
    rng = np.random.default_rng(0)
    base = [(8 + i * 1e-3, 80 + (i % 7) * 1e-3, "2020-03-10", 730, "n", float(v), "D", "SNPP", 0) for i, v in enumerate(rng.gamma(2, 6, 300) + 0.5)]
    base += [(7.0, 80.0, "2020-03-11", 730, "n", 5000.0, "D", "SNPP", 0), (7.0, 80.2, "2020-03-12", 730, "n", np.nan, "D", "SNPP", 0),
             (7.0, 80.4, "2020-03-12", 730, "n", -1.0, "D", "SNPP", 0), (7.0, 80.6, "2020-03-12", 730, "n", 0.0, "D", "SNPP", 0)]
    f = flags_for(base + ANCHORS)
    n = len(base)
    assert f["flag_frp_extreme_high"].iloc[n - 4] and f["flag_frp_extreme_high"].sum() == 1
    assert f["flag_frp_missing"].iloc[n - 3] and f["flag_frp_negative"].iloc[n - 2] and f["flag_frp_zero"].iloc[n - 1]
    assert f["flag_frp_extreme_uncorroborated"].iloc[n - 4]                             # no neighbour within 5 km / 2 days
    assert not any(c.startswith("exclude") for c in f.columns)


def test_extreme_frp_threshold_needs_enough_records():
    f = flags_for([R0, (8.5, 80.5, "2020-03-10", 730, "n", 99999.0, "D", "SNPP", 0)])
    assert not f["flag_frp_extreme_high"].any()


def test_context_and_source_flags():
    rows = [(8.0, 80.0, "2020-03-10", 730, "n", 5.0, "N", "SNPP", 0),       # night flag at ~12:00 local solar time
            (8.1, 80.0, "2020-03-10", 2030, "n", 5.0, "X", "SNPP", 0),     # invalid day/night value
            (8.2, 80.0, "2020-03-10", 99, "l", 5.0, "N", "SNPP", 2),       # bad time, low-confidence night north of 7 N, type 2
            (8.3, 80.0, "2020-03-10", 730, "n", 5.0, "D", "SNPP", 9)]
    f = flags_for(rows)
    assert f["flag_daynight_time_mismatch"].tolist() == [True, False, False, False] and f["flag_daynight_invalid"].tolist() == [False, True, False, False]
    assert f["flag_acq_time_invalid"].tolist() == [False, False, True, False]
    assert f["flag_viirs_low_night_outside_documented_area"].tolist() == [False, False, True, False]
    assert f["flag_type_not_vegetation"].tolist() == [False, False, True, False] and f["flag_type_undocumented"].tolist() == [False, False, False, True]


def test_future_date_and_null_island():
    f = flags_for([(0.0, 0.0, "2020-03-10", 730, "n", 5.0, "D", "SNPP", 0), (8.0, 80.0, "2030-01-01", 730, "n", 5.0, "D", "SNPP", 0)])
    assert f["flag_null_island"].tolist() == [True, False] and f["flag_future_date"].tolist() == [False, True]


def test_isolation_not_assessed_at_region_or_period_edge():
    rows = [(0.02, 80.0, "2020-03-10", 730, "n", 5.0, "D", "SNPP", 0),               # within the isolation radius of the region edge
            (8.0, 80.0, "2020-03-10", 730, "n", 5.0, "D", "SNPP", 0), (9.0, 81.0, "2020-01-01", 730, "n", 5.0, "D", "SNPP", 0),
            (9.0, 81.0, "2020-06-01", 730, "n", 5.0, "D", "SNPP", 0)]               # first / last day of the record
    f = flags_for(rows)
    assert f["isolation_assessed"].tolist() == [False, True, False, False]
    assert f["flag_isolated"].tolist() == [False, True, False, False]               # unassessable records are never called isolated


# ---------------------------------------------------------------- cleaning layers
def raw(rows, src="VIIRS_SNPP_SP"):
    d = pd.DataFrame(rows, columns=["latitude", "longitude", "acq_date", "acq_time", "confidence", "frp", "daynight", "satellite", "type"])
    d["src"] = src
    return d


def test_invalid_vs_optional_filter_are_distinguished(monkeypatch):
    monkeypatch.setattr(clean, "DEMO", False)
    d = raw([(7.5, 80.5, "2020-03-01", 100, "n", 5.0, "D", "N", 0), (7.5, 80.5, "2020-03-01", 100, "n", 5.0, "D", "N", 0),
             ("x", 80.5, "2020-03-01", 100, "n", 5.0, "D", "N", 0), (7.6, 80.6, "2020-03-02", 100, "l", 5.0, "D", "N", 0)])
    rep = {}
    valid = clean.prepare(d, "viirs", rep)
    kinds = {s["step"]: s["kind"] for s in rep["steps"]}
    assert kinds["duplicate_rows"] == "redundant_record" and kinds["invalid_coordinate_format"] == "invalid_record" and kinds["study_region_bbox"] == "scope"
    assert len(valid) == 2 and rep["rows_valid"] == 2 and "confidence_filter" not in kinds       # optional filter not applied yet
    kept = clean.apply_profile(valid, "viirs", rep, config.QUALITY_PROFILES["baseline"])
    assert len(kept) == 1 and {s["step"]: s["kind"] for s in rep["steps"]}["confidence_filter"] == "analytical_filter"
    assert len(clean.apply_profile(valid, "viirs", {"rows_read": 4, "steps": []}, config.QUALITY_PROFILES["all_valid"])) == 2


def test_original_attributes_preserved(monkeypatch):
    monkeypatch.setattr(clean, "DEMO", False)
    d = raw([(7.5, 80.5, "2020-03-01", 100, "H", 123.456, "N", "N", 0)])
    v = clean.prepare(d, "viirs")
    assert v["confidence_raw"].iloc[0] == "H" and v["frp"].iloc[0] == 123.456 and v["src"].iloc[0] == "VIIRS_SNPP_SP" and v["platform"].iloc[0] == "SNPP"
    assert v["fire_type"].iloc[0] == 0 and v["daynight"].iloc[0] == "N"


def test_duplicates_judged_within_source_sp_and_nrt_never_merged(monkeypatch):
    monkeypatch.setattr(clean, "DEMO", False)
    row = (7.5, 80.5, "2020-03-01", 100, "n", 5.0, "D", "N", 0)
    d = pd.concat([raw([row], "VIIRS_SNPP_SP"), raw([row], "VIIRS_SNPP_NRT")], ignore_index=True)
    rep = {}
    v = clean.prepare(d, "viirs", rep)
    assert len(v) == 2 and {s["step"]: s["removed"] for s in rep["steps"]}["duplicate_rows"] == 0 and set(v["product_stream"]) == {"SP", "NRT"}


def test_bom_and_header_whitespace_csv(tmp_path):
    f = tmp_path / "a.csv"
    f.write_bytes(b"\xef\xbb\xbflatitude, longitude ,acq_date,confidence\n7.5,80.5,2020-03-01,n\n")
    d = clean.read_firms_csv(f)
    assert list(d.columns) == ["latitude", "longitude", "acq_date", "confidence"] and len(d) == 1


# ---------------------------------------------------------------- profiles
def test_profiles_have_expected_effect_and_never_drop_high_frp_or_isolated_by_default():
    rows = [R0, (8.0004, 80.0, "2020-03-10", 735, "n", 6.0, "D", "SNPP", 0), (9.0, 81.0, "2020-03-10", 730, "l", 5.0, "D", "SNPP", 0),
            (9.5, 81.5, "2020-03-10", 730, "h", np.nan, "D", "SNPP", 0), (7.0, 80.0, "2020-03-10", 730, "n", 9e5, "D", "SNPP", 2)]
    d = obs(rows); f = quality.assess({"viirs": d}, today="2025-01-01", bbox=(70, 0, 90, 20))["viirs"]
    n = lambda pid: int(quality.profile_mask(d, f, config.QUALITY_PROFILES[pid]).sum())
    assert n("all_valid") == 5 and n("baseline") == 3 and n("no_type_filter") == 4 and n("high_confidence") == 1
    assert n("default_no_duplicates") == 2 and n("default_valid_frp") == 2
    assert config.QUALITY_PROFILES["default_no_isolated"]["exploratory"] and not config.QUALITY_PROFILES["baseline"]["drop_flags"]
    assert all("frp_extreme_high" not in p["drop_flags"] for p in config.QUALITY_PROFILES.values())


def test_flag_profile_without_flags_is_refused():
    with pytest.raises(ValueError):
        quality.profile_steps(obs([R0]), None, config.QUALITY_PROFILES["default_no_isolated"])


# ---------------------------------------------------------------- pipeline run writes separate tables
def test_run_writes_observations_flags_and_report_separately(tmp_path, monkeypatch):
    monkeypatch.setattr(clean, "DEMO", False)
    monkeypatch.setattr(clean, "RAW", tmp_path / "raw"); monkeypatch.setattr(clean, "CLEAN", tmp_path / "clean")
    monkeypatch.setattr(clean, "SOURCES", {"modis": "MODIS_SP", "viirs": "VIIRS_SNPP_SP"}); monkeypatch.setattr(clean, "EXTRA_SOURCES", {})
    for sub, sat, conf in (("MODIS_SP", "Terra", ["80", "10", "55"]), ("VIIRS_SNPP_SP", "N", ["n", "l", "h"])):
        d = tmp_path / "raw" / sub; d.mkdir(parents=True)
        (d / "2020-03-01_5.csv").write_text("latitude,longitude,acq_date,acq_time,satellite,confidence,frp,daynight,type\n" +
                                            "\n".join(f"7.{i},80.{i},2020-03-0{i + 1},730,{sat},{c},5.{i},D,0" for i, c in enumerate(conf)) + "\nabc,80,2020-03-01,730,%s,n,1,D,0\n" % sat)
    before = {p: p.read_bytes() for p in (tmp_path / "raw").rglob("*.csv")}
    res = clean.run("baseline")
    assert {p: p.read_bytes() for p in (tmp_path / "raw").rglob("*.csv")} == before                      # raw files untouched
    c = tmp_path / "clean"
    allv, fl = pd.read_csv(c / "all_valid" / "viirs.csv.gz"), pd.read_csv(c / "quality" / "viirs_flags.csv.gz")
    assert len(allv) == 3 and len(res["viirs"]) == 2 and list(allv["rec_id"]) == list(fl["rec_id"])
    assert "flag_conf_low" not in allv.columns and "flag_conf_low" in fl.columns                          # flags live in their own table
    assert list(allv["confidence_raw"]) == ["n", "l", "h"]                                              # original confidence kept
    rej = pd.read_csv(c / "quality" / "viirs_rejected.csv.gz")
    assert list(rej["reject_step"]) == ["invalid_coordinate_format"]
    q = json.loads((c / "quality_report.json").read_text())
    for pid, p in q["profiles"].items():
        for k, s in p["sensors"].items():
            assert s["retained"] + s["excluded"] == s["valid_records"]
    assert q["profiles"]["baseline"]["sensors"]["viirs"]["retained"] == 2 and q["profiles"]["all_valid"]["sensors"]["modis"]["retained"] == 3


# ---------------------------------------------------------------- sensitivity + API on the synthetic dataset fixture
@pytest.fixture
def qds(fake_dataset):
    ds = fake_dataset
    q = ds.points.copy()
    q["confidence_raw"] = np.where(q["sensor"] == "modis", "80", "n")
    ds.points["confidence_raw"] = q["confidence_raw"]
    q["rec_id"] = [f"r{i}" for i in range(len(q))]
    for n in quality.FLAG_INFO:
        q["flag_" + n] = False
    q["flag_near_duplicate_later"] = (np.arange(len(q)) % 50 == 0)
    q["flag_isolated"] = (np.arange(len(q)) % 7 == 0)
    q["type_in_source"] = False; q["isolation_assessed"] = True; q["conf_class"] = "nominal"; q["n_neighbours"] = 1
    ds.q_points, ds.quality_error, ds._keep, ds._reg_by_profile = q, None, {}, {}
    ds._qlat, ds._qlon = q["lat"].to_numpy(), q["lon"].to_numpy()
    ds.active_profile = "baseline"
    return ds


def test_sensitivity_recomputes_chain_and_counts(qds):
    sel = area.spatial.parse_geometry({"type": "Polygon", "coordinates": [[[80, 7], [81, 7], [81, 8], [80, 8], [80, 7]]]})
    r = area.quality_sensitivity(qds, sel, "2015-01", "2020-12")
    assert r["available"] and [p["id"] for p in r["profiles"]][:2] == ["baseline", "all_valid"] and r["active_profile"] == "baseline"
    by = {p["id"]: p for p in r["profiles"]}
    assert by["baseline"]["vs_active"] is None and by["all_valid"]["records"]["retained"] >= by["baseline"]["records"]["retained"]
    flagged = int(qds.q_points.loc[qds.mask_q(sel), "flag_near_duplicate_later"].sum())
    assert by["baseline"]["records"]["retained"] - by["default_no_duplicates"]["records"]["retained"] == flagged
    assert all(p["records"]["retained"] + p["records"]["excluded_vs_all_valid"] == r["valid_records_in_selection"] for p in r["profiles"])
    assert by["default_no_isolated"]["exploratory"] and len(by["baseline"]["monthly"]) == 72
    assert by["baseline"]["ratio"]["usable_overlap_months"] > 0 and by["all_valid"]["vs_active"]["months_compared"] > 0


def test_sensitivity_keeps_unknown_months_null_and_rejects_bad_input(qds):
    r = area.quality_sensitivity(qds, None, "2010-01", "2011-12")                  # VIIRS not in the record before 2012
    m = r["profiles"][0]["monthly"]
    assert all(x["viirs"] is None for x in m) and all(x["modis"] is not None for x in m)
    with pytest.raises(area.AreaError):
        area.quality_sensitivity(qds, None, profiles=["nope"])
    with pytest.raises(area.AreaError):
        area.quality_sensitivity(qds, None, baseline="x")


def test_sensitivity_unavailable_without_quality_layer(fake_dataset):
    fake_dataset.q_points = None
    r = area.quality_sensitivity(fake_dataset)
    assert r["available"] is False and "run_pipeline" in r["reason"]


def test_api_quality_and_points_flags(qds):
    sq = {"geometry": {"type": "Polygon", "coordinates": [[[80, 7], [81, 7], [81, 8], [80, 8], [80, 7]]]}, "start": "2015-01", "end": "2016-12"}
    r = api.handle_quality(qds, sq)
    assert r["selection"] != "whole processing region" and json.dumps(r, allow_nan=False)           # JSON-safe: unknown = null
    assert api.handle_quality(qds, {})["selection"] == "whole processing region"
    pts = api.handle_points(qds, {**sq, "month": "2016-03", "profile": "all_valid"})
    p = pts["features"][0]["properties"]
    assert "flags" in p and p["confidence"] in ("80", "n") and pts["meta"]["quality_profile"] == "all_valid"
    with pytest.raises(area.AreaError):
        api.handle_points(qds, {**sq, "month": "2016-03", "profile": "zzz"})
