import numpy as np, pytest
from firepulse import spatial as S
from conftest import SQUARE


def sq(coords): return {"type": "Polygon", "coordinates": [coords]}


def test_area_of_one_degree_square_near_equator_latitude():
    sel = S.parse_geometry(SQUARE)
    assert sel.area_km2 == pytest.approx(12258, rel=0.01)           # ~111.2 km x ~110.2 km
    assert sel.bbox == (80.0, 7.0, 81.0, 8.0) and sel.kind == "polygon"


def test_inside_outside_and_boundary_points():
    sel = S.parse_geometry(SQUARE)
    lat = np.array([7.5, 7.0, 8.0, 7.5, 9.0, 7.5]); lon = np.array([80.5, 80.5, 81.0, 80.0, 80.5, 81.0001])
    assert S.points_in_selection(lat, lon, sel).tolist() == [True, True, True, True, False, False]   # edges and vertices are inside


def test_polygon_filter_is_not_a_bounding_box():
    tri = S.parse_geometry({"type": "Polygon", "coordinates": [[[80, 7], [81, 7], [80, 8], [80, 7]]]})
    inside_bbox_outside_poly = (7.9, 80.9)
    assert S.points_in_selection([7.9], [80.9], tri).tolist() == [False]
    assert S.points_in_selection([7.1], [80.1], tri).tolist() == [True]


def test_hole_excludes_points_but_keeps_hole_edge():
    donut = {"type": "Polygon", "coordinates": [
        [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]]}
    sel = S.parse_geometry(donut)
    assert S.points_in_selection([5, 2, 4], [5, 2, 5], sel).tolist() == [False, True, True]
    assert sel.area_km2 < S.parse_geometry(sq([[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]])).area_km2


def test_multipolygon_and_feature_wrappers():
    mp = {"type": "MultiPolygon", "coordinates": [SQUARE["coordinates"], [[[84, 7], [85, 7], [85, 8], [84, 8], [84, 7]]]]}
    sel = S.parse_geometry({"type": "Feature", "properties": {}, "geometry": mp})
    assert sel.kind == "multipolygon" and S.points_in_selection([7.5, 7.5, 7.5], [80.5, 84.5, 83], sel).tolist() == [True, True, False]
    fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": SQUARE}]}
    assert S.parse_geometry(fc).kind == "polygon"


def test_unclosed_ring_is_closed_and_duplicates_dropped():
    sel = S.parse_geometry(sq([[80, 7], [80, 7], [81, 7], [81, 8], [80, 8]]))
    assert sel.polygons[0][0][0] == sel.polygons[0][0][-1] and sel.area_km2 > 12000


@pytest.mark.parametrize("bad,fragment", [
    (sq([[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]), "crosses itself"),
    (sq([[0, 0], [1, 0], [2, 0], [0, 0]]), "zero area"),
    (sq([[0, 0], [1, 0]]), "at least 3"),
    (sq([[0, 0], [1, 0], [1, 95], [0, 0]]), "outside the valid range"),
    (sq([[170, 0], [-170, 0], [-170, 5], [170, 0]]), "antimeridian"),
    (sq([[0, 0], [1, "x"], [1, 1], [0, 0]]), "finite number"),
    (sq([[0, 0], [1, 0, 5], [1]]), "malformed"),
    ({"type": "Point", "coordinates": [0, 0]}, "point_selection"),
    ({"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, "Unsupported"),
    ({"type": "Polygon", "coordinates": []}, "no coordinates"),
    ({"type": "FeatureCollection", "features": []}, "exactly one"),
    ("not an object", "GeoJSON object"),
    ({"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], [[20, 20], [21, 20], [21, 21], [20, 20]]]}, "hole lies outside"),
])
def test_invalid_geometries_rejected_with_readable_messages(bad, fragment):
    with pytest.raises(S.GeometryError, match=fragment):
        S.parse_geometry(bad)


def test_vertex_limit():
    ring = [[80 + 0.0001 * i, 7 + (0.0001 if i % 2 else 0)] for i in range(S.MAX_VERTICES + 5)]
    with pytest.raises(S.GeometryError, match="limit"):
        S.parse_geometry(sq(ring))


def test_point_selection_buffer_and_cell():
    p = S.point_selection(7.5, 80.5, 10)
    assert p.kind == "point_buffer" and p.area_km2 == pytest.approx(400, rel=0.02) and "10 km" in p.description
    c = S.point_selection(7.55, 80.55, grid=0.1)
    assert c.kind == "point_cell" and c.bbox == pytest.approx((80.5, 7.5, 80.6, 7.6))
    for args in [(7.5, 80.5, 0.01), (7.5, 80.5, 900), (89, 0, 5), (91, 0, 5), (7, 179.99, 50), ("a", 1, 1), (float("nan"), 1, 1)]:
        with pytest.raises(S.GeometryError):
            S.point_selection(*args)


def test_empty_input_arrays():
    sel = S.parse_geometry(SQUARE)
    assert S.points_in_selection([], [], sel).tolist() == []
