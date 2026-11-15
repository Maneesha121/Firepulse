"""Load raw FIRMS CSVs, remove INVALID records, flag quality problems, apply an optional analytical filter profile.

Three clearly separated layers (every removal is counted per rule in <CLEAN>/cleaning_report.json):

  1. INVALID / REDUNDANT records (always removed): non-numeric or impossible coordinates, unparseable dates, exact
     duplicate rows inside one source. step "kind" = invalid_record or redundant_record.
  2. SCOPE (always applied): outside the processing region, before the configured product start. kind = scope.
  3. ANALYTICAL FILTER (optional, configurable through config.QUALITY_PROFILES): FIRMS type rule, confidence rule and any
     flag-based rule of the active profile. kind = analytical_filter. These are project assumptions, not standards.

Files written (raw downloads in data/raw are never modified):
  <CLEAN>/<sensor>.csv.gz                  records that enter the analysis under the ACTIVE profile (schema unchanged + rec_id)
  <CLEAN>/all_valid/<sensor>.csv.gz        every valid in-scope record with its ORIGINAL attributes (the observations)
  <CLEAN>/quality/<sensor>_flags.csv.gz    quality flags, one row per all_valid record, joined on rec_id (kept separate)
  <CLEAN>/quality/<sensor>_rejected.csv.gz records removed in layers 1-2 with the reason
  <CLEAN>/cleaning_report.json, quality_report.json
"""
import json
import numpy as np, pandas as pd
from .config import (RAW, CLEAN, SOURCES, EXTRA_SOURCES, BBOX, MODIS_MIN_CONF, VIIRS_KEEP, MODIS_START,
                     VIIRS_START, DEMO, FIRE_TYPE_DOC, FIRE_TYPE_KEEP, FIRE_TYPE_BASIS, QUALITY_PROFILES, ACTIVE_PROFILE)
from . import schema, quality

START = {"modis": MODIS_START, "viirs": VIIRS_START}
REC = "_rec"        # raw record identifier column (source folder / file # row); becomes rec_id in cleaned tables


def folders_for(key):
    """Raw folders feeding one sensor family (primary source + any configured extras)."""
    names = [SOURCES[key]] + [n for n, fam in EXTRA_SOURCES.items() if fam == key]
    return [RAW / n for n in names]


def read_firms_csv(path):
    """Read one raw FIRMS CSV. Tolerates a UTF-8 BOM and stray whitespace in the header; the file itself is not changed."""
    d = pd.read_csv(path, dtype={"confidence": str}, encoding="utf-8-sig")
    d.columns = [str(c).strip().lstrip("\ufeff") for c in d.columns]
    return d


def load_raw(key):
    frames = []
    for folder in folders_for(key):
        for f in sorted(folder.glob("*.csv")) if folder.exists() else []:
            if f.stat().st_size > 0:
                d = read_firms_csv(f)
                if d.empty:       # header-only reply: retrieved, zero detections (coverage.py still counts the file as evidence)
                    continue
                d["src"] = folder.name
                d[REC] = [f"{folder.name}/{f.name}#{i}" for i in range(len(d))]
                frames.append(d)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _type_breakdown(col, keep):
    """Raw FIRMS 'type' codes with counts and the documented meaning; undocumented codes are labelled, never interpreted."""
    out = []
    for k, n in col.value_counts(dropna=False).sort_index().items():
        code = None if pd.isna(k) else (int(k) if float(k).is_integer() else float(k))
        out.append({"raw_code": code, "count": int(n), "kept": True if keep is None else code in keep,
                    "documented_meaning": FIRE_TYPE_DOC.get(code, "undocumented code (kept raw, not interpreted)"), "basis": FIRE_TYPE_BASIS})
    return out


def prepare(df, key, report=None, rejected=None):
    """Layers 1-2: remove invalid/redundant records and apply scope, build the standard observation table.

    Returns every valid in-scope record (NOT yet filtered by confidence/type). ``rejected`` (list) collects removed rows.
    """
    rep = report if report is not None else {}
    rep.update(sensor=key, rows_read=int(len(df)), steps=[])
    if df.empty:
        rep["rows_valid"] = 0
        return df
    cur = df.copy()
    if REC not in cur.columns:
        cur[REC] = [f"row#{i}" for i in range(len(cur))]

    def step(name, rule, keep, kind):
        nonlocal cur
        keep = pd.Series(np.asarray(keep, dtype=bool), index=cur.index)
        removed = int((~keep).sum())
        rep["steps"].append({"step": name, "rule": rule, "removed": removed, "kind": kind})
        if rejected is not None and removed:
            rejected.append(cur.loc[~keep].assign(reject_step=name, reject_kind=kind))
        cur = cur[keep]

    # --- layer 1: invalid / redundant. Duplicates are judged WITHIN a source: SP and NRT copies are never merged silently.
    step("duplicate_rows", "exact duplicate rows within one source (e.g. overlapping download windows)",
         ~cur.duplicated(subset=[c for c in cur.columns if c != REC]), "redundant_record")
    lat = pd.to_numeric(cur["latitude"], errors="coerce")
    lon = pd.to_numeric(cur["longitude"], errors="coerce")
    step("invalid_coordinate_format", "latitude/longitude not numeric", lat.notna() & lon.notna(), "invalid_record")
    lat, lon = lat.loc[cur.index], lon.loc[cur.index]
    step("coordinates_out_of_range", "|lat|>90 or |lon|>180", (lat.abs() <= 90) & (lon.abs() <= 180), "invalid_record")
    lat, lon = lat.loc[cur.index], lon.loc[cur.index]
    dates = pd.to_datetime(cur["acq_date"], errors="coerce")
    step("invalid_date", "acq_date not parseable", dates.notna(), "invalid_record")
    lat, lon, dates = lat.loc[cur.index], lon.loc[cur.index], dates.loc[cur.index]

    out = pd.DataFrame({
        "date": dates.values, "lat": lat.values, "lon": lon.values,
        "frp": pd.to_numeric(cur["frp"], errors="coerce").values if "frp" in cur else np.nan,
        "daynight": cur["daynight"].values if "daynight" in cur else "",
        "sensor": key,
        "platform": (schema.normalise_platform(cur["satellite"], key).values if "satellite" in cur else "UNKNOWN"),
        "confidence_raw": cur["confidence"].astype(str).values,
        "acq_time": cur["acq_time"].values if "acq_time" in cur else "",
        "src": cur["src"].values,
        "data_origin": schema.data_origin(DEMO)}, index=cur.index)
    out["product_stream"] = schema.product_stream(cur["src"])
    # The VIIRS source name is the documented FIRMS product identity. It fills platforms the 'satellite' column could not
    # map (UNKNOWN) and is cross-checked against it; a disagreement keeps the column value and is counted, never silent.
    from_src = pd.Series(schema.platform_from_src(cur["src"]), index=out.index)
    fill = (out["platform"] == "UNKNOWN") & from_src.notna()
    conflict = (out["platform"] != "UNKNOWN") & from_src.notna() & (out["platform"] != from_src)
    out.loc[fill, "platform"] = from_src[fill]
    rep["platform_checks"] = {"filled_from_source_name": int(fill.sum()), "conflicts_satellite_vs_source": int(conflict.sum())}
    if conflict.any():
        print(f"WARNING: {int(conflict.sum())} {key} rows have a 'satellite' value that disagrees with the source name; check schema._PLATFORM_MAP")
    for raw_col, dst in (("version", "version"), ("scan", "scan"), ("track", "track"), ("type", "fire_type")):
        if raw_col in cur.columns:
            out[dst] = cur[raw_col].values
    out["month"] = out["date"].dt.to_period("M").astype(str)
    out["rec_id"] = cur[REC].values

    # --- layer 2: scope
    cur = out
    w, s, e, n = BBOX
    step("study_region_bbox", f"inside processing region {BBOX}", cur["lat"].between(s, n) & cur["lon"].between(w, e), "scope")
    step("before_product_start", f"month >= {START[key]} (configured product start)", cur["month"] >= START[key], "scope")
    rep["rows_valid"] = int(len(cur))
    return cur.reset_index(drop=True)


def apply_profile(valid, key, report, profile, flags=None):
    """Layer 3: optional analytical filter. Returns the records that enter the analysis under ``profile``."""
    rep = report
    if valid.empty:
        rep["rows_kept"] = 0
        return valid
    valid = valid.reset_index(drop=True)
    if "fire_type" in valid.columns:
        rep["type_breakdown"] = _type_breakdown(valid["fire_type"], None if profile.get("type_keep") is None else set(profile["type_keep"]))
    if profile.get("drop_flags") and flags is None:
        flags = quality.assess({key: valid})[key]
    tis = flags["type_in_source"].to_numpy(bool) if flags is not None and len(flags) else None
    keep = np.ones(len(valid), bool)
    for name, rule, m in quality.profile_steps(valid, flags, profile, tis):
        removed = int((keep & ~m).sum())
        rep["steps"].append({"step": name, "rule": rule, "removed": removed, "kind": "analytical_filter"})
        keep &= m
    out = valid[keep].reset_index(drop=True)
    rep["rows_kept"] = int(len(out))
    rep["profile"] = profile.get("label")
    print(f"{key}: kept {len(out)} of {rep['rows_read']} detections after filters")
    return out


def clean(df, key, report=None, profile=None, flags=None):
    """Raw rows -> records for analysis under ``profile`` (default: the active profile). Backward-compatible entry point."""
    rep = report if report is not None else {}
    valid = prepare(df, key, rep)
    return apply_profile(valid, key, rep, profile or QUALITY_PROFILES[ACTIVE_PROFILE], flags)


def _write(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def run(profile_id=None):
    CLEAN.mkdir(parents=True, exist_ok=True)
    pid = profile_id or ACTIVE_PROFILE
    if pid not in QUALITY_PROFILES:
        raise ValueError(f"unknown quality profile '{pid}'; choose one of {sorted(QUALITY_PROFILES)}")
    prof = QUALITY_PROFILES[pid]
    reports, valid, rejected = {}, {}, {}
    for key in SOURCES:
        rep, rej = {}, []
        valid[key] = prepare(load_raw(key), key, rep, rej)
        reports[key], rejected[key] = rep, rej
    flags = quality.assess({k: v for k, v in valid.items() if len(v)})
    res = {}
    for key in SOURCES:
        v = valid[key]
        if v.empty:
            continue
        kept = apply_profile(v, key, reports[key], prof, flags[key])
        reports[key]["quality_flags_file"] = f"quality/{key}_flags.csv.gz"
        _write(v, CLEAN / "all_valid" / f"{key}.csv.gz")
        _write(flags[key], CLEAN / "quality" / f"{key}_flags.csv.gz")
        if rejected[key]:
            _write(pd.concat(rejected[key], ignore_index=True), CLEAN / "quality" / f"{key}_rejected.csv.gz")
        if not kept.empty:
            _write(kept, CLEAN / f"{key}.csv.gz")
            res[key] = kept
    origin = schema.data_origin(DEMO)
    (CLEAN / "cleaning_report.json").write_text(json.dumps({"data_origin": origin, "active_profile": pid, "sensors": reports}, indent=1, default=str))
    qrep = quality.summarise(valid, flags, active=pid)
    qrep.update(data_origin=origin, active_profile=pid, removal_steps={k: r["steps"] for k, r in reports.items()})
    (CLEAN / "quality_report.json").write_text(json.dumps(qrep, indent=1, default=str))
    return res
