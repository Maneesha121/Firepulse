"""Observation-quality assessment for MODIS and VIIRS hotspot records.

Design rules (see docs/data_quality.md):
  * Raw downloaded files are never touched. Cleaned observations keep their original confidence, FRP, source, platform
    and type values.
  * Quality information is a SEPARATE table of flags (one row per observation, joined on ``rec_id``). A flag marks a
    record as unusual or suspicious; it does not remove it.
  * Only INVALID records are removed (see clean.py): unparseable or impossible coordinates, unparseable dates and exact
    duplicate rows. Everything in this module is a flag and/or an OPTIONAL analytical filter chosen through a profile
    (config.QUALITY_PROFILES).
  * Unusually high FRP is flagged statistically but is not treated as an error: large fires legitimately have high FRP.
  * Isolation is an exploratory flag. Small or isolated fires can be real, so no default profile drops them.

All thresholds are engineering choices defined in config.py.
"""
import numpy as np, pandas as pd
from . import config as C

# flag name -> (short label, group, what it means)
FLAG_INFO = {
    "null_island": ("Coordinate exactly 0,0", "validity", "Latitude and longitude are both exactly 0 (a common placeholder). Kept, flagged."),
    "acq_time_invalid": ("Acquisition time invalid", "validity", "acq_time is missing or is not a valid HHMM UTC time. The record's date is valid, so it is kept."),
    "future_date": ("Acquisition date in the future", "validity", "acq_date is later than the run date (plus one day)."),
    "dup_key_conflict": ("Same key, different attributes", "duplicate", "Same source, location, date, time and platform appear more than once with different other attributes (exact duplicates were already removed)."),
    "dup_cross_source": ("Same detection in two sources", "duplicate", "Same platform, location, date and time appear in more than one product source (for example SP and NRT)."),
    "dup_cross_source_later": ("Cross-source duplicate (lower precedence copy)", "duplicate", "The copy that would be dropped by the 'no duplicates' profile (SP is kept before NRT, then the earlier row)."),
    "near_duplicate": ("Suspicious near-duplicate", "duplicate", "Another detection from the same platform on the same date lies within the near-duplicate distance and time."),
    "near_duplicate_later": ("Near-duplicate (lower precedence copy)", "duplicate", "The copy that would be dropped by the 'no duplicates' profile."),
    "frp_missing": ("FRP missing", "frp", "FRP is empty or not numeric."),
    "frp_negative": ("FRP negative", "frp", "FRP below zero (not a physical power; may be a missing-value sentinel)."),
    "frp_zero": ("FRP exactly zero", "frp", "FRP equals zero. Reported, not claimed to be an error."),
    "frp_extreme_high": ("Extreme-high FRP (statistical)", "frp", "log(FRP) far above the median for that sensor and platform. NOT assumed to be an error; large fires are real."),
    "frp_extreme_uncorroborated": ("Extreme-high FRP with no neighbour", "frp", "Extreme-high FRP and no other detection within the isolation radius and window. Worth a manual look; still not an automatic error."),
    "conf_low": ("Low-confidence class", "confidence", "MODIS confidence below the low-class limit, or VIIRS 'l'."),
    "conf_invalid": ("Confidence unreadable", "confidence", "MODIS confidence not a number in 0-100, or VIIRS confidence not one of l/n/h."),
    "viirs_low_night_outside_documented_area": ("VIIRS low-confidence night outside the documented area", "source", "FIRMS documents low-confidence night VIIRS pixels only inside a stated area; this record is outside it."),
    "daynight_invalid": ("Day/night flag invalid", "context", "daynight is not D or N."),
    "daynight_time_mismatch": ("Day/night flag disagrees with clock time", "context", "Approximate local solar hour is implausible for the D/N flag (wide margins; not assessed near the poles)."),
    "type_not_vegetation": ("Type is not 'presumed vegetation fire'", "source", "FIRMS type code 1, 2 or 3 (volcano, other static land source, offshore)."),
    "type_undocumented": ("Type code not documented", "source", "FIRMS type code other than 0-3."),
    "large_pixel": ("Unusually large pixel", "source", "scan*track pixel area far above the platform median (edge-of-scan proxy)."),
    "isolated": ("Spatially and temporally isolated (exploratory)", "exploratory", "No other detection within the isolation radius and window. Small or isolated fires can be real: this is not a deletion rule."),
}
FLAG_COLS = ["flag_" + k for k in FLAG_INFO]
EXPLORATORY_FLAGS = {"isolated", "frp_extreme_high", "frp_extreme_uncorroborated", "daynight_time_mismatch", "large_pixel"}


# ------------------------------------------------------------------------------------------------ small parsers
def parse_hhmm(series):
    """acq_time (FIRMS writes HHMM as an integer, e.g. 30 = 00:30) -> minutes after 00:00 UTC, NaN when invalid."""
    x = pd.to_numeric(pd.Series(series).reset_index(drop=True), errors="coerce")
    ok = x.notna() & (x >= 0) & (x == np.floor(x.fillna(0)))
    hh, mm = x // 100, x % 100
    ok &= (hh <= 23) & (mm <= 59)
    return (hh * 60 + mm).where(ok).to_numpy(dtype=float)


def conf_class(conf_raw, sensor, modis_classes=None):
    """-> (class array of 'low'/'nominal'/'high'/'unknown', invalid bool array). Raw confidence is never altered."""
    mc = modis_classes or C.MODIS_CONF_CLASSES
    conf = pd.Series(conf_raw).reset_index(drop=True)
    sensor = pd.Series(sensor).reset_index(drop=True)
    num = pd.to_numeric(conf, errors="coerce")
    low = conf.astype(str).str.strip().str.lower().map(C.VIIRS_CONF_CLASSES)
    mod_ok = num.notna() & (num >= 0) & (num <= 100)
    mod_cls = pd.Series(np.where(num < mc["low_below"], "low", np.where(num >= mc["high_from"], "high", "nominal")), index=num.index)
    is_mod = sensor.eq("modis")
    cls = pd.Series("unknown", index=conf.index, dtype=object)
    cls[is_mod & mod_ok] = mod_cls[is_mod & mod_ok]
    v_ok = (~is_mod) & low.notna()
    cls[v_ok] = low[v_ok]
    invalid = (is_mod & ~mod_ok) | ((~is_mod) & low.isna())
    return cls.to_numpy(dtype=object), invalid.to_numpy(dtype=bool)


# ------------------------------------------------------------------------------------------------ pair search
def pair_search(lat, lon, day, minute, radius_m, max_days):
    """All unordered record pairs within ``radius_m`` metres and ``max_days`` days of each other.

    Uses a cell hash so it never builds an n x n matrix. Returns a DataFrame with columns a, b (row positions),
    dist_m, dday (>= 0, b is the later or same day) and dmin (signed minutes b - a, NaN if a time is missing).
    Distances use a local equirectangular approximation (accurate to well under 1 % at these radii).
    """
    cols = ["a", "b", "dist_m", "dday", "dmin"]
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    day, minute = np.asarray(day, np.int64), np.asarray(minute, float)
    n = len(lat)
    if n < 2:
        return pd.DataFrame({c: np.empty(0) for c in cols})
    cell_lat = max(radius_m, 1.0) / 111_320.0
    cell_lon = cell_lat / max(np.cos(np.radians(min(float(np.nanmax(np.abs(lat))), 85.0))), 0.02)
    ci, cj = np.floor(lat / cell_lat).astype(np.int64), np.floor(lon / cell_lon).astype(np.int64)
    idx = np.arange(n)
    right = pd.DataFrame({"b": idx, "ci": ci, "cj": cj, "d": day})
    combos = [(0, di, dj) for di, dj in ((0, 0), (0, 1), (1, -1), (1, 0), (1, 1))]
    combos += [(dd, di, dj) for dd in range(1, int(max_days) + 1) for di in (-1, 0, 1) for dj in (-1, 0, 1)]
    parts = []
    for dd, di, dj in combos:
        left = pd.DataFrame({"a": idx, "ci": ci + di, "cj": cj + dj, "d": day + dd})
        m = left.merge(right, on=["ci", "cj", "d"])
        if dd == 0 and di == 0 and dj == 0:
            m = m[m["a"] < m["b"]]
        if m.empty:
            continue
        a, b = m["a"].to_numpy(), m["b"].to_numpy()
        dy = lat[b] - lat[a]
        dx = (lon[b] - lon[a]) * np.cos(np.radians((lat[a] + lat[b]) / 2.0))
        dist = np.hypot(dx, dy) * 111_320.0
        keep = dist <= radius_m
        if keep.any():
            a, b, dist = a[keep], b[keep], dist[keep]
            parts.append(pd.DataFrame({"a": a, "b": b, "dist_m": dist, "dday": dd, "dmin": (minute[b] - minute[a]) + dd * 1440.0}))
    if not parts:
        return pd.DataFrame({c: np.empty(0) for c in cols})
    return pd.concat(parts, ignore_index=True)


# ------------------------------------------------------------------------------------------------ assessment
def _num(s):
    return pd.to_numeric(s, errors="coerce") if s is not None else None


def assess(valid_by_key, today=None, bbox=None):
    """Quality flags for every valid record.

    ``valid_by_key``: {sensor key: cleaned observation DataFrame} as produced by clean.prepare (must contain rec_id).
    Isolation and duplicate checks look across ALL supplied families at once (a MODIS detection can corroborate a VIIRS one).
    Returns {sensor key: flags DataFrame} with the same row order, plus ``rec_id``, ``conf_class``, ``n_neighbours``,
    ``isolation_assessed``, ``type_in_source`` and the ``flag_*`` boolean columns.
    """
    keys = [k for k, v in valid_by_key.items() if v is not None and len(v)]
    out = {k: pd.DataFrame(columns=["rec_id", "conf_class", "n_neighbours", "isolation_assessed", "type_in_source"] + FLAG_COLS)
           for k, v in valid_by_key.items() if k not in keys}
    if not keys:
        return out
    frames = []
    for k in keys:
        d = valid_by_key[k].reset_index(drop=True)
        f = pd.DataFrame({"_key": k, "_row": np.arange(len(d)), "rec_id": d["rec_id"].astype(str).to_numpy(),
                          "sensor": d["sensor"].astype(str).to_numpy(), "platform": d["platform"].astype(str).to_numpy(),
                          "src": d["src"].astype(str).to_numpy(),
                          "stream": (d["product_stream"].astype(str).to_numpy() if "product_stream" in d else np.full(len(d), "UNKNOWN")),
                          "lat": _num(d["lat"]).to_numpy(float), "lon": _num(d["lon"]).to_numpy(float),
                          "date": pd.to_datetime(d["date"]).to_numpy(),
                          "acq_time": d["acq_time"].to_numpy() if "acq_time" in d else np.full(len(d), np.nan),
                          "frp": d["frp"].to_numpy() if "frp" in d else np.full(len(d), np.nan),
                          "conf": d["confidence_raw"].to_numpy(),
                          "daynight": (d["daynight"].astype(str).to_numpy() if "daynight" in d else np.full(len(d), "")),
                          "type": (d["fire_type"].to_numpy() if "fire_type" in d else np.full(len(d), np.nan)),
                          "type_in_source": "fire_type" in d.columns,
                          "scan": d["scan"].to_numpy() if "scan" in d else np.full(len(d), np.nan),
                          "track": d["track"].to_numpy() if "track" in d else np.full(len(d), np.nan)})
        frames.append(f)
    big = pd.concat(frames, ignore_index=True)
    n = len(big)
    day = ((pd.to_datetime(big["date"]) - pd.Timestamp("1970-01-01")).dt.days).to_numpy(np.int64)
    minute = parse_hhmm(big["acq_time"])
    lat, lon = big["lat"].to_numpy(float), big["lon"].to_numpy(float)
    F = {name: np.zeros(n, dtype=bool) for name in FLAG_INFO}

    # --- coordinates / timestamps (records that fail parsing never reach this point; clean.prepare removes them)
    F["null_island"] = (lat == 0) & (lon == 0)
    F["acq_time_invalid"] = np.isnan(minute)
    t = pd.Timestamp(today) if today is not None else pd.Timestamp.now("UTC").tz_localize(None).normalize()
    F["future_date"] = (pd.to_datetime(big["date"]) > t + pd.Timedelta(days=1)).to_numpy()

    # --- confidence classes (original confidence is untouched in the observation table)
    cls, invalid = conf_class(big["conf"], big["sensor"])
    F["conf_invalid"] = invalid
    F["conf_low"] = cls == "low"
    night = big["daynight"].str.strip().str.upper().eq("N").to_numpy()
    box = C.VIIRS_LOW_NIGHT_BOX
    in_lon = (lon >= box["lon_from"]) | (lon <= box["lon_to"])           # eastward from 11 E, through 180, to 110 W
    in_box = in_lon & (lat >= box["lat_south"]) & (lat <= box["lat_north"])
    F["viirs_low_night_outside_documented_area"] = (big["sensor"].to_numpy() == "viirs") & (cls == "low") & night & ~in_box

    # --- day / night context
    dn = big["daynight"].str.strip().str.upper()
    F["daynight_invalid"] = ~dn.isin(["D", "N"]).to_numpy()
    solar = np.mod(minute / 60.0 + lon / 15.0, 24.0)
    ok = (~np.isnan(minute)) & (np.abs(lat) <= C.DAYNIGHT_MAX_ABS_LAT)
    is_d, is_n = (dn == "D").to_numpy(), (dn == "N").to_numpy()
    F["daynight_time_mismatch"] = ok & ((is_d & ((solar >= 21) | (solar < 3))) | (is_n & (solar >= 9) & (solar < 15)))

    # --- FRP (checked against product documentation: FRP is pixel-integrated power in MW; high values are not assumed erroneous)
    frp = pd.to_numeric(big["frp"], errors="coerce").to_numpy(float)
    F["frp_missing"] = np.isnan(frp)
    F["frp_negative"] = frp < 0
    F["frp_zero"] = frp == 0
    frp_thr = {}
    for (s, p), g in big.groupby(["sensor", "platform"]):
        v = frp[g.index.to_numpy()]
        v = v[np.isfinite(v) & (v > 0)]
        if len(v) < C.FRP_EXTREME_MIN_N:
            frp_thr[(s, p)] = None
            continue
        lv = np.log(v)
        med = np.median(lv)
        mad = 1.4826 * np.median(np.abs(lv - med))
        if mad <= 0:
            frp_thr[(s, p)] = None
            continue
        thr = float(np.exp(med + C.FRP_EXTREME_K * mad))
        frp_thr[(s, p)] = thr
        rows = g.index.to_numpy()
        F["frp_extreme_high"][rows] = np.isfinite(frp[rows]) & (frp[rows] > thr)

    # --- type (raw code preserved; interpretation from the FIRMS attribute table)
    ty = pd.to_numeric(big["type"], errors="coerce").to_numpy(float)
    F["type_not_vegetation"] = np.isin(ty, [1, 2, 3])
    F["type_undocumented"] = ~np.isnan(ty) & ~np.isin(ty, [0, 1, 2, 3])

    # --- pixel size proxy
    area = pd.to_numeric(big["scan"], errors="coerce").to_numpy(float) * pd.to_numeric(big["track"], errors="coerce").to_numpy(float)
    for (s, p), g in big.groupby(["sensor", "platform"]):
        rows = g.index.to_numpy()
        a = area[rows]
        if np.isfinite(a).sum() >= C.LARGE_PIXEL_MIN_N:
            F["large_pixel"][rows] = np.isfinite(a) & (a > C.LARGE_PIXEL_FACTOR * np.nanmedian(a))

    # --- duplicates keyed on source identifiers + acquisition attributes
    key = big[["src", "platform"]].copy()
    key["lat"], key["lon"], key["date"], key["t"] = lat, lon, big["date"].to_numpy(), big["acq_time"].astype(str).to_numpy()
    F["dup_key_conflict"] = key.duplicated(keep=False).to_numpy()

    # --- one pair search serves isolation (wide), near-duplicates and cross-source duplicates (narrow)
    pairs = pair_search(lat, lon, day, minute, C.ISOLATION_KM * 1000.0, C.ISOLATION_DAYS)
    nb = np.zeros(n, dtype=np.int64)
    if len(pairs):
        a, b = pairs["a"].to_numpy(np.int64), pairs["b"].to_numpy(np.int64)
        nb += np.bincount(a, minlength=n) + np.bincount(b, minlength=n)
        sensor, plat, src = big["sensor"].to_numpy(), big["platform"].to_numpy(), big["src"].to_numpy()
        same = (sensor[a] == sensor[b]) & (plat[a] == plat[b]) & (pairs["dday"].to_numpy() == 0)
        near_m = np.where(sensor[a] == "modis", C.NEAR_DUP_M["modis"], C.NEAR_DUP_M["viirs"])
        dmin = pairs["dmin"].to_numpy(float)
        near = same & (np.abs(dmin) <= C.NEAR_DUP_MINUTES) & (pairs["dist_m"].to_numpy() <= near_m)
        cross = same & (src[a] != src[b]) & (pairs["dist_m"].to_numpy() <= 1.0) & (dmin == 0)
        rank_stream = big["stream"].map({"SP": 0, "NRT": 1}).fillna(2).to_numpy()
        prec = rank_stream * n + np.arange(n)                    # lower = kept first (SP before NRT, then earlier row)
        later = np.where(prec[a] > prec[b], a, b)
        for flag, m in (("near_duplicate", near), ("dup_cross_source", cross)):
            F[flag][a[m]] = True; F[flag][b[m]] = True
        F["near_duplicate_later"][later[near]] = True
        F["dup_cross_source_later"][later[cross]] = True
    # isolation is only assessable away from the edge of the downloaded area and of the downloaded period
    w, s_, e, n_ = bbox or C.BBOX
    rad_deg = C.ISOLATION_KM / 111.32
    inner = (lat >= s_ + rad_deg) & (lat <= n_ - rad_deg) & (lon >= w + rad_deg) & (lon <= e - rad_deg)
    in_time = (day >= day.min() + C.ISOLATION_DAYS) & (day <= day.max() - C.ISOLATION_DAYS)
    assessed = inner & in_time
    F["isolated"] = assessed & (nb == 0)
    F["frp_extreme_uncorroborated"] = F["frp_extreme_high"] & F["isolated"]

    res = pd.DataFrame({"rec_id": big["rec_id"].to_numpy(), "conf_class": cls, "n_neighbours": nb.astype(int),
                        "isolation_assessed": assessed, "type_in_source": big["type_in_source"].to_numpy(bool)})
    for name in FLAG_INFO:
        res["flag_" + name] = F[name]
    res["_key"], res["_row"] = big["_key"].to_numpy(), big["_row"].to_numpy()
    res.attrs["frp_thresholds"] = {f"{s}/{p}": v for (s, p), v in frp_thr.items()}
    for k in keys:
        g = res[res["_key"] == k].sort_values("_row").drop(columns=["_key", "_row"]).reset_index(drop=True)
        out[k] = g
    out_attrs = {f"{s}/{p}": v for (s, p), v in frp_thr.items()}
    for k in out:
        out[k].attrs["frp_thresholds"] = out_attrs
    return out


# ------------------------------------------------------------------------------------------------ profiles
def profile_steps(df, flags, profile, type_in_source=None):
    """Ordered analytical-filter steps for a profile: [(step name, rule text, keep mask), ...].

    ``df``: observation rows (columns sensor, confidence_raw, fire_type if present). ``flags``: aligned flag table (or None
    when the profile uses no flag). Masks are positional numpy bool arrays. Step names type_filter / confidence_filter are
    the ones earlier FirePulse versions reported.
    """
    steps = []
    n = len(df)
    if profile.get("type_keep") is not None and "fire_type" in df.columns:
        has = type_in_source if type_in_source is not None else np.ones(n, bool)
        keep_codes = set(profile["type_keep"])
        ok = pd.to_numeric(df["fire_type"], errors="coerce").isin(keep_codes).to_numpy()
        steps.append(("type_filter", f"keep FIRMS type in {sorted(keep_codes)} (where the source has a type column)", np.where(np.asarray(has, bool), ok, True)))
    is_mod = (df["sensor"].to_numpy() == "modis")
    mm, vk = profile.get("modis_min_conf"), profile.get("viirs_keep")
    if mm is not None or vk is not None:
        conf = df["confidence_raw"]
        keep = np.ones(n, bool)
        if mm is not None:
            keep &= np.where(is_mod, pd.to_numeric(conf, errors="coerce").ge(mm).to_numpy(), True)
        if vk is not None:
            keep &= np.where(~is_mod, conf.astype(str).str.lower().isin([str(x).lower() for x in vk]).to_numpy(), True)
        rule = []
        if mm is not None: rule.append(f"MODIS confidence >= {mm}")
        if vk is not None: rule.append(f"VIIRS confidence in {sorted(vk)}")
        steps.append(("confidence_filter", "; ".join(rule), keep))
    for name in profile.get("drop_flags", []):
        if flags is None:
            raise ValueError(f"profile needs quality flags ({name}) but none were supplied")
        steps.append(("flag_" + name, f"exclude records flagged '{name}'", ~flags["flag_" + name].to_numpy(bool)))
    return steps


def profile_mask(df, flags, profile):
    """Boolean numpy mask of the records that enter the analysis under ``profile`` (all steps combined)."""
    tis = flags["type_in_source"].to_numpy(bool) if flags is not None and "type_in_source" in flags else None
    keep = np.ones(len(df), bool)
    for _, _, m in profile_steps(df, flags, profile, tis):
        keep &= m
    return keep


# ------------------------------------------------------------------------------------------------ reporting
def summarise(valid_by_key, flags_by_key, profiles=None, active=None):
    """Counts of retained / flagged / excluded records. Nothing is estimated: every number is a row count."""
    profiles = profiles or C.QUALITY_PROFILES
    active = active or C.ACTIVE_PROFILE
    rep = {"flags": {}, "confidence_classes": {}, "day_night": {}, "frp": {}, "platform_summary": [], "profiles": {}, "frp_thresholds": {}}
    for k, d in valid_by_key.items():
        fl = flags_by_key.get(k)
        if d is None or fl is None or not len(d):
            continue
        d = d.reset_index(drop=True)
        n = len(d)
        rep["flags"][k] = {name: {"n": int(fl["flag_" + name].sum()), "share_pct": round(100 * float(fl["flag_" + name].mean()), 3),
                                  "by_platform": {p: int(c) for p, c in fl["flag_" + name].groupby(d["platform"]).sum().items() if c}}
                           for name in FLAG_INFO}
        rep["confidence_classes"][k] = {p: {c: int(v) for c, v in g.value_counts().items()} for p, g in fl["conf_class"].groupby(d["platform"])}
        dn = d["daynight"].astype(str).str.strip().str.upper().where(lambda s: s.isin(["D", "N"]), "other")
        rep["day_night"][k] = {p: {c: int(v) for c, v in g.value_counts().items()} for p, g in dn.groupby(d["platform"])}
        frp = pd.to_numeric(d["frp"], errors="coerce")
        rep["frp"][k] = {}
        for p, g in frp.groupby(d["platform"]):
            v = g[np.isfinite(g) & (g > 0)]
            rep["frp"][k][p] = {"n_records": int(len(g)), "n_positive": int(len(v)),
                                "median": None if v.empty else float(v.median()), "p99": None if v.empty else float(v.quantile(.99)),
                                "p99_9": None if v.empty else float(v.quantile(.999)), "max": None if v.empty else float(v.max()),
                                "extreme_threshold": fl.attrs.get("frp_thresholds", {}).get(f"{k}/{p}"),
                                "n_extreme_high": int(fl.loc[g.index, "flag_frp_extreme_high"].sum())}
        rep["frp_thresholds"].update(fl.attrs.get("frp_thresholds", {}))
        for p, g in d.groupby("platform"):
            ix = g.index
            rep["platform_summary"].append({
                "sensor": k, "platform": p, "records": int(len(ix)),
                "conf_low_pct": round(100 * float(fl.loc[ix, "flag_conf_low"].mean()), 2),
                "night_pct": round(100 * float((dn.loc[ix] == "N").mean()), 2),
                "frp_median": rep["frp"][k][p]["median"],
                "near_duplicate_pct": round(100 * float(fl.loc[ix, "flag_near_duplicate"].mean()), 3),
                "isolated_pct": round(100 * float(fl.loc[ix, "flag_isolated"].mean()), 3),
                "frp_extreme_high_pct": round(100 * float(fl.loc[ix, "flag_frp_extreme_high"].mean()), 3)})
    # profiles: how many records each keeps, and how many each rule hits on its own
    for pid, prof in profiles.items():
        per = {}
        for k, d in valid_by_key.items():
            fl = flags_by_key.get(k)
            if d is None or fl is None or not len(d):
                continue
            d = d.reset_index(drop=True)
            keep = np.ones(len(d), bool)
            rules = []
            for step, rule, m in profile_steps(d, fl, prof, fl["type_in_source"].to_numpy(bool)):
                removed_seq = int((keep & ~m).sum())
                rules.append({"rule": step, "description": rule, "records_failing_rule": int((~m).sum()), "removed_in_sequence": removed_seq})
                keep &= m
            per[k] = {"valid_records": int(len(d)), "retained": int(keep.sum()), "excluded": int((~keep).sum()), "rules": rules,
                      "by_platform_retained": {p: int(c) for p, c in pd.Series(keep).groupby(d["platform"]).sum().items()}}
        rep["profiles"][pid] = {"label": prof["label"], "description": prof["description"], "exploratory": bool(prof.get("exploratory")),
                                "active": pid == active, "sensors": per}
    return rep
