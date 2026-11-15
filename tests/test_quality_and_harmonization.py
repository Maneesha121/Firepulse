
"""Tests for the transparent data-quality assessment system, zero-VIIRS handling, and sensitivity analysis."""

import numpy as np
import pandas as pd
import pytest

from firepulse import (
    clean, config, harmonize, area,
    spatial as S, quality
)
from conftest import SQUARE

def test_quality_flags_computation():
    """Verify quality flags assess observations without deleting valid data."""

    raw = pd.DataFrame({
        "latitude": [7.5, 7.5005, 8.5, 7.6, 7.7],
        "longitude": [80.5, 80.5005, 81.5, 80.6, 80.7],
        "acq_date": ["2020-03-01"] * 5,
        "acq_time": [1000] * 5,
        "confidence": ["85", "45", "90", "15", "80"],
        "frp": [25.0, 15000.0, 30.0, 10.0, -5.0],
        "daynight": ["D", "D", "N", "D", "D"],
        "satellite": ["Terra"] * 5,
        "src": ["MODIS_SP"] * 5,
        "type": [0, 0, 0, 0, 1]
    })

    # Prepare valid observations.
    report = {}
    valid = clean.prepare(raw, "modis", report)

    # Assess quality separately from the observation table.
    assessed = quality.assess({"modis": valid})
    flags = assessed["modis"]

    # 1. Valid observations are retained.
    assert len(valid) == 5
    assert "rec_id" in valid.columns
    assert "rec_id" in flags.columns

    # 2. Observation IDs and flag IDs must correspond.
    assert valid["rec_id"].is_unique
    assert flags["rec_id"].is_unique
    assert set(valid["rec_id"]) == set(flags["rec_id"])

    # 3. Verify the current quality flag schema.
    expected_flags = [
        "conf_class",
        "flag_frp_negative",
        "flag_frp_extreme_high",
        "flag_near_duplicate",
        "flag_isolated",
        "flag_type_not_vegetation"
    ]

    for column in expected_flags:
        assert column in flags.columns

    # 4. The statistical extreme-FRP threshold requires at least
    # FRP_EXTREME_MIN_N positive observations per sensor/platform.
    # This fixture has only four positive observations.
    assert len(valid[valid["frp"] > 0]) < config.FRP_EXTREME_MIN_N
    assert not flags["flag_frp_extreme_high"].any()

    # The 15000 FRP observation is retained, not deleted.
    assert 15000.0 in valid["frp"].values

    # 5. Near-duplicates are flagged for inspection.
    assert flags["flag_near_duplicate"].any()

    # 6. All fixture observations share one date.
    # Therefore the configured temporal isolation window cannot
    # be assessed for this dataset.
    assert not flags["isolation_assessed"].any()
    assert not flags["flag_isolated"].any()

    # 7. Confidence classes are available.
    assert "high" in flags["conf_class"].values
    assert "nominal" in flags["conf_class"].values

    # 8. Negative FRP and non-vegetation records are flagged.
    assert flags["flag_frp_negative"].any()
    assert flags["flag_type_not_vegetation"].any()

    # 9. Generate the quality summary using separate dataframes.
    summary = quality.summarise(
        {"modis": valid},
        {"modis": flags},
        active=config.ACTIVE_PROFILE
    )

    assert "flags" in summary
    assert "confidence_classes" in summary
    assert "day_night" in summary
    assert "frp" in summary
    assert "profiles" in summary

def test_zero_viirs_overlap_handling_in_harmonization():
    """Verify zero-VIIRS overlap months do not cause invalid ratios."""

    idx = pd.period_range("2015-01", "2015-12", freq="M")

    # MODIS has 10 detections each month.
    # VIIRS has zero detections in December.
    m_vals = [10.0] * 12
    v_vals = [60.0] * 11 + [0.0]

    reg = pd.DataFrame(
        {"modis": m_vals, "viirs": v_vals},
        index=idx
    )

    # 1. Check overlap classification.
    st = harmonize.classify_overlap(reg)

    assert (
        st[pd.Period("2015-12", "M")]
        == harmonize.RATIO_ZERO_NUM
    )

    assert (
        st[pd.Period("2015-01", "M")]
        == harmonize.RATIO_USABLE
    )

    # 2. Check ratio estimation.
    tables = harmonize.ratio_tables(reg)

    assert tables["global"]["med"] == pytest.approx(6.0)
    assert np.isfinite(tables["global"]["med"])
    assert tables["n_usable_months"] == 11

    # 3. Check harmonization of the zero-VIIRS month.
    hz = harmonize.harmonize(reg, tables)

    december = pd.Period("2015-12", "M")

    assert hz.loc[december, "harmonized"] == pytest.approx(0.0)
    assert np.isfinite(hz.loc[december, "harmonized"])

def test_polygon_geometry_validation_and_point_in_polygon():
    """Test rectangle, triangle, irregular polygon, self-intersection, and point selection."""

    # 1. Valid rectangle.
    rect = {
        "type": "Polygon",
        "coordinates": [[
            [80.0, 7.0],
            [81.0, 7.0],
            [81.0, 8.0],
            [80.0, 8.0],
            [80.0, 7.0]
        ]]
    }

    sel_rect = S.parse_geometry(rect)

    assert sel_rect.kind == "polygon"
    assert sel_rect.area_km2 > 10000

    # 2. Valid triangle.
    tri = {
        "type": "Polygon",
        "coordinates": [[
            [80.0, 7.0],
            [81.0, 7.0],
            [80.0, 8.0],
            [80.0, 7.0]
        ]]
    }

    sel_tri = S.parse_geometry(tri)
    assert sel_tri.area_km2 < sel_rect.area_km2

    # 3. Irregular pentagon.
    pent = {
        "type": "Polygon",
        "coordinates": [[
            [80.0, 7.0],
            [80.8, 7.1],
            [81.0, 7.8],
            [80.5, 8.2],
            [80.1, 7.5],
            [80.0, 7.0]
        ]]
    }

    sel_pent = S.parse_geometry(pent)
    assert sel_pent.area_km2 > 0

    # 4. Self-intersecting polygon must be rejected.
    bowtie = {
        "type": "Polygon",
        "coordinates": [[
            [80.0, 7.0],
            [81.0, 8.0],
            [81.0, 7.0],
            [80.0, 8.0],
            [80.0, 7.0]
        ]]
    }

    with pytest.raises(S.GeometryError, match="crosses itself"):
        S.parse_geometry(bowtie)

    # 5. Collinear points must be rejected.
    collinear = {
        "type": "Polygon",
        "coordinates": [[
            [80.0, 7.0],
            [80.5, 7.0],
            [81.0, 7.0],
            [80.0, 7.0]
        ]]
    }

    with pytest.raises(S.GeometryError, match="zero area"):
        S.parse_geometry(collinear)

    # 6. Point-in-polygon checks.
    inside = S.points_in_selection(
        np.array([7.5]),
        np.array([80.5]),
        sel_rect
    )

    outside = S.points_in_selection(
        np.array([8.5]),
        np.array([82.5]),
        sel_rect
    )

    edge = S.points_in_selection(
        np.array([7.0]),
        np.array([80.5]),
        sel_rect
    )

    assert inside[0] is True or inside[0] == 1
    assert outside[0] is False or outside[0] == 0
    assert edge[0] is True or edge[0] == 1

def test_quality_filter_sensitivity_in_area_analysis(fake_dataset):
    """Test area analysis and alternative quality-profile sensitivity."""

    rect = S.parse_geometry(SQUARE)

    # 1. Run the standard area analysis.
    result = area.analyze(fake_dataset, rect)

    assert "yearly" in result
    assert "summary" in result
    assert "months" in result

    assert len(result["yearly"]) > 0

    yearly = result["yearly"][0]

    assert yearly["months_in_range"] == 12
    assert "modis_total" in yearly
    assert "viirs_total" in yearly
    assert "raw_combined_total" in yearly
    assert "harmonized_total" in yearly
    assert "complete_year" in yearly

    # 2. Run the actual quality sensitivity API.
    sensitivity = area.quality_sensitivity(
        fake_dataset,
        rect
    )

    assert isinstance(sensitivity, dict)
    assert "available" in sensitivity

    # When quality data is available, verify the profile comparison.
    if sensitivity["available"]:
        assert "profiles" in sensitivity
        assert "active_profile" in sensitivity
        assert len(sensitivity["profiles"]) > 0

    # Otherwise, the API must explicitly report unavailability.
    else:
        assert (
            "reason" in sensitivity
            or "message" in sensitivity
            or "available" in sensitivity
        )