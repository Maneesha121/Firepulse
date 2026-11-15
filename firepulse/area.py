"""Area-specific historical analysis: exact spatial filtering of cleaned detections + calendar/summaries.

The area calendar is rebuilt from the OBSERVATIONS inside the chosen geometry (point-in-polygon), not from
grid-cell centres. Months whose data status is not OBSERVED_* are unknown (null), never 0.
"""
import json
import numpy as np, pandas as pd
from . import spatial, harmonize, anomaly, coverage, sensor_transition, stream_join, quality, sensitivity
from .config import CLEAN, WEB_DATA, MIN_BASELINE, MIN_YEARS, QUALITY_PROFILES

PLATFORM_COLS = ["TERRA", "AQUA", "SNPP", "NOAA20", "NOAA21", "UNKNOWN"]
MIN_AREA_RATIO_MONTHS = 36          # usable overlap months needed before an area-specific ratio replaces the regional one
SMALL_AREA_KM2 = 1500.0
LOW_COUNT = 100                     # MODIS detections in the whole record below which ratios/anomalies are fragile


class AreaError(ValueError):
    pass


class Dataset:
    """Cleaned points + the metadata written by the pipeline. Loaded once, reused per request."""

    def __init__(self, clean_dir=CLEAN, meta_path=WEB_DATA / "meta.json"):
        meta_path = meta_path if hasattr(meta_path, "read_text") else __import__("pathlib").Path(meta_path)
        if not meta_path.exists():
            raise AreaError(f"{meta_path} not found. Run python run_pipeline.py (--demo for synthetic data) first.")
        self.meta = json.loads(meta_path.read_text())
        files = sorted(clean_dir.glob("*.csv.gz"))
        if not files:
            raise AreaError(f"No cleaned detections in {clean_dir}. Run python run_pipeline.py first.")
        self.points = pd.concat([pd.read_csv(f, parse_dates=["date"]) for f in files], ignore_index=True)
        origins = set(self.points["data_origin"].unique()) if "data_origin" in self.points else set()
        if origins != {self.meta.get("data_origin")}:
            raise AreaError("data/clean and web/data/meta.json come from different runs (or mix synthetic and NASA data). "
                            "Re-run python run_pipeline.py.")
        self.origin = self.meta["data_origin"]
        self.months = pd.PeriodIndex(self.meta["months"], freq="M")
        self.status = {k: pd.Series(v, index=self.months) for k, v in self.meta["status"].items()}
        self.evidence = self.meta.get("coverage_evidence", {})
        self.region_tables = {"global": self.meta["ratios"]["global"],
                              "by_month": {int(k): v for k, v in self.meta["ratios"]["by_month"].items()}}
        sp = self.meta.get("splice_idx")
        self.splice = str(self.months[sp]) if sp is not None else None
        self._lat = self.points["lat"].to_numpy(); self._lon = self.points["lon"].to_numpy()
        # First/last month with a detection per platform in the processed record (inferred from the data, NOT an
        # official mission date). Used by sensor_transition to mark platform-months as unavailable instead of zero.
        span = self.points.groupby("platform")["month"].agg(["min", "max"])
        self.platform_span = {p: (pd.Period(r["min"], "M"), pd.Period(r["max"], "M")) for p, r in span.iterrows()}
        self._region_series = None
        self.active_profile = self.meta.get("active_profile") or "baseline"
        self.evidence_by_month = self.meta.get("evidence_by_month")
        self._load_quality(clean_dir)

    def _load_quality(self, clean_dir):
        """Optional quality layer: every valid observation + its flags (separate tables, joined on rec_id). Absent = no sensitivity view."""
        self.q_points, self.quality_error, self._keep, self._reg_by_profile = None, None, {}, {}
        vdir, qdir = clean_dir / "all_valid", clean_dir / "quality"
        vs, fs = (sorted(vdir.glob("*.csv.gz")) if vdir.exists() else []), (sorted(qdir.glob("*_flags.csv.gz")) if qdir.exists() else [])
        if not vs or not fs:
            return
        allv = pd.concat([pd.read_csv(f, parse_dates=["date"]) for f in vs], ignore_index=True)
        fl = pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)
        if set(allv["data_origin"].unique()) != {self.origin}:
            raise AreaError("data/clean/all_valid comes from a different run (or mixes synthetic and NASA data). Re-run python run_pipeline.py.")
        if allv["rec_id"].duplicated().any() or fl["rec_id"].duplicated().any():
            self.quality_error = "Quality tables have duplicate record ids; re-run python run_pipeline.py."
            return
        q = allv.merge(fl, on="rec_id", how="left", validate="one_to_one")
        if q["flag_isolated"].isna().any():
            self.quality_error = "Some observations have no quality flags (files from different runs); re-run python run_pipeline.py."
            return
        for c in [c for c in q.columns if c.startswith("flag_")] + ["type_in_source", "isolation_assessed"]:
            q[c] = q[c].astype(bool)
        self.q_points = q
        self._qlat, self._qlon = q["lat"].to_numpy(), q["lon"].to_numpy()
        pid = self.active_profile if self.active_profile in QUALITY_PROFILES else "baseline"
        if int(self.profile_keep(pid).sum()) != len(self.points):
            self.q_points = None
            self.quality_error = ("The quality layer does not match the cleaned detections (different run or profile). "
                                  "Re-run python run_pipeline.py.")

    def profile_keep(self, pid):
        """Boolean mask over q_points: records that enter the analysis under profile ``pid`` (cached)."""
        if pid not in QUALITY_PROFILES:
            raise AreaError(f"unknown quality profile '{pid}'; choose one of {sorted(QUALITY_PROFILES)}")
        if pid not in self._keep:
            self._keep[pid] = quality.profile_mask(self.q_points, self.q_points, QUALITY_PROFILES[pid])
        return self._keep[pid]

    def mask_q(self, sel):
        return spatial.points_in_selection(self._qlat, self._qlon, sel)

    def region_series(self, pid=None):
        """Monthly series for the whole processing region (cached). Used to validate the regional-ratio fallback."""
        if pid is not None and pid != self.active_profile and self.q_points is not None:
            if pid not in self._reg_by_profile:
                self._reg_by_profile[pid] = _series_from_points(self, self.q_points[self.profile_keep(pid)])
            return self._reg_by_profile[pid]
        if self._region_series is None:
            self._region_series = _series_from_points(self, self.points)
        return self._region_series

    def region_tables_for(self, pid):
        """Region-wide ratio tables for a profile (the pipeline's own tables for the active profile); None if no usable overlap."""
        if pid == self.active_profile:
            return self.region_tables
        try:
            return harmonize.ratio_tables(self.region_series(pid)[["modis", "viirs"]])
        except ValueError:
            return None

    def mask(self, sel):
        return spatial.points_in_selection(self._lat, self._lon, sel)


def _month_range(ds, start, end):
    first, last = ds.months[0], ds.months[-1]
    try:
        a = pd.Period(start, "M") if start else first
        b = pd.Period(end, "M") if end else last
    except Exception:
        raise AreaError("Dates must look like 2015-01 or 2015-01-31.")
    if a > b:
        raise AreaError("The start of the date range is after its end.")
    a, b = max(a, first), min(b, last)
    if a > b:
        raise AreaError(f"The date range is outside the processed record ({first} to {last}).")
    return a, b


def full_series(ds, sel):
    """Monthly series for the WHOLE record inside the selection (baselines must not depend on the date range)."""
    m = ds.mask(sel)
    return _series_from_points(ds, ds.points[m]), int(m.sum())


def _series_from_points(ds, pts):
    cnt = pts.groupby(["month", "platform"]).size().unstack(fill_value=0)
    cnt.index = pd.PeriodIndex(cnt.index, freq="M")
    cnt = cnt.reindex(ds.months).fillna(0).astype(int)
    for c in PLATFORM_COLS:
        if c not in cnt:
            cnt[c] = 0
    sens = pts.groupby(["month", "sensor"]).size().unstack(fill_value=0)
    sens.index = pd.PeriodIndex(sens.index, freq="M")
    sens = sens.reindex(ds.months).fillna(0)
    out = pd.DataFrame(index=ds.months)
    for k in ("modis", "viirs"):
        n = sens[k] if k in sens else pd.Series(0, index=ds.months)
        ok = ds.status[k].isin(coverage.OBSERVED)
        out[k] = np.where(ok, n, np.nan)
    plat_ok = {"TERRA": "modis", "AQUA": "modis", "SNPP": "viirs", "NOAA20": "viirs", "NOAA21": "viirs"}
    for c in PLATFORM_COLS:
        k = plat_ok.get(c)
        ok = ds.status[k].isin(coverage.OBSERVED) if k else pd.Series(True, index=ds.months)
        out["n_" + c] = np.where(ok, cnt[c], np.nan)
    return out


def _choose_tables(ds, base):
    try:
        t = harmonize.ratio_tables(base[["modis", "viirs"]])
        if t["global"]["n"] >= MIN_AREA_RATIO_MONTHS:
            return t, f"AREA ({t['global']['n']} usable overlap months inside the selection)"
    except ValueError:
        pass
    return ds.region_tables, "REGION (selection has too few usable overlap months; regional ratio applied, treat as low reliability)"


def _tables_for_profile(ds, base, pid):
    """Same rule as _choose_tables (area ratio if enough usable overlap months, else regional), per quality profile."""
    try:
        t = harmonize.ratio_tables(base[["modis", "viirs"]])
        if t["global"]["n"] >= MIN_AREA_RATIO_MONTHS:
            return t, f"AREA ({t['global']['n']} usable overlap months inside the selection)"
    except ValueError:
        pass
    t = ds.region_tables_for(pid)
    if t is None:
        return None, "no usable overlap months in the selection or the region"
    return t, "REGION (selection has too few usable overlap months; regional ratio applied, treat as low reliability)"


def quality_sensitivity(ds, sel=None, start=None, end=None, baseline="all_other_years", profiles=None):
    """Calendar / ratio / anomaly sensitivity to the quality-filter profile for a selection (None = whole region)."""
    if baseline is None:
        baseline = "all_other_years"
    if baseline not in BASELINES:
        raise AreaError(f"baseline must be one of {sorted(BASELINES)}.")
    a, b = _month_range(ds, start, end)
    prof = None
    if profiles:
        bad = [p for p in profiles if p not in QUALITY_PROFILES]
        if bad:
            raise AreaError(f"unknown quality profile(s) {bad}; choose from {sorted(QUALITY_PROFILES)}.")
        prof = {p: QUALITY_PROFILES[p] for p in profiles}
        act = ds.active_profile if ds.active_profile in QUALITY_PROFILES else "baseline"
        prof.setdefault(act, QUALITY_PROFILES[act])
    return sensitivity.analyze(ds, sel, a, b, baseline, series_fn=_series_from_points, tables_fn=_tables_for_profile, profiles=prof)


BASELINES = {"all_other_years": "same calendar month, all other years in the processed record (past and future)",
             "past_only": "same calendar month, earlier years only (what was knowable at the time; retrospective, not a forecast)"}


def _baseline_n(s, past_only=False):
    n = []
    for ts in s.index:
        m = (s.index.month == ts.month) & ((s.index.year < ts.year) if past_only else (s.index.year != ts.year))
        n.append(int(s[m].notna().sum()))
    return n


def analyze(ds, sel, start=None, end=None, platforms=None, baseline="all_other_years"):
    if baseline is None:
        baseline = "all_other_years"
    if baseline not in BASELINES:
        raise AreaError(f"baseline must be one of {sorted(BASELINES)}.")
    past = baseline == "past_only"
    try:
        psel = sensor_transition.parse_selection(platforms)
    except sensor_transition.PlatformSelectionError as e:
        raise AreaError(str(e))
    a, b = _month_range(ds, start, end)
    base, n_points = full_series(ds, sel)
    tables, basis = _choose_tables(ds, base)
    reg = base[["modis", "viirs"]]
    hz = harmonize.harmonize(reg, tables, splice=ds.splice)
    z_h = anomaly.series_anomalies(hz["harmonized"], past_only=past)
    z_m = anomaly.series_anomalies(reg["modis"], past_only=past)
    z_v = anomaly.series_anomalies(reg["viirs"], past_only=past)
    bn = _baseline_n(hz["harmonized"], past)
    rng = (base.index >= a) & (base.index <= b)
    rows = []
    for i, p in enumerate(base.index):
        if not rng[i]:
            continue
        r = base.iloc[i]
        sm, sv = ds.status["modis"].iloc[i], ds.status["viirs"].iloc[i]
        used = hz["source_used"].iloc[i]
        status = sm if used == "MODIS" else sv if used == "VIIRS" else (
            "MISSING_DATA" if (sm == "MISSING_DATA" and sv == "MISSING_DATA") else "INSUFFICIENT_EVIDENCE")
        both = not np.isnan(r["modis"]) and not np.isnan(r["viirs"])
        comb = np.nansum([r["modis"], r["viirs"]]) if not (np.isnan(r["modis"]) and np.isnan(r["viirs"])) else np.nan
        rows.append({
            "month": str(p), "year": p.year, "calendar_month": p.month,
            "modis": r["modis"], "viirs": r["viirs"],
            **{c.lower(): r["n_" + c] for c in PLATFORM_COLS},
            "raw_combined": comb,
            "combined_sensors": "MODIS+VIIRS" if both else "MODIS" if not np.isnan(r["modis"]) else "VIIRS" if not np.isnan(r["viirs"]) else "",
            "harmonized": hz["harmonized"].iloc[i], "h_lo": hz["h_lo"].iloc[i], "h_hi": hz["h_hi"].iloc[i], "source_used": used,
            "z": z_h["z"].iloc[i], "percentile": z_h["percentile"].iloc[i], "band": z_h["band"].iloc[i],
            "z_modis": z_m["z"].iloc[i], "z_viirs": z_v["z"].iloc[i], "baseline_n": bn[i],
            "modis_status": sm, "viirs_status": sv, "data_status": status,
            "n_observations": None if np.isnan(comb) else int(comb),
        })
    df = pd.DataFrame(rows)
    out = {
        "data_origin": ds.origin,
        "selection": {"kind": sel.kind, "description": sel.description, "area_km2": round(sel.area_km2, 2),
                      "bbox": list(sel.bbox), "geojson": sel.to_geojson()},
        "range": {"start": str(a), "end": str(b)},
        "n_points_in_selection_all_time": n_points,
        "ratio_basis": basis,
        "baseline_mode": baseline,
        "method": {"baseline": f"{BASELINES[baseline]} (>= {MIN_BASELINE} usable years, MAD > 0; otherwise no anomaly is shown)",
                   "baseline_mode": baseline,
                   "z": "0.6745*(x-median)/MAD", "spatial_filter": "exact point-in-polygon on detections (edge points inside)",
                   "min_area_ratio_months": MIN_AREA_RATIO_MONTHS},
        "months": _records(df),
        "yearly": _records(_yearly(df)),
        "seasonal": _records(_seasonal(df)),
    }
    out["summary"] = _summary(df, sel, out, base)
    out["sensor_intelligence"] = sensor_transition.build(ds, base, tables, basis, df, a, b, psel,
                                                         out["summary"]["missing_data_periods"])
    out["sensor_intelligence"]["stream_join"] = stream_join.build(ds, base, a, b)
    out["sensor_intelligence"]["notes"].extend(out["sensor_intelligence"]["stream_join"]["notes"])
    if past:
        out["summary"]["limitations"].append("Past-only baseline: months in the first years of the record have fewer than the minimum "
                                             f"{MIN_BASELINE} earlier years and show no anomaly. The score is retrospective, not a forecast. The VIIRS/MODIS ratio behind the "
                                             "harmonised index is still estimated from the whole record, so only the baseline, not the index, is past-only.")
    return out


def _yearly(df):
    g = df.groupby("year")
    y = pd.DataFrame({
        "modis_total": g["modis"].sum(min_count=1), "viirs_total": g["viirs"].sum(min_count=1),
        "raw_combined_total": g["raw_combined"].sum(min_count=1), "harmonized_total": g["harmonized"].sum(min_count=1),
        "months_in_range": g.size(), "months_with_index": g["harmonized"].count(),
    })
    y["complete_year"] = (y["months_with_index"] == 12)
    return y.reset_index()


def _seasonal(df):
    g = df.groupby("calendar_month")
    return pd.DataFrame({"harmonized_median": g["harmonized"].median(), "harmonized_mean": g["harmonized"].mean(),
                         "modis_median": g["modis"].median(), "viirs_median": g["viirs"].median(),
                         "years_with_index": g["harmonized"].count()}).reset_index()


def _runs(df, col, sensor):
    runs, cur = [], None
    for m, st in zip(df["month"], df[col]):
        bad = st not in coverage.OBSERVED
        if bad and cur and cur["status"] == st:
            cur["end"] = m
        elif bad:
            cur = {"sensor": sensor, "start": m, "end": m, "status": st}; runs.append(cur)
        else:
            cur = None
    return runs


def _summary(df, sel, out, base):
    h = df.dropna(subset=["harmonized"])
    s = {"total_modis_detections": _num(df["modis"].sum(min_count=1)), "total_viirs_detections": _num(df["viirs"].sum(min_count=1)),
         "months_with_index": int(len(h)), "monthly_average_index": _num(h["harmonized"].mean()) if len(h) else None}
    if len(h):
        top = h.loc[h["harmonized"].idxmax()]
        s["highest_observed_hotspot_activity_month"] = {"month": top["month"], "index": _num(top["harmonized"])}
        yc = out["yearly"]
        cy = [y for y in yc if y["complete_year"] and y["harmonized_total"] is not None]
        pool = cy or [y for y in yc if y["harmonized_total"] is not None]
        if pool:
            best = max(pool, key=lambda y: y["harmonized_total"])
            s["highest_observed_hotspot_activity_year"] = {"year": best["year"], "index_total": best["harmonized_total"],
                                                           "complete_year": bool(best["complete_year"])}
    s["lowest_month"] = None
    s["lowest_month_note"] = "Not reported: fewer than 36 months with data, so a minimum would not be meaningful."
    if len(h) >= 36:
        lo = h.loc[h["harmonized"].idxmin()]
        s["lowest_month"] = {"month": lo["month"], "index": _num(lo["harmonized"])}
        s["lowest_month_note"] = "Lowest observed value; low or zero months can reflect small counts in a small area."
    z = df["z"].dropna()
    s["anomaly_count_much_above"] = int((z >= 2).sum()); s["anomaly_count_much_below"] = int((z <= -2).sum())
    s["anomaly_months_assessed"] = int(len(z))
    s["missing_data_periods"] = _runs(df, "modis_status", "MODIS") + _runs(df, "viirs_status", "VIIRS")
    w = []
    if sel.area_km2 < SMALL_AREA_KM2:
        w.append(f"Small area ({sel.area_km2:.0f} km2): monthly counts are small and noisy; ratios and anomalies are less reliable.")
    if (df["modis"].sum(min_count=1) or 0) < LOW_COUNT:
        w.append(f"Fewer than {LOW_COUNT} MODIS detections in this area over the selected range; harmonisation is fragile.")
    if out["ratio_basis"].startswith("REGION"):
        w.append("The VIIRS/MODIS ratio was estimated for the whole processing region, not this area.")
    if s["anomaly_months_assessed"] == 0:
        w.append("No anomaly could be computed (baseline shorter than the minimum or no spread).")
    if (df["data_status"] == "INCOMPLETE_PERIOD").any():
        w.append("Some months are INCOMPLETE_PERIOD: coverage evidence exists for only part of the month.")
    if out["data_origin"] == "SYNTHETIC_DEMO":
        w.append("SYNTHETIC DEMONSTRATION DATA: not NASA observations.")
    w.append("Highest observed hotspot activity is not fire danger. Hotspots include agricultural burning and other heat sources.")
    s["limitations"] = w
    return s


def _num(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)


def _records(df):
    recs = df.to_dict("records")
    for r in recs:
        for k, v in list(r.items()):
            if isinstance(v, (np.floating, float)):
                r[k] = None if np.isnan(v) else float(v)
            elif isinstance(v, np.integer):
                r[k] = int(v)
            elif isinstance(v, np.bool_):
                r[k] = bool(v)
    return recs


def points_for_month(ds, sel, month, limit=5000, profile=None):
    """Real detections inside the selection for one month, as GeoJSON points (deterministic stride sample if > limit).

    ``profile`` (a quality profile id, e.g. 'all_valid') shows the records that profile would keep, with their quality flags.
    Default: the records of the active profile (what the calendar counts). Original confidence/FRP are returned unchanged.
    """
    try:
        per = pd.Period(month, "M")
    except Exception:
        raise AreaError("Month must look like 2015-01.")
    if per < ds.months[0] or per > ds.months[-1]:
        raise AreaError(f"Month is outside the processed record ({ds.months[0]} to {ds.months[-1]}).")
    pid = profile or ds.active_profile
    flag_names = [k for k in quality.FLAG_INFO]
    if ds.q_points is not None:
        if pid not in QUALITY_PROFILES:
            raise AreaError(f"unknown quality profile '{pid}'; choose one of {sorted(QUALITY_PROFILES)}.")
        q = ds.q_points
        act = ds.profile_keep(ds.active_profile if ds.active_profile in QUALITY_PROFILES else "baseline")
        m = (q["month"] == str(per)).to_numpy() & ds.mask_q(sel) & ds.profile_keep(pid)
        pts = q[m].assign(in_active=act[m]).sort_values(["date", "lat", "lon"])
    else:
        if profile and profile != ds.active_profile:
            raise AreaError("Quality profiles need the quality layer: re-run python run_pipeline.py.")
        pts = ds.points[(ds.points["month"] == str(per)).to_numpy() & ds.mask(sel)].sort_values(["date", "lat", "lon"])
    total = len(pts)
    stride = max(1, -(-total // limit))
    pts = pts.iloc[::stride]
    feats = []
    for r in pts.itertuples():
        props = {"date": str(r.date.date()), "platform": r.platform, "sensor": r.sensor,
                 "frp": None if pd.isna(r.frp) else float(r.frp), "daynight": r.daynight, "confidence": r.confidence_raw}
        if ds.q_points is not None:
            props.update(conf_class=r.conf_class, quality_profile=pid, in_active_profile=bool(r.in_active),
                         flags=[k for k in flag_names if getattr(r, "flag_" + k)])
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(r.lon), float(r.lat)]}, "properties": props})
    return {"type": "FeatureCollection", "features": feats, "data_origin": ds.origin,
            "meta": {"month": str(per), "total_in_selection": int(total), "returned": len(feats), "sampled": stride > 1,
                     "quality_profile": pid if ds.q_points is not None else None,
                     "note": "Individual detections (not aggregated counts)." + (f" Every {stride}th shown for display." if stride > 1 else "")}}
