import json, threading, urllib.request, urllib.error
from http.server import ThreadingHTTPServer
import numpy as np, pandas as pd, pytest
from firepulse import coverage, clean, validate, download, schema
from conftest import SQUARE


# ---------------------------------------------------------------- coverage / data status
def test_windows_from_download_names_ignore_empty_files(tmp_path):
    (tmp_path / "2020-01-01_10.csv").write_text("latitude,longitude\n")          # retrieved, zero rows
    (tmp_path / "2020-01-11_10.csv").write_text("")                              # failed marker: NOT evidence
    wins, ev = coverage.folder_windows(tmp_path)
    assert ev == "DOWNLOAD_WINDOWS" and wins == [(pd.Timestamp("2020-01-01").date(), pd.Timestamp("2020-01-10").date())]


def test_declared_coverage_sidecar(tmp_path):
    (tmp_path / "coverage.json").write_text(json.dumps({"windows": [{"start": "2020-01-01", "end": "2020-02-29"}]}))
    wins, ev = coverage.folder_windows(tmp_path)
    cov = coverage.covered_days_by_month(wins)
    assert ev == "DECLARED" and cov[pd.Period("2020-01")] == 31 and cov[pd.Period("2020-02")] == 29


def test_missing_folder_is_no_evidence(tmp_path):
    assert coverage.folder_windows(tmp_path / "nope") == ([], "NONE")


def test_all_five_statuses():
    idx = pd.period_range("2011-12", "2012-05", freq="M")
    counts = pd.Series({pd.Period("2012-01"): 4, pd.Period("2012-03"): 0, pd.Period("2012-04"): 2}, dtype=int)
    covered = pd.Series({pd.Period("2012-01"): 31, pd.Period("2012-02"): 29, pd.Period("2012-03"): 31, pd.Period("2012-04"): 10})
    st = coverage.month_status(idx, counts, covered, "DECLARED", pd.Period("2012-01"))["status"].tolist()
    assert st == ["MISSING_DATA",              # before product start
                  "OBSERVED_WITH_DETECTIONS",  # full coverage + detections
                  "OBSERVED_ZERO_DETECTIONS",  # full coverage (Feb) + zero rows
                  "OBSERVED_ZERO_DETECTIONS",  # full coverage (Mar) + zero rows
                  "INCOMPLETE_PERIOD",         # partial coverage (Apr)
                  "INSUFFICIENT_EVIDENCE"]     # May: no rows, no coverage -> zero cannot be claimed


def test_rows_without_coverage_evidence_do_not_claim_completeness():
    idx = pd.period_range("2020-01", "2020-02", freq="M")
    df = coverage.month_status(idx, pd.Series({pd.Period("2020-01"): 3}, dtype=int), pd.Series(dtype=int), "NONE", pd.Period("2000-01"))
    assert df["status"].tolist() == ["OBSERVED_WITH_DETECTIONS", "INSUFFICIENT_EVIDENCE"] and df["evidence"].tolist() == ["NONE", "NONE"]


def test_family_coverage_combines_platform_streams_without_losing_earlier_coverage(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"; a.mkdir(); b.mkdir()
    (a / "coverage.json").write_text(json.dumps({"windows": [{"start": "2020-01-01", "end": "2020-03-31"}]}))
    (b / "coverage.json").write_text(json.dumps({"windows": [{"start": "2020-02-01", "end": "2020-03-31"}]}))
    cov, _ = coverage.family_coverage([a, b])
    assert cov[pd.Period("2020-01")] == 31
    assert cov[pd.Period("2020-02")] == 29
    assert cov[pd.Period("2020-03")] == 31


# ---------------------------------------------------------------- cleaning accounting
def _raw_modis(rows):
    cols = ["latitude", "longitude", "acq_date", "acq_time", "confidence", "frp", "daynight", "satellite", "type"]
    return pd.DataFrame(rows, columns=cols).assign(src="MODIS_SP")


def test_clean_counts_every_removal_and_keeps_platform(monkeypatch):
    monkeypatch.setattr(clean, "DEMO", False)
    raw = _raw_modis([
        (7.5, 80.5, "2020-01-05", 1000, "80", 5.0, "D", "Terra", 0),
        (7.5, 80.5, "2020-01-05", 1000, "80", 5.0, "D", "Terra", 0),          # exact duplicate
        (7.6, 80.6, "2020-01-06", 1000, "10", 5.0, "D", "Aqua", 0),           # confidence below 30
        ("x", 80.6, "2020-01-06", 1000, "90", 5.0, "D", "Aqua", 0),           # bad coordinate
        (95.0, 80.6, "2020-01-06", 1000, "90", 5.0, "D", "Aqua", 0),          # out of range
        (7.7, 80.7, "not-a-date", 1000, "90", 5.0, "D", "Aqua", 0),           # bad date
        (7.8, 80.8, "2020-01-07", 1000, "90", 5.0, "D", "Aqua", 2),           # not vegetation fire
        (20.0, 30.0, "2020-01-07", 1000, "90", 5.0, "D", "Aqua", 0),          # outside region
        (7.9, 80.9, "1999-01-07", 1000, "90", 5.0, "D", "Aqua", 0),           # before product start
        (7.9, 80.9, "2020-01-08", 1000, "90", 5.0, "N", "Weird", 0),          # unknown platform label
    ])
    rep = {}
    out = clean.clean(raw, "modis", rep)
    removed = {s["step"]: s["removed"] for s in rep["steps"]}
    assert removed == {"duplicate_rows": 1, "invalid_coordinate_format": 1, "coordinates_out_of_range": 1, "invalid_date": 1,
                       "type_filter": 1, "confidence_filter": 1, "study_region_bbox": 1, "before_product_start": 1}
    assert rep["rows_read"] == 10 and rep["rows_kept"] == len(out) == 2
    assert rep["rows_read"] - sum(removed.values()) == rep["rows_kept"]        # nothing disappears unaccounted
    assert sorted(out["platform"]) == ["TERRA", "UNKNOWN"]                      # unknown label never guessed
    assert set(out["data_origin"]) == {"NASA_FIRMS"} and "confidence_raw" in out


def test_clean_marks_synthetic_origin(monkeypatch):
    monkeypatch.setattr(clean, "DEMO", True)
    out = clean.clean(_raw_modis([(7.5, 80.5, "2020-01-05", 1000, "80", 5.0, "D", "Terra", 0)]), "modis")
    assert set(out["data_origin"]) == {"SYNTHETIC_DEMO"}


def test_viirs_confidence_filter_and_platform_codes(monkeypatch):
    monkeypatch.setattr(clean, "DEMO", False)
    raw = pd.DataFrame({"latitude": [7.5] * 5, "longitude": [80.5, 80.51, 80.52, 80.53, 80.54], "acq_date": ["2020-03-01"] * 5,
                        "acq_time": [100] * 5, "confidence": ["l", "n", "h", "nominal", "n"], "frp": 1.0, "daynight": "D",
                        "satellite": ["N", "N", "1", "2", "zzz"], "src": "V"})
    out = clean.clean(raw, "viirs")
    assert sorted(out["platform"]) == ["NOAA20", "NOAA21", "SNPP", "UNKNOWN"] and (out["confidence_raw"] != "l").all()


def test_normalise_platform_vocabulary():
    s = pd.Series(["Terra", "AQUA", "t", "x"])
    assert schema.normalise_platform(s, "modis").tolist() == ["TERRA", "AQUA", "TERRA", "UNKNOWN"]
    assert schema.normalise_platform(pd.Series(["N", "N20", "N21", "1", "2"]), "viirs").tolist() == ["SNPP", "NOAA20", "NOAA21", "NOAA20", "NOAA21"]


# ---------------------------------------------------------------- input validation
def test_validate_good_and_bad_files(tmp_path):
    good = tmp_path / "g.csv"
    good.write_text("latitude,longitude,acq_date,acq_time,satellite,confidence,frp,daynight,version\n7.5,80.5,2020-01-01,100,Terra,80,5,D,6.1NRT\n"
                    "95,80.5,2020-01-01,100,Terra,80,5,D,6.1\nabc,80,2020-13-01,100,Terra,80,5,D,6.1\n")
    r = validate.validate_file(good)
    assert r["ok"] and r["rows"] == 3 and r["coordinates_out_of_range"] == 1 and r["invalid_coordinate_format"] == 1 and r["invalid_dates"] == 1
    assert any("NRT" in n for n in r["notes"]) and r["satellite_values"] == {"Terra": 3}
    nocol = tmp_path / "n.csv"; nocol.write_text("lat,lon\n1,2\n")
    assert validate.validate_file(nocol)["ok"] is False
    empty = tmp_path / "e.csv"; empty.write_text("")
    assert validate.validate_file(empty)["ok"] is False
    folder = validate.validate_folder(tmp_path)
    assert folder["files_checked"] == 2 and str(empty) in folder["empty_files"]


def test_validate_main_exit_codes(tmp_path):
    (tmp_path / "g.csv").write_text("latitude,longitude,acq_date\n7.5,80.5,2020-01-01\n")
    assert validate.main(tmp_path) == 0
    (tmp_path / "b.csv").write_text("a,b\n1,2\n")
    assert validate.main(tmp_path) == 1
    assert validate.main(tmp_path / "empty_dir_does_not_exist") == 1


# ---------------------------------------------------------------- download cache fix
def test_error_reply_is_not_cached_and_header_only_reply_is(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "RAW", tmp_path)
    monkeypatch.setattr(download, "SOURCES", {"modis": "SRC"})
    monkeypatch.setattr(download, "EXTRA_SOURCES", {})
    monkeypatch.setattr(download, "CHUNK_DAYS", 10)   # this test is about caching, not window size (default is now 5; see test_stage5b)
    monkeypatch.setattr(download.time, "sleep", lambda *_: None)
    replies = iter(["Invalid MAP_KEY", "latitude,longitude,acq_date\n"])
    monkeypatch.setattr(download, "_get", lambda url: next(replies))
    failed = download.download("2020-01-01", "2020-01-20", key="k")
    files = sorted(p.name for p in (tmp_path / "SRC").glob("*.csv"))
    assert files == ["2020-01-11_10.csv"] and len(failed) == 1             # failed window retried next run, zero-row window cached
    wins, ev = coverage.folder_windows(tmp_path / "SRC")
    assert ev == "DOWNLOAD_WINDOWS" and len(wins) == 1


# ---------------------------------------------------------------- HTTP layer
@pytest.fixture
def server(fake_dataset, tmp_path):
    import serve
    web = tmp_path / "web"; web.mkdir(); (web / "index.html").write_text("<html>ok</html>")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), serve.make_handler(fake_dataset, web))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _post(url, body=None, raw=None):
    req = urllib.request.Request(url + "/api/area", data=raw if raw is not None else json.dumps(body).encode(), method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_http_health_static_and_area(server):
    h = json.loads(urllib.request.urlopen(server + "/api/health").read())
    assert h["ok"] and h["data_origin"] == "SYNTHETIC_DEMO"
    assert urllib.request.urlopen(server + "/index.html").read() == b"<html>ok</html>"
    code, body = _post(server, {"geometry": SQUARE, "start": "2015-01", "end": "2015-02"})
    assert code == 200 and len(body["months"]) == 2 and body["selection"]["area_km2"] > 12000


def test_http_errors_are_json_and_do_not_leak(server):
    assert _post(server, {"geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}})[0] == 422
    assert _post(server, raw=b"{bad json")[0] == 400
    assert _post(server, {"geometry": SQUARE, "start": "2020-01", "end": "2019-01"})[0] == 422
    req = urllib.request.Request(server + "/api/nope", data=b"{}", method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 404
