"""Request handling for the local API (kept separate from the HTTP layer so it can be unit-tested)."""
from . import spatial, area
from .config import GRID


def selection_from_payload(payload):
    if not isinstance(payload, dict):
        raise spatial.GeometryError("Request body must be a JSON object.")
    if payload.get("geometry") is not None:
        return spatial.parse_geometry(payload["geometry"])
    pt = payload.get("point")
    if isinstance(pt, dict):
        return spatial.point_selection(pt.get("lat"), pt.get("lon"), pt.get("radius_km", 5.0),
                                       grid=GRID if pt.get("snap_to_grid") else None)
    raise spatial.GeometryError("Send either 'geometry' (GeoJSON polygon) or 'point' {lat, lon, radius_km}.")


def handle_area(ds, payload):
    sel = selection_from_payload(payload)
    return area.analyze(ds, sel, payload.get("start"), payload.get("end"), payload.get("platforms"), payload.get("baseline"))


def health(ds):
    return {"ok": True, "data_origin": ds.origin, "first_month": str(ds.months[0]), "last_month": str(ds.months[-1]),
            "n_detections": int(len(ds.points)), "api": 1}


def handle_points(ds, payload):
    sel = selection_from_payload(payload)
    return area.points_for_month(ds, sel, payload.get("month"), profile=payload.get("profile"))


def handle_quality(ds, payload):
    """Quality-filter sensitivity for a drawn area, or for the whole processing region when no geometry/point is sent."""
    payload = payload if isinstance(payload, dict) else {}
    sel = selection_from_payload(payload) if (payload.get("geometry") is not None or payload.get("point") is not None) else None
    return area.quality_sensitivity(ds, sel, payload.get("start"), payload.get("end"), payload.get("baseline"), payload.get("profiles"))
