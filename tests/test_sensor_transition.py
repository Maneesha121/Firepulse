"""Stage 5 tests: sensor-transition intelligence. All fixtures are SYNTHETIC and only check the arithmetic and the
safeguards; none of this says anything about real MODIS/VIIRS behaviour."""
import json
import numpy as np, pandas as pd, pytest
from firepulse import area, spatial as S, api, harmonize, sensor_transition as ST
from conftest import SQUARE

WEST = {"type": "Polygon", "coordinates": [[[80.0, 7.0], [80.5, 7.0], [80.5, 8.0], [80.0, 8.0], [80.0, 7.0]]]}
EAST = {"type": "Polygon", "coordinates": [[[80.5, 7.0], [81.0, 7.0], [81.0, 8.0], [80.5, 8.0], [80.5, 7.0]]]}
FAR = {"type": "Polygon", "coordinates": [[[100, 10], [101, 10], [101, 11], [100, 11], [100, 10]]]}
FAMILY = {"TERRA": "modis", "AQUA": "modis", "SNPP": "viirs", "NOAA20": "viirs", "NOAA21": "viirs"}


def build_ds(tmp_path, count, origin="SYNTHETIC_DEMO", first="2010-01", last="2023-12", viirs_start="2012-01",
             status_override=None):
    """count(period, platform, zone) -> int number of detections (None = no rows). Points are placed inside SQUARE:
    zone 'W' in the west half, zone 'E' in the east half."""
    months = pd.period_range(first, last, freq="M")
    rows = []
    for p in months:
        for plat in FAMILY:
            for zone, x0 in (("W", 80.05), ("E", 80.55)):
                n = count(p, plat, zone)
                for i in range(int(n or 0)):
                    rows.append((p.to_timestamp() + pd.Timedelta(days=i % 27), 7.1 + 0.8 * (i % 10) / 10, x0 + 0.4 * ((i * 3) % 10) / 10,
                                 FAMILY[plat], plat, str(p)))
    pts = pd.DataFrame(rows, columns=["date", "lat", "lon", "sensor", "platform", "month"])
    pts["frp"] = 5.0; pts["daynight"] = "D"; pts["confidence_raw"] = "n"; pts["acq_time"] = 1000; pts["src"] = "x"
    pts["data_origin"] = origin
    clean = tmp_path / "clean"; clean.mkdir()
    pts.to_csv(clean / "all.csv.gz", index=False)
    vs = pd.Period(viirs_start, "M")
    status = {"modis": ["OBSERVED_WITH_DETECTIONS"] * len(months),
              "viirs": ["MISSING_DATA" if p < vs else "OBSERVED_WITH_DETECTIONS" for p in months]}
    for (fam, month), st in (status_override or {}).items():
        status[fam][list(months).index(pd.Period(month, "M"))] = st
    meta = {"data_origin": origin, "months": [str(p) for p in months], "status": status,
            "coverage_evidence": {"modis": "DECLARED", "viirs": "DECLARED"}, "splice_idx": int(list(months).index(vs)),
            "ratios": {"global": {"med": 6.0, "q25": 6.0, "q75": 6.0, "n": 100},
                       "by_month": {str(m): {"med": 6.0, "q25": 6.0, "q75": 6.0, "n": 10} for m in range(1, 13)}}}
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    return area.Dataset(clean_dir=clean, meta_path=tmp_path / "meta.json")


def const(ratio, modis=10, noaa20_from=None):
    """Terra 6 + Aqua 4 = 10 MODIS per month; S-NPP = ratio x 10; optional NOAA-20 from a given month (extra VIIRS)."""
    def f(p, plat, zone):
        if zone != "W":
            return 0
        if plat == "TERRA": return modis * 0.6
        if plat == "AQUA": return modis * 0.4
        if plat == "SNPP": return modis * ratio if p >= pd.Period("2012-01", "M") else 0
        if plat == "NOAA20" and noaa20_from and p >= pd.Period(noaa20_from, "M"): return 5
        return 0
    return f


def run(ds, geom=SQUARE, **kw):
    return area.analyze(ds, S.parse_geometry(geom), **kw)["sensor_intelligence"]


def cal(si, which="selected_range"):
    return {r["calendar_month"]: r for r in si["calendar_ratio"][which]["months"]}


# ---------------------------------------------------------------------------------- monthly ratio calculations
def test_calendar_month_ratio_matches_known_constant(tmp_path):
    si = run(build_ds(tmp_path, const(6.0)))
    c = cal(si)
    for m in range(1, 13):
        assert c[m]["median"] == pytest.approx(6.0) and c[m]["q25"] == pytest.approx(6.0) and c[m]["q75"] == pytest.approx(6.0)
        assert c[m]["n_observations"] == 12 and c[m]["n_years"] == 12 and c[m]["evidence"] == "ADEQUATE"
    assert si["overlap"]["whole_record"]["usable_months"] == 144 and si["overlap"]["whole_record"]["first_month"] == "2012-01"


def test_median_and_quartiles_with_varying_ratio_match_numpy(tmp_path):
    ratio_by_year = {y: 2 + (y - 2012) for y in range(2012, 2024)}            # 2..13

    def f(p, plat, zone):
        if zone != "W": return 0
        if plat == "TERRA": return 10
        if plat == "SNPP": return 10 * ratio_by_year[p.year] if p.year >= 2012 else 0
        return 0
    si = run(build_ds(tmp_path, f))
    vals = list(ratio_by_year.values())
    for m, r in cal(si).items():
        assert r["median"] == pytest.approx(np.median(vals)) and r["q25"] == pytest.approx(np.quantile(vals, .25))
        assert r["q75"] == pytest.approx(np.quantile(vals, .75))


def test_same_numbers_as_existing_harmonisation_tables(tmp_path):
    ds = build_ds(tmp_path, const(6.0))
    base, _ = area.full_series(ds, S.parse_geometry(SQUARE))
    t = harmonize.ratio_tables(base[["modis", "viirs"]])
    si = run(ds)
    for m, r in cal(si, "whole_record").items():
        assert r["median"] == pytest.approx(t["by_month"][m]["med"]) and r["n_observations"] == t["by_month"][m]["n"]
    assert si["calendar_ratio"]["whole_record"]["global"]["median"] == pytest.approx(t["global"]["med"])


def test_monthly_series_values_and_labels(tmp_path):
    si = run(build_ds(tmp_path, const(6.0)), start="2015-01", end="2015-12")
    assert len(si["monthly"]) == 12
    for r in si["monthly"]:
        assert (r["modis"], r["viirs"], r["raw_combined"], r["ratio"]) == (10, 60, 70, pytest.approx(6.0))
        assert r["harmonized"] == pytest.approx(10.0)       # index on the MODIS-equivalent scale, distinct from raw_combined


# ---------------------------------------------------------------------------------- zero denominator / missing / low
def test_zero_denominator_gives_no_ratio_and_is_counted(tmp_path):
    def f(p, plat, zone):
        if zone != "W": return 0
        if plat == "TERRA": return 0 if (p.month == 1 and p.year in (2015, 2016)) else 10
        if plat == "SNPP": return 60 if p.year >= 2012 else 0
        return 0
    ds = build_ds(tmp_path, f)
    si = run(ds)
    jan = {r["month"]: r for r in si["monthly"]}["2015-01"]
    assert jan["ratio"] is None and jan["ratio_status"] == "ZERO_DENOMINATOR" and jan["ratio_unstable"] is None and jan["modis"] == 0
    c = cal(si)[1]
    assert c["n_zero_denominator"] == 2 and c["n_observations"] == 10 and c["median"] == pytest.approx(6.0)
    json.dumps(si, allow_nan=False)                           # no inf/NaN leaks


def test_low_denominator_is_reported_unstable_but_not_used(tmp_path):
    def f(p, plat, zone):
        if zone != "W": return 0
        if plat == "TERRA": return 2 if (p.month == 6 and p.year == 2018) else 10
        if plat == "SNPP": return 60 if p.year >= 2012 else 0
        return 0
    si = run(build_ds(tmp_path, f))
    r = {m["month"]: m for m in si["monthly"]}["2018-06"]
    assert r["ratio"] is None and r["ratio_status"] == "LOW_DENOMINATOR" and r["ratio_unstable"] == pytest.approx(30.0)
    assert cal(si)[6]["n_low_denominator"] == 1 and cal(si)[6]["median"] == pytest.approx(6.0)   # the 30x month is not in the median


def test_missing_month_is_null_and_excluded(tmp_path):
    ds = build_ds(tmp_path, const(6.0), status_override={("modis", "2016-05"): "INSUFFICIENT_EVIDENCE",
                                                            ("viirs", "2017-05"): "INCOMPLETE_PERIOD"})
    si = run(ds)
    m = {r["month"]: r for r in si["monthly"]}
    assert m["2016-05"]["modis"] is None and m["2016-05"]["ratio"] is None and m["2016-05"]["ratio_status"] == "NOT_BOTH_OBSERVED"
    assert m["2017-05"]["viirs"] is None and m["2017-05"]["incomplete"] is True
    assert cal(si)[5]["n_observations"] == 10
    assert {"sensor": "MODIS", "start": "2016-05", "end": "2016-05", "status": "INSUFFICIENT_EVIDENCE"} in si["missing_periods"]


# ---------------------------------------------------------------------------------- insufficient evidence
def test_insufficient_overlap_has_no_ratio_or_metrics(tmp_path):
    si = run(build_ds(tmp_path, const(6.0), viirs_start="2021-01"))        # only 3 overlap years
    for r in cal(si).values():
        assert r["n_observations"] == 3 and r["median"] is None and r["evidence"] == "INSUFFICIENT_EVIDENCE"
    assert si["calendar_ratio"]["selected_range"]["global"]["median"] is None
    assert all(y["smape_pct"] is None and y["correlation"] is None for y in si["validation"]["years"])
    assert si["validation"]["summary"]["years_with_metrics"] == 0 and si["validation"]["summary"]["evidence"] == "INSUFFICIENT_EVIDENCE"


def test_exploratory_label_for_five_to_nine_years(tmp_path):
    si = run(build_ds(tmp_path, const(6.0), viirs_start="2016-01"))        # 8 overlap years
    assert all(r["evidence"] == "EXPLORATORY" and r["median"] == pytest.approx(6.0) for r in cal(si).values())


def test_selected_range_without_overlap(tmp_path):
    si = run(build_ds(tmp_path, const(6.0)), start="2010-01", end="2011-12")
    assert si["overlap"]["in_range"]["usable_months"] == 0 and all(r["median"] is None for r in cal(si).values())
    assert any("No usable overlap month" in n for n in si["notes"])
    assert all(r["viirs"] is None for r in si["monthly"])


# ---------------------------------------------------------------------------------- platform contribution
def test_platform_contribution_counts_and_percentages(tmp_path):
    si = run(build_ds(tmp_path, const(6.0)), start="2015-01", end="2015-12")
    o = {p["platform"]: p for p in si["contribution"]["overall"]["platforms"]}
    assert o["TERRA"]["detections"] == 12 * 6 and o["AQUA"]["detections"] == 12 * 4 and o["SNPP"]["detections"] == 12 * 60
    assert o["TERRA"]["percent"] == pytest.approx(100 * 72 / 840) and o["SNPP"]["percent"] == pytest.approx(100 * 720 / 840)
    assert sum(p["percent"] for p in o.values() if p["percent"] is not None) == pytest.approx(100)
    assert si["contribution"]["overall"]["total_detections"] == 840 and si["contribution"]["range"] == {"start": "2015-01", "end": "2015-12"}
    assert si["contribution"]["family_totals"]["viirs"]["detections"] == 720


def test_unavailable_platform_is_null_not_zero_and_partial_is_flagged(tmp_path):
    si = run(build_ds(tmp_path, const(6.0, noaa20_from="2018-03")), start="2016-01", end="2019-12")
    o = {p["platform"]: p for p in si["contribution"]["overall"]["platforms"]}
    assert o["NOAA21"]["status"] == "UNAVAILABLE" and o["NOAA21"]["detections"] is None and o["NOAA21"]["percent"] is None
    assert o["NOAA20"]["status"] == "PARTIAL" and o["NOAA20"]["months_unavailable"] == 26 and o["NOAA20"]["detections"] == 5 * 22
    y2016 = next(y for y in si["contribution"]["by_year"] if y["year"] == 2016)
    assert y2016["detections"]["NOAA20"] is None and y2016["detections"]["SNPP"] == 12 * 60
    assert any("NOAA-21 has no data" in n for n in si["notes"])
    assert si["contribution"]["platform_record"]["NOAA20"]["first_month"] == "2018-03"
    assert any(m["platform"] == "NOAA20" for m in si["composition_changes"])        # platform mix change is surfaced


def test_contribution_is_not_a_physical_claim(tmp_path):
    si = run(build_ds(tmp_path, const(6.0)))
    assert "physical fires" in si["contribution"]["caution"]
    assert "not universal" in si["calendar_ratio"]["caution"]


# ---------------------------------------------------------------------------------- leave-one-year-out
def varying_ds(tmp_path, **kw):
    ratio_by_year = {y: 2 + (y - 2012) for y in range(2012, 2024)}            # distinct ratio each year (2..13)

    def f(p, plat, zone):
        if zone != "W": return 0
        if plat == "TERRA": return 10 + (p.month % 5)
        if plat == "SNPP": return round((10 + (p.month % 5)) * ratio_by_year[p.year]) if p.year >= 2012 else 0
        return 0
    return build_ds(tmp_path, f, **kw), ratio_by_year


def test_loyo_excludes_held_out_year_from_the_fit(tmp_path):
    ds, rby = varying_ds(tmp_path)
    si = run(ds)
    rows = {y["year"]: y for y in si["validation"]["years"]}
    for y in (2014, 2020, 2023):
        others = [r for yy, r in rby.items() if yy != y]
        with_all = list(rby.values())
        assert np.median(others) != np.median(with_all)               # test is able to detect leakage
        for mth in rows[y]["months"]:
            assert mth["ratio_used"] == pytest.approx(np.median(others), rel=0.02)   # integer rounding of counts only
            assert mth["predicted"] == pytest.approx(mth["viirs"] / mth["ratio_used"])


def test_loyo_calls_the_fit_without_each_held_out_year(tmp_path, monkeypatch):
    ds, _ = varying_ds(tmp_path)
    seen = []
    orig = harmonize.ratio_tables
    monkeypatch.setattr(harmonize, "ratio_tables", lambda region, exclude_year=None: (seen.append(exclude_year), orig(region, exclude_year))[1])
    base, _ = area.full_series(ds, S.parse_geometry(SQUARE))
    rows, _ = ST.loyo_report(base[["modis", "viirs"]])
    assert sorted(seen) == [r["year"] for r in rows] and None not in seen


def test_loyo_metrics_hand_computed(tmp_path):
    si = run(build_ds(tmp_path, const(6.0)))
    y = next(r for r in si["validation"]["years"] if r["year"] == 2018)
    assert y["status"] == "COMPLETE_YEAR" and y["n_valid_months"] == 12
    assert y["smape_pct"] == pytest.approx(0, abs=1e-9) and y["abs_bias"] == pytest.approx(0, abs=1e-9)
    assert y["correlation"] is None and "do not vary" in y["correlation_note"]        # constant series: correlation undefined


def test_loyo_bias_and_smape_values(tmp_path):
    """Held-out year 2020 has ratio 12 while all others have 6, so the other-year ratio (6) over-predicts MODIS by x2."""
    def f(p, plat, zone):
        if zone != "W": return 0
        if plat == "TERRA": return 10 + (p.month % 5)
        if plat == "SNPP": return (10 + (p.month % 5)) * (12 if p.year == 2020 else 6) if p.year >= 2012 else 0
        return 0
    si = run(build_ds(tmp_path, f))
    y = next(r for r in si["validation"]["years"] if r["year"] == 2020)
    assert y["bias_pct"] == pytest.approx(100.0) and y["abs_bias_pct"] == pytest.approx(100.0)
    assert y["smape_pct"] == pytest.approx(200 * 1 / 3 * 1, rel=1e-6)          # 2|2a-a|/(2a+a) = 2/3 -> 66.7 %
    assert y["abs_bias"] == pytest.approx(sum(m["predicted"] - m["actual"] for m in y["months"]))
    assert y["correlation"] == pytest.approx(1.0)                              # same seasonal shape; correlation hides the bias
    assert y["climatology_smape_pct"] is not None


def test_incomplete_years_and_insufficient_valid_months(tmp_path):
    ds = build_ds(tmp_path, const(6.0), viirs_start="2012-04", last="2023-04")
    si = run(ds)
    ys = {y["year"]: y for y in si["validation"]["years"]}
    assert ys[2012]["status"] == "PARTIAL_YEAR" and ys[2012]["n_valid_months"] == 9 and ys[2012]["smape_pct"] is not None
    assert ys[2023]["status"] == "INSUFFICIENT_VALID_MONTHS" and ys[2023]["n_valid_months"] == 4
    assert all(ys[2023][k] is None for k in ("smape_pct", "correlation", "bias", "abs_bias", "bias_pct", "mae"))
    assert "at least" in ys[2023]["reason"]
    assert [m["calendar_month"] for m in ys[2023]["months"]] == [1, 2, 3, 4]
    yearly = {y["year"]: y for y in si["ratio_over_time"]["annual"]}
    assert yearly[2023]["status"] == "INSUFFICIENT_USABLE_MONTHS" and yearly[2023]["median_ratio"] is None
    assert yearly[2012]["status"] == "PARTIAL_YEAR" and yearly[2015]["status"] == "COMPLETE_YEAR"


def test_validation_years_follow_selected_range(tmp_path):
    ds, _ = varying_ds(tmp_path)
    si = run(ds, start="2018-01", end="2019-12")
    assert [y["year"] for y in si["validation"]["years"]] == [2018, 2019]
    assert si["validation"]["summary"]["held_out_years_outside_range"] == 10


# ---------------------------------------------------------------------------------- area-specific + calibration source
def test_area_specific_ratios_differ(tmp_path):
    def f(p, plat, zone):
        r = 3 if zone == "W" else 9
        if plat == "TERRA": return 10
        if plat == "SNPP": return 10 * r if p.year >= 2012 else 0
        return 0
    ds = build_ds(tmp_path, f)
    w, e = run(ds, WEST), run(ds, EAST)
    assert all(r["median"] == pytest.approx(3.0) for r in cal(w).values())
    assert all(r["median"] == pytest.approx(9.0) for r in cal(e).values())
    assert w["calibration"]["source"] == "AREA" and e["calibration"]["source"] == "AREA"
    assert all(m["viirs"] == 30 for m in w["monthly"] if m["year"] >= 2012)


def test_regional_fallback_is_explained_and_validated_with_region_fit(tmp_path):
    ds = build_ds(tmp_path, const(6.0))
    si = run(ds, FAR)
    assert si["calibration"]["source"] == "REGION" and si["calibration"]["usable_overlap_months_in_selection"] == 0
    assert "REGIONAL ratio" in si["calibration"]["explanation"] and si["calibration"]["minimum_for_area_calibration"] == 36
    assert si["validation"]["summary"]["method"] == "REGION_TRANSFER_LOYO"
    assert all(r["median"] is None for r in cal(si).values())                  # an empty area has no observed ratio of its own
    assert all(y["smape_pct"] is None for y in si["validation"]["years"])
    ok = run(ds)
    assert ok["calibration"]["source"] == "AREA" and ok["validation"]["summary"]["method"] == "AREA_LOYO"


def test_area_with_fewer_than_36_overlap_months_uses_region(tmp_path):
    si = run(build_ds(tmp_path, const(6.0), viirs_start="2021-01"))             # 36 overlap months -> area; try 35
    assert si["calibration"]["source"] == "AREA"
    si2 = run(build_ds(tmp_path / "b", const(6.0), viirs_start="2021-02") if (tmp_path / "b").mkdir() is None else None)
    assert si2["calibration"]["source"] == "REGION" and si2["calibration"]["usable_overlap_months_in_selection"] == 35


def test_date_range_changes_ratio_window_but_not_the_index(tmp_path):
    ds, _ = varying_ds(tmp_path)
    a, b = run(ds, start="2013-01", end="2015-12"), run(ds)
    assert cal(a)[3]["median"] != cal(b)[3]["median"] and cal(a)[3]["n_observations"] == 3
    idx_a = {m["month"]: m["harmonized"] for m in a["monthly"]}
    idx_b = {m["month"]: m["harmonized"] for m in b["monthly"] if m["month"] in idx_a}
    assert idx_a == idx_b                                                       # harmonised index uses the whole-record ratio
    assert cal(a, "whole_record")[3]["median"] == cal(b, "whole_record")[3]["median"]


# ---------------------------------------------------------------------------------- platform selection
def test_platform_subset_is_strict_and_keeps_identity(tmp_path):
    ds = build_ds(tmp_path, const(6.0, noaa20_from="2018-03"))
    t_vs_s = run(ds, platforms={"modis": ["terra"], "viirs": ["S-NPP"]}, start="2015-01", end="2015-12")
    assert t_vs_s["selection"]["mode"] == "SUBSET" and t_vs_s["selection"]["description"] == "MODIS Terra vs VIIRS S-NPP"
    assert all(m["modis"] == 6 and m["viirs"] == 60 and m["ratio"] == pytest.approx(10.0) for m in t_vs_s["monthly"])
    n20 = run(ds, platforms={"viirs": ["NOAA20"]}, start="2017-01", end="2018-12")      # NOAA-20 starts 2018-03
    pre = [m for m in n20["monthly"] if m["month"] < "2018-03"]
    assert all(m["viirs"] is None and m["ratio"] is None and m["selection_gap"] == ["NOAA20"] for m in pre)   # unavailable, not zero
    assert all(m["viirs"] == 5 for m in n20["monthly"] if m["month"] >= "2018-03")
    assert n20["calibration"]["platform_selection_note"] and "all available platforms" in n20["calibration"]["platform_selection_note"]


def test_family_default_equals_all_platforms_selected(tmp_path):
    ds = build_ds(tmp_path, const(6.0, noaa20_from="2018-03"))
    a = run(ds)
    b = run(ds, platforms={"modis": ["AQUA", "TERRA"], "viirs": ["SNPP", "NOAA20", "NOAA21"]})
    assert a == b and a["selection"]["mode"] == "FAMILY"


@pytest.mark.parametrize("bad", ["x", {"modis": []}, {"modis": ["SNPP"]}, {"viirs": ["TERRA"]}, {"viirs": ["GOES"]}, {"modis": "TERRA"}])
def test_invalid_platform_selection_is_a_readable_error(tmp_path, bad):
    ds = build_ds(tmp_path, const(6.0))
    with pytest.raises(area.AreaError):
        api.handle_area(ds, {"geometry": SQUARE, "platforms": bad})


def test_api_passes_platform_selection(tmp_path):
    ds = build_ds(tmp_path, const(6.0))
    r = api.handle_area(ds, {"geometry": SQUARE, "start": "2015-01", "end": "2015-03", "platforms": {"modis": ["AQUA"]}})
    assert r["sensor_intelligence"]["selection"]["modis"] == ["AQUA"] and r["sensor_intelligence"]["monthly"][0]["modis"] == 4


# ---------------------------------------------------------------------------------- sensitivity
def test_sensitivity_tables(tmp_path):
    ds, _ = varying_ds(tmp_path)
    s = run(ds)["sensitivity"]
    labels = [w["label"] for w in s["time_period"]["windows"]]
    assert labels[:2] == ["Whole record", "Selected date range"] and "Earlier half of overlap years" in labels
    early, late = s["time_period"]["windows"][2], s["time_period"]["windows"][3]
    assert early["median"] < late["median"] and s["time_period"]["label"] == "LARGE_SPREAD"     # ratio drifts 2 -> 13 in this fixture
    assert s["time_period"]["leave_one_year_out_global_median"]["n_years"] == 12
    combos = {c["label"]: c for c in s["platform_combination"]["combinations"]}
    assert combos["MODIS Terra + MODIS Aqua vs VIIRS NOAA-21"]["status"] == "UNAVAILABLE" and combos["MODIS Terra vs VIIRS S-NPP"]["median"] is not None
    assert combos["MODIS Aqua vs VIIRS S-NPP"]["status"] == "UNAVAILABLE"                   # this fixture has no Aqua rows
    assert sum(1 for c in combos.values() if c["is_selected"]) == 0                          # default FAMILY mode is not one pair


def test_stable_ratio_gives_small_spread(tmp_path):
    s = run(build_ds(tmp_path, const(6.0)))["sensitivity"]
    assert s["time_period"]["label"] == "SMALL_SPREAD"
    pair = {c["label"]: c for c in s["platform_combination"]["combinations"]}["MODIS Terra + MODIS Aqua vs VIIRS S-NPP"]
    assert pair["median"] == pytest.approx(6.0) and pair["evidence"] == "ADEQUATE"


# ---------------------------------------------------------------------------------- provenance + safety
def test_synthetic_vs_nasa_provenance(tmp_path):
    syn = run(build_ds(tmp_path / "s" if (tmp_path / "s").mkdir() is None else None, const(6.0), origin="SYNTHETIC_DEMO"))
    nasa = run(build_ds(tmp_path / "n" if (tmp_path / "n").mkdir() is None else None, const(6.0), origin="NASA_FIRMS"))
    assert syn["provenance"]["is_synthetic"] and syn["provenance"]["interpretation_scope"] == "ILLUSTRATIVE_ONLY"
    assert "SYNTHETIC DEMONSTRATION DATA" in syn["provenance"]["statement"] and syn["notes"][0].startswith("SYNTHETIC")
    assert not nasa["provenance"]["is_synthetic"] and nasa["provenance"]["data_origin"] == "NASA_FIRMS"
    assert "NASA FIRMS" in nasa["provenance"]["statement"] and "SYNTHETIC" not in " ".join(nasa["notes"])
    assert "not differences in actual fire occurrence" in nasa["provenance"]["statement"]


def test_output_is_json_safe_deterministic_and_has_thresholds(tmp_path):
    ds, _ = varying_ds(tmp_path)
    a = run(ds, WEST)
    assert a == run(ds, WEST)
    json.dumps(a, allow_nan=False)
    assert a["thresholds"]["min_overlap_months_for_area_calibration"] == 36 and a["thresholds"]["min_modis_count_for_ratio"] == 5
    import serve
    json.dumps(serve._jsonable(area.analyze(ds, S.parse_geometry(WEST))), allow_nan=False)


def test_ratio_over_time_makes_overlap_visible_and_trend_is_descriptive(tmp_path):
    ds, _ = varying_ds(tmp_path)
    r = run(ds)["ratio_over_time"]
    assert (r["overlap_start"], r["overlap_end"]) == ("2012-01", "2023-12")
    assert r["trend"]["spearman_rho"] == pytest.approx(1.0) and r["trend"]["evidence"] == "EXPLORATORY" and "Descriptive only" in r["trend"]["note"]
    flat = run(build_ds(tmp_path / "f" if (tmp_path / "f").mkdir() is None else None, const(6.0)))["ratio_over_time"]["trend"]
    assert flat["spearman_rho"] is None                                        # no variation: rank correlation undefined
