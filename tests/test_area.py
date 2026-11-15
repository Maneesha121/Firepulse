import numpy as np, pandas as pd, pytest, copy
from firepulse import area, spatial as S, api
from conftest import SQUARE, TRIANGLE, _month_counts


def run(ds, geom=SQUARE, **kw):
    return area.analyze(ds, S.parse_geometry(geom), **kw)


def test_monthly_counts_match_known_fixture(fake_dataset):
    r = run(fake_dataset, start="2015-01", end="2015-12")
    for m in r["months"]:
        nm, nv = _month_counts(pd.Period(m["month"], "M"))
        assert (m["modis"], m["viirs"]) == (nm, nv)               # outside-cluster points are excluded
        assert m["terra"] + m["aqua"] == nm and m["snpp"] == nv   # platform identity preserved
        assert m["noaa20"] == 0 and m["raw_combined"] == nm + nv


def test_polygon_filter_changes_result_vs_bbox(fake_dataset):
    full, tri = run(fake_dataset), run(fake_dataset, TRIANGLE)
    assert tri["n_points_in_selection_all_time"] < full["n_points_in_selection_all_time"]
    assert tri["selection"]["area_km2"] == pytest.approx(full["selection"]["area_km2"] / 2, rel=0.02)


def test_date_range_filtering_and_clipping(fake_dataset):
    r = run(fake_dataset, start="2014-03-15", end="2015-02-28")
    assert r["months"][0]["month"] == "2014-03" and r["months"][-1]["month"] == "2015-02" and len(r["months"]) == 12
    r2 = run(fake_dataset, start="1990-01", end="2100-01")
    assert (r2["range"]["start"], r2["range"]["end"]) == ("2010-01", "2023-12")
    with pytest.raises(area.AreaError, match="after its end"):
        run(fake_dataset, start="2020-01", end="2019-01")
    with pytest.raises(area.AreaError, match="outside the processed record"):
        run(fake_dataset, start="2030-01", end="2031-01")
    with pytest.raises(area.AreaError, match="look like"):
        run(fake_dataset, start="banana")


def test_missing_data_is_null_not_zero(fake_dataset):
    r = run(fake_dataset, start="2010-01", end="2011-12")           # VIIRS did not exist yet
    assert all(m["viirs"] is None and m["viirs_status"] == "MISSING_DATA" for m in r["months"])
    assert all(m["modis"] is not None for m in r["months"])
    assert r["summary"]["total_viirs_detections"] is None
    assert all(m["combined_sensors"] == "MODIS" for m in r["months"])


def test_insufficient_evidence_month_is_unknown_even_with_no_rows(fake_dataset):
    ds = fake_dataset
    i = list(ds.months).index(pd.Period("2016-05", "M"))
    ds.status["modis"].iloc[i] = "INSUFFICIENT_EVIDENCE"
    r = run(ds, start="2016-04", end="2016-06")
    may = next(m for m in r["months"] if m["month"] == "2016-05")
    assert may["modis"] is None and may["modis_status"] == "INSUFFICIENT_EVIDENCE" and may["terra"] is None


def test_observed_zero_detection_month_is_zero_with_status(fake_dataset):
    far = {"type": "Polygon", "coordinates": [[[100, 10], [101, 10], [101, 11], [100, 11], [100, 10]]]}
    r = run(fake_dataset, far, start="2014-01", end="2014-12")
    assert r["n_points_in_selection_all_time"] == 0                 # empty selection does not crash
    assert all(m["modis"] == 0 and m["viirs"] == 0 for m in r["months"])
    assert r["summary"]["total_modis_detections"] == 0
    assert any("Small area" in w or "Fewer than" in w for w in r["summary"]["limitations"])


def test_yearly_totals_equal_sum_of_months(fake_dataset):
    r = run(fake_dataset, start="2013-01", end="2016-12")
    for y in r["yearly"]:
        ms = [m for m in r["months"] if m["year"] == y["year"]]
        assert y["modis_total"] == sum(m["modis"] for m in ms) and y["viirs_total"] == sum(m["viirs"] for m in ms)
        assert y["raw_combined_total"] == sum(m["raw_combined"] for m in ms) and y["complete_year"] is True


def test_incomplete_year_flagged(fake_dataset):
    r = run(fake_dataset, start="2013-01", end="2013-06")
    assert r["yearly"][0]["complete_year"] is False and r["yearly"][0]["months_in_range"] == 6


def test_seasonal_summary_has_twelve_months_and_peaks_in_feb_mar(fake_dataset):
    r = run(fake_dataset)
    assert [s["calendar_month"] for s in r["seasonal"]] == list(range(1, 13))
    top = max(r["seasonal"], key=lambda s: s["modis_median"])
    assert top["calendar_month"] in (2, 3)


def test_baseline_does_not_depend_on_selected_date_range(fake_dataset):
    a = {m["month"]: m["z"] for m in run(fake_dataset, start="2020-01", end="2023-12")["months"]}
    b = {m["month"]: m["z"] for m in run(fake_dataset)["months"] if m["month"] in a}
    assert a == b


def test_anomaly_needs_baseline_and_uses_same_calendar_month(fake_dataset):
    r = run(fake_dataset)
    for m in r["months"]:
        if m["baseline_n"] < 10:
            assert m["z"] is None and m["band"] == "insufficient data"
    jan = [m for m in r["months"] if m["calendar_month"] == 1 and m["harmonized"] is not None]
    assert all(m["baseline_n"] == len(jan) - 1 for m in jan)       # baseline = same month in OTHER years


def test_highest_observed_activity_wording_and_limits(fake_dataset):
    s = run(fake_dataset)["summary"]
    assert "highest_observed_hotspot_activity_month" in s and "danger" in " ".join(s["limitations"]).lower()
    assert any("SYNTHETIC" in w for w in s["limitations"])
    assert "most_dangerous" not in str(s)


def test_lowest_month_only_when_enough_months(fake_dataset):
    assert run(fake_dataset, start="2015-01", end="2015-12")["summary"]["lowest_month"] is None
    assert run(fake_dataset)["summary"]["lowest_month"] is not None


def test_ratio_basis_reports_area_or_region(fake_dataset):
    assert run(fake_dataset)["ratio_basis"].startswith("AREA")
    assert run(fake_dataset, start="2020-01", end="2020-03")["ratio_basis"].startswith("AREA")   # basis uses the whole record
    far = {"type": "Polygon", "coordinates": [[[100, 10], [101, 10], [101, 11], [100, 11], [100, 10]]]}
    assert run(fake_dataset, far)["ratio_basis"].startswith("REGION")


def test_missing_periods_listed(fake_dataset):
    r = run(fake_dataset, start="2010-01", end="2013-12")
    runs = r["summary"]["missing_data_periods"]
    assert runs == [{"sensor": "VIIRS", "start": "2010-01", "end": "2011-12", "status": "MISSING_DATA"}]


def test_result_is_deterministic(fake_dataset):
    assert run(fake_dataset) == run(fake_dataset)


def test_json_safe(fake_dataset):
    import json
    json.dumps(run(fake_dataset), allow_nan=False) if False else None
    import serve
    json.dumps(serve._jsonable(run(fake_dataset)), allow_nan=False)


def test_dataset_refuses_mixed_origin(fake_dataset, tmp_path):
    import json, pathlib
    meta = json.loads((tmp_path / "meta.json").read_text()); meta["data_origin"] = "NASA_FIRMS"
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    with pytest.raises(area.AreaError, match="different runs"):
        area.Dataset(clean_dir=tmp_path / "clean", meta_path=tmp_path / "meta.json")


def test_api_payload_handling(fake_dataset):
    r = api.handle_area(fake_dataset, {"geometry": SQUARE, "start": "2015-01", "end": "2015-03"})
    assert len(r["months"]) == 3
    p = api.handle_area(fake_dataset, {"point": {"lat": 7.5, "lon": 80.5, "radius_km": 20}, "start": "2015-01", "end": "2015-03"})
    assert p["selection"]["kind"] == "point_buffer" and "20 km" in p["selection"]["description"]
    c = api.handle_area(fake_dataset, {"point": {"lat": 7.55, "lon": 80.55, "snap_to_grid": True}})
    assert c["selection"]["kind"] == "point_cell"
    for bad in [None, {}, {"point": {"lat": 1}}, {"geometry": {"type": "Point", "coordinates": [1, 2]}}]:
        with pytest.raises(S.GeometryError):
            api.handle_area(fake_dataset, bad)


def test_points_for_month_returns_real_detections_not_invented(fake_dataset):
    r = area.points_for_month(fake_dataset, S.parse_geometry(SQUARE), "2015-02")
    nm, nv = _month_counts(pd.Period("2015-02", "M"))
    assert r["meta"]["total_in_selection"] == nm + nv == r["meta"]["returned"] and not r["meta"]["sampled"]
    src = fake_dataset.points
    coords = {(round(la, 6), round(lo, 6)) for la, lo in zip(src.lat, src.lon)}
    assert all((round(f["geometry"]["coordinates"][1], 6), round(f["geometry"]["coordinates"][0], 6)) in coords for f in r["features"])
    assert {f["properties"]["platform"] for f in r["features"]} <= {"TERRA", "AQUA", "SNPP"}


def test_points_for_month_is_capped_and_declares_sampling(fake_dataset):
    r = area.points_for_month(fake_dataset, S.parse_geometry(SQUARE), "2015-02", limit=10)
    assert r["meta"]["sampled"] and r["meta"]["returned"] <= 10 < r["meta"]["total_in_selection"]
    with pytest.raises(area.AreaError):
        area.points_for_month(fake_dataset, S.parse_geometry(SQUARE), "1990-01")
    with pytest.raises(area.AreaError):
        area.points_for_month(fake_dataset, S.parse_geometry(SQUARE), "nonsense")
