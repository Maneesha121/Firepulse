"""Tests for route delivery and provenance preflight."""
import gzip

from serve import DASHBOARD_ROUTES, _enhance_dashboard
from validate_submission import _check_origin_file


def test_dashboard_enhancement_loads_styles_script_and_baseline_status_node():
    source = '<html><head></head><body><header><h1>FirePulse</h1></header><div id="peaks"></div></body></html>'
    result = _enhance_dashboard(source)
    assert 'href="/dashboard-enhancements.css"' in result
    assert 'src="/dashboard-enhancements.js"' in result
    assert 'id="baseNote"' in result
    assert _enhance_dashboard(result) == result


def test_dashboard_routes_are_all_served_by_the_app():
    assert DASHBOARD_ROUTES == {'/', '/index.html', '/overview', '/map', '/calendar', '/trends', '/advanced', '/about'}


def test_preflight_rejects_empty_cleaned_output(tmp_path):
    path = tmp_path / 'empty.csv.gz'
    with gzip.open(path, 'wt', encoding='utf-8', newline='') as handle:
        handle.write('date,data_origin\n')
    errors = []
    _check_origin_file(path, errors)
    assert any('contains no cleaned detections' in error for error in errors)


def test_preflight_rejects_non_nasa_provenance(tmp_path):
    path = tmp_path / 'demo.csv.gz'
    with gzip.open(path, 'wt', encoding='utf-8', newline='') as handle:
        handle.write('date,data_origin\n2020-01-01,SYNTHETIC_DEMO\n')
    errors = []
    _check_origin_file(path, errors)
    assert any('SYNTHETIC_DEMO' in error for error in errors)
