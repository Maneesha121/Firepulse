"""Geometry validation, area, and exact point-in-polygon filtering (numpy only, no extra dependencies).

All geometry is GeoJSON in WGS84 (lon, lat).  Boundary rule: a point exactly ON a polygon edge is INSIDE.
Limits (stated, not hidden): rings crossing the antimeridian are rejected; holes are checked only by vertex
containment; polygons above MAX_VERTICES are rejected.
"""
import math
from dataclasses import dataclass, field
import numpy as np

EARTH_R_KM = 6371.0088
MAX_VERTICES = 3000


class GeometryError(ValueError):
    """Selected geometry is unusable; the message is written for end users."""


@dataclass
class Selection:
    kind: str                                   # polygon | multipolygon | point_buffer | point_cell
    polygons: list = field(default_factory=list)   # [ (outer_ring, [hole_rings]) ] ; rings are lists of (lon, lat), closed
    description: str = ""
    area_km2: float = 0.0
    bbox: tuple = (0, 0, 0, 0)                  # west, south, east, north

    def to_geojson(self):
        coords = [[ [list(p) for p in outer] ] + [[list(p) for p in h] for h in holes] for outer, holes in self.polygons]
        if len(coords) == 1:
            return {"type": "Polygon", "coordinates": coords[0]}
        return {"type": "MultiPolygon", "coordinates": coords}


def _num(v, what):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise GeometryError(f"{what} must be a finite number.")
    return float(v)


def _ring(raw, name):
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        raise GeometryError(f"{name} needs at least 3 points.")
    pts = []
    for p in raw:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            raise GeometryError(f"{name} contains a malformed position (expected [longitude, latitude]).")
        lon, lat = _num(p[0], "longitude"), _num(p[1], "latitude")
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise GeometryError(f"{name} has coordinates outside the valid range (longitude -180..180, latitude -90..90).")
        if not pts or (lon, lat) != pts[-1]:
            pts.append((lon, lat))
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    if len(pts) < 4:
        raise GeometryError(f"{name} needs at least 3 distinct points.")
    if len(pts) > MAX_VERTICES:
        raise GeometryError(f"{name} has {len(pts)} points; the limit is {MAX_VERTICES}. Simplify the shape.")
    lons = [p[0] for p in pts]
    if max(lons) - min(lons) > 180:
        raise GeometryError(f"{name} spans more than 180 degrees of longitude or crosses the antimeridian; this is not supported.")
    if _self_intersects(pts):
        raise GeometryError(f"{name} crosses itself. Draw a simple outline that does not intersect its own edges.")
    if abs(ring_area_km2(pts)) < 1e-6:
        raise GeometryError(f"{name} has zero area (points are collinear).")
    return pts


def _self_intersects(pts):
    a = np.array(pts[:-1], dtype=float)
    b = np.array(pts[1:], dtype=float)
    n = len(a)
    if n < 4:
        return False

    def orient(p, q, r):
        return (q[..., 0] - p[..., 0]) * (r[..., 1] - p[..., 1]) - (q[..., 1] - p[..., 1]) * (r[..., 0] - p[..., 0])

    for i in range(n):
        j = np.arange(i + 2, n)
        if i == 0:
            j = j[j != n - 1]               # first and last segment are adjacent
        if len(j) == 0:
            continue
        o1 = np.sign(orient(a[i], b[i], a[j])); o2 = np.sign(orient(a[i], b[i], b[j]))
        o3 = np.sign(orient(a[j], b[j], a[i])); o4 = np.sign(orient(a[j], b[j], b[i]))
        if np.any((o1 * o2 <= 0) & (o3 * o4 <= 0)):
            return True
    return False


def ring_area_km2(ring):
    """Signed spherical area of a closed lon/lat ring (Chamberlain & Duquette), km^2."""
    s = 0.0
    for (x1, y1), (x2, y2) in zip(ring[:-1], ring[1:]):
        s += math.radians(x2 - x1) * (2 + math.sin(math.radians(y1)) + math.sin(math.radians(y2)))
    return s * EARTH_R_KM ** 2 / 2.0


def _polygon(coords, label):
    if not isinstance(coords, (list, tuple)) or not coords:
        raise GeometryError(f"{label} has no coordinates.")
    outer = _ring(coords[0], f"{label} outline")
    holes = [_ring(h, f"{label} hole {i + 1}") for i, h in enumerate(coords[1:])]
    for h in holes:
        if not points_in_ring(np.array([p[1] for p in h[:-1]]), np.array([p[0] for p in h[:-1]]), outer).all():
            raise GeometryError(f"{label}: a hole lies outside the outline.")
    return outer, holes


def _finish(kind, polys, description):
    area = sum(abs(ring_area_km2(o)) - sum(abs(ring_area_km2(h)) for h in hs) for o, hs in polys)
    xs = [p[0] for o, _ in polys for p in o]; ys = [p[1] for o, _ in polys for p in o]
    return Selection(kind, polys, description, area, (min(xs), min(ys), max(xs), max(ys)))


def parse_geometry(obj):
    """GeoJSON Polygon / MultiPolygon / Feature / single-feature FeatureCollection -> Selection."""
    if not isinstance(obj, dict):
        raise GeometryError("Geometry must be a GeoJSON object.")
    t = obj.get("type")
    if t == "FeatureCollection":
        feats = obj.get("features") or []
        if len(feats) != 1:
            raise GeometryError("Provide exactly one feature (found %d)." % len(feats))
        return parse_geometry(feats[0])
    if t == "Feature":
        if not obj.get("geometry"):
            raise GeometryError("Feature has no geometry.")
        return parse_geometry(obj["geometry"])
    if t == "Polygon":
        return _finish("polygon", [_polygon(obj.get("coordinates"), "Polygon")], "Drawn polygon")
    if t == "MultiPolygon":
        parts = obj.get("coordinates")
        if not isinstance(parts, (list, tuple)) or not parts:
            raise GeometryError("MultiPolygon has no polygons.")
        return _finish("multipolygon", [_polygon(c, f"Polygon {i + 1}") for i, c in enumerate(parts)], "Drawn multi-polygon")
    if t == "Point":
        raise GeometryError("For a point use point_selection(lat, lon, radius_km) so the analysis extent is explicit.")
    raise GeometryError(f"Unsupported geometry type '{t}'. Use Polygon, MultiPolygon or a Feature containing one.")


def point_selection(lat, lon, radius_km=5.0, grid=None):
    """Point -> explicit square analysis extent. If ``grid`` is given, the grid cell containing the point is used."""
    lat, lon = _num(lat, "latitude"), _num(lon, "longitude")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise GeometryError("Point is outside the valid coordinate range.")
    if abs(lat) > 85:
        raise GeometryError("Point selection is not supported poleward of 85 degrees.")
    if grid:
        s, w = math.floor(lat / grid) * grid, math.floor(lon / grid) * grid
        ring = [(w, s), (w + grid, s), (w + grid, s + grid), (w, s + grid), (w, s)]
        sel = _finish("point_cell", [(ring, [])], f"{grid} degree grid cell containing the point")
        return sel
    radius_km = _num(radius_km, "radius")
    if not 0.1 <= radius_km <= 500:
        raise GeometryError("Analysis radius must be between 0.1 and 500 km.")
    dlat = radius_km / 111.195
    dlon = radius_km / (111.195 * math.cos(math.radians(lat)))
    if lon - dlon < -180 or lon + dlon > 180:
        raise GeometryError("Point is too close to the antimeridian for a buffer.")
    ring = [(lon - dlon, lat - dlat), (lon + dlon, lat - dlat), (lon + dlon, lat + dlat), (lon - dlon, lat + dlat), (lon - dlon, lat - dlat)]
    return _finish("point_buffer", [(ring, [])], f"Square of +/-{radius_km:g} km around the point")


def points_in_ring(lat, lon, ring):
    """Vectorised even-odd test; points on an edge or vertex count as inside."""
    lat = np.asarray(lat, dtype=float); lon = np.asarray(lon, dtype=float)
    inside = np.zeros(lat.shape, dtype=bool)
    on_edge = np.zeros(lat.shape, dtype=bool)
    for (x1, y1), (x2, y2) in zip(ring[:-1], ring[1:]):
        cross = (lon - x1) * (y2 - y1) - (lat - y1) * (x2 - x1)
        within = (np.minimum(x1, x2) - 1e-12 <= lon) & (lon <= np.maximum(x1, x2) + 1e-12) & \
                 (np.minimum(y1, y2) - 1e-12 <= lat) & (lat <= np.maximum(y1, y2) + 1e-12)
        on_edge |= (np.abs(cross) <= 1e-12) & within
        if y1 != y2:
            cond = ((y1 > lat) != (y2 > lat)) & (lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1)
            inside ^= cond
    return inside | on_edge


def points_in_selection(lat, lon, sel):
    """Exact filter: bounding-box pre-filter, then point-in-polygon (holes excluded)."""
    lat = np.asarray(lat, dtype=float); lon = np.asarray(lon, dtype=float)
    w, s, e, n = sel.bbox
    cand = (lon >= w) & (lon <= e) & (lat >= s) & (lat <= n)
    out = np.zeros(lat.shape, dtype=bool)
    idx = np.flatnonzero(cand)
    if idx.size == 0:
        return out
    la, lo = lat[idx], lon[idx]
    hit = np.zeros(idx.size, dtype=bool)
    for outer, holes in sel.polygons:
        m = points_in_ring(la, lo, outer)
        for h in holes:
            inh = points_in_ring(la, lo, h)
            # a point strictly inside a hole is outside; a point on the hole boundary stays inside
            m &= ~(inh & ~_on_boundary(la, lo, h))
        hit |= m
    out[idx] = hit
    return out


def _on_boundary(lat, lon, ring):
    on = np.zeros(lat.shape, dtype=bool)
    for (x1, y1), (x2, y2) in zip(ring[:-1], ring[1:]):
        cross = (lon - x1) * (y2 - y1) - (lat - y1) * (x2 - x1)
        within = (np.minimum(x1, x2) - 1e-12 <= lon) & (lon <= np.maximum(x1, x2) + 1e-12) & \
                 (np.minimum(y1, y2) - 1e-12 <= lat) & (lat <= np.maximum(y1, y2) + 1e-12)
        on |= (np.abs(cross) <= 1e-12) & within
    return on
