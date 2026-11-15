"""Stage 5b: documented-vs-detected platform timeline, platform endings, product streams, attribution, FIRMS API chunking.
All fixtures are SYNTHETIC; documented dates under test are the ones recorded in config.DOCUMENTED_AVAILABILITY."""
import pandas as pd, pytest
from firepulse import area, clean, config, schema, download, spatial as S
from test_sensor_transition import build_ds, run, SQUARE


def two_viirs(noaa20_from="2018-04", snpp_until="2022-12", modis=10):
    """Terra MODIS all along; VIIRS S-NPP until a given month, NOAA-20 from a given month (both 60/month)."""
    def f(p, plat, zone):
        if zone != "W": return 0
        if plat == "TERRA": return modis
        if plat == "SNPP": return 60 if pd.Period("2012-01", "M") <= p <= pd.Period(snpp_until, "M") else 0
        if plat == "NOAA20": return 60 if p >= pd.Period(noaa20_from, "M") else 0
        return 0
    return f


def timeline(si):
    return {r["platform"]: r for r in si["platform_timeline"]["rows"]}


def test_documented_and_detected_availability_are_kept_separate(tmp_path):
    si = run(build_ds(tmp_path, two_viirs()))
    t = timeline(si)
    assert t["NOAA20"]["documented_start"] == "2018-04-01" and t["NOAA20"]["detected_first_month"] == "2018-04" and t["NOAA20"]["flags"] == []
    assert t["SNPP"]["documented_end"] == "2026-11-02" and t["SNPP"]["detected_last_month"] == "2022-12"
    assert t["NOAA21"]["in_record"] is False and t["NOAA21"]["detected_first_month"] is None and t["NOAA21"]["documented_start"] == "2024-01-17"
    assert t["TERRA"]["documented_start"] is None            # not verified -> not invented
    assert si["platform_timeline"]["retrieved"] == config.DOCUMENTED_RETRIEVED and "do not prove" not in si["platform_timeline"]["caution"].lower()


def test_detection_before_documented_start_is_flagged(tmp_path):
    si = run(build_ds(tmp_path, two_viirs(noaa20_from="2017-06")))
    assert any("precede the documented FIRMS start" in f for f in timeline(si)["NOAA20"]["flags"])
    assert any("NOAA-20: Detections precede" in n for n in si["notes"])


def test_platform_ending_is_reported_and_total_follows_remaining_platforms(tmp_path):
    si = run(build_ds(tmp_path, two_viirs()), start="2022-10", end="2023-03")
    assert [e["platform"] for e in si["platform_endings"]] == ["SNPP"] and si["platform_endings"][0]["last_detected_month"] == "2022-12"
    assert any("after 2022-12" in n and "2 November 2026" in n for n in si["notes"])
    m = {r["month"]: r for r in si["monthly"]}
    assert m["2022-11"]["viirs"] == 120 and m["2023-02"]["viirs"] == 60                 # S-NPP + NOAA-20, then NOAA-20 only
    assert m["2023-02"]["active_platforms"] == ["TERRA", "NOAA20"]
    sub = run(build_ds(tmp_path / "s" if (tmp_path / "s").mkdir() is None else None, two_viirs()),
              platforms={"viirs": ["SNPP"]}, start="2022-10", end="2023-03")
    assert sub["platform_endings"] == [] and all(r["viirs"] is None for r in sub["monthly"] if r["month"] >= "2023-01")   # unavailable, not zero


def test_product_streams_mixed_and_missing(tmp_path):
    ds = build_ds(tmp_path, two_viirs())
    assert run(ds)["product_streams"]["available"] is False                              # fixture has no product_stream column
    ds.points["product_stream"] = ds.points["month"].map(lambda m: "NRT" if m >= "2023-06" else "SP")
    ps = run(ds)["product_streams"]
    rows = {(r["platform"], r["stream"]): r for r in ps["rows"]}
    assert rows[("NOAA20", "NRT")]["first_month"] == "2023-06" and rows[("NOAA20", "SP")]["last_month"] == "2023-05"
    assert any("NOAA-20 mixes standard-processing (SP) and near-real-time (NRT)" in n for n in ps["notes"])
    ds.points["product_stream"] = "NRT"
    assert any("NRT-only" in n for n in run(ds)["product_streams"]["notes"])


def test_clean_keeps_source_attributes_and_stream():
    raw = pd.DataFrame({"latitude": [7.5, 7.6], "longitude": [80.5, 80.6], "acq_date": ["2020-03-01", "2020-03-02"], "acq_time": [100, 200],
                        "satellite": ["N20", "N20"], "confidence": ["n", "h"], "frp": [1.0, 2.0], "daynight": ["D", "N"], "type": [0, 0],
                        "scan": [0.39, 0.52], "track": [0.36, 0.45], "version": ["2.0NRT", "2.0NRT"], "src": "VIIRS_NOAA20_NRT"})
    out = clean.clean(raw, "viirs")
    assert list(out["platform"]) == ["NOAA20", "NOAA20"] and set(out["product_stream"]) == {"NRT"}
    assert list(out["scan"]) == [0.39, 0.52] and list(out["track"]) == [0.36, 0.45] and set(out["version"]) == {"2.0NRT"} and list(out["fire_type"]) == [0, 0]
    raw2 = raw.drop(columns=["scan", "track", "version"]).assign(src="VIIRS_SNPP_SP")
    out2 = clean.clean(raw2, "viirs")
    assert set(out2["product_stream"]) == {"SP"} and "scan" not in out2.columns


def test_product_stream_is_never_guessed():
    assert list(schema.product_stream(["VIIRS_NOAA20_NRT", "MODIS_SP", "modis_c6", "x_SP_old"])) == ["NRT", "SP", "UNKNOWN", "UNKNOWN"]


def test_api_attribution_matches_config_and_page(tmp_path):
    si = run(build_ds(tmp_path, two_viirs()))
    assert si["attribution"]["acknowledgment"] == config.ATTRIBUTION["acknowledgment"]
    assert "provided" in si["attribution"]["disclaimer"] and "as is" in si["attribution"]["disclaimer"].replace("\u201c", "").replace("\u201d", "")
    assert si["attribution"]["non_endorsement"].startswith("FirePulse is an independent project. NASA does not endorse")
    import html, pathlib
    page = html.unescape(pathlib.Path("web/index.html").read_text())
    for k in ("acknowledgment", "non_endorsement"):
        assert config.ATTRIBUTION[k] in page
    assert "Land, Atmosphere Near real-time Capability" in page


def test_download_uses_day_ranges_of_at_most_five(tmp_path, monkeypatch):
    urls = []
    monkeypatch.setattr(download, "RAW", tmp_path)
    monkeypatch.setattr(download, "_get", lambda u, tries=4: (urls.append(u), "latitude,longitude\n")[1])
    monkeypatch.setattr(download.time, "sleep", lambda s: None)
    download.download("2020-01-01", "2020-01-12", key="K" * 32, sources=["VIIRS_NOAA20_SP"])
    days = [int(u.split("/")[-2]) for u in urls]
    assert config.CHUNK_DAYS == 5 and days == [5, 5, 2] and all("VIIRS_NOAA20_SP" in u for u in urls)
    assert urls[0].endswith("/5/2020-01-01") and "K" * 32 in urls[0]
