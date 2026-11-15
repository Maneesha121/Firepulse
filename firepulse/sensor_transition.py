"""Stage 5: Sensor-transition intelligence.

Explains how OBSERVED hotspot detections change across the MODIS-to-VIIRS transition for the selected area,
date range and platform combination. It is built from the same monthly series (area.full_series), the same
ratio rules (harmonize.classify_overlap / ratio_tables) and the same calibration choice (area._choose_tables)
as the rest of the application; it is not a second pipeline.

Everything here describes detections, never physical fire occurrence. Ratios are observed detection ratios for one
area and period, not universal sensor correction factors. Unknown months/platforms are None (null), never 0.

Thresholds below are ENGINEERING CHOICES, not published standards; they are reported in the output ("thresholds").
"""
import math, re
import numpy as np, pandas as pd
from . import coverage, harmonize
from .config import MIN_COUNT, MIN_YEARS, DOCUMENTED_AVAILABILITY, DOCUMENTED_RETRIEVED, ATTRIBUTION
from .schema import FAMILY_OF, ORIGIN_SYNTHETIC
from .availability import split_source

SCHEMA = 1
MODIS_PLATFORMS = ("TERRA", "AQUA")
VIIRS_PLATFORMS = ("SNPP", "NOAA20", "NOAA21")
PLATFORMS = MODIS_PLATFORMS + VIIRS_PLATFORMS
LABEL = {"TERRA": "MODIS Terra", "AQUA": "MODIS Aqua", "SNPP": "VIIRS S-NPP", "NOAA20": "VIIRS NOAA-20",
         "NOAA21": "VIIRS NOAA-21", "UNKNOWN": "Unidentified platform"}

EXPLORATORY_BELOW = 10      # usable observations (years) per calendar month: MIN_YEARS..9 = exploratory, >=10 = adequate
MIN_ANNUAL_MONTHS = 6       # usable months needed before an annual ratio summary is shown
MIN_TREND_YEARS = 5         # years needed before a (descriptive) rank trend is reported
MIN_VALID_MONTHS_YEAR = 6   # valid comparison months needed before leave-one-year-out metrics are reported for a year
MIN_WINDOW_MONTHS = 12      # usable months needed for a sensitivity-table row (time window / platform combination)
SENSITIVITY_REL_SPREAD = 0.25
MIN_AREA_RATIO_MONTHS = 36  # mirrors area.MIN_AREA_RATIO_MONTHS (kept here to avoid a circular import)

THRESHOLDS = {"min_modis_count_for_ratio": MIN_COUNT, "min_years_per_calendar_month": MIN_YEARS,
              "exploratory_below_years": EXPLORATORY_BELOW, "min_months_for_annual_ratio": MIN_ANNUAL_MONTHS,
              "min_years_for_trend": MIN_TREND_YEARS, "min_valid_months_per_validation_year": MIN_VALID_MONTHS_YEAR,
              "min_months_for_sensitivity_row": MIN_WINDOW_MONTHS, "sensitivity_relative_spread_flag": SENSITIVITY_REL_SPREAD,
              "min_overlap_months_for_area_calibration": MIN_AREA_RATIO_MONTHS,
              "note": "Engineering choices, not published standards."}


class PlatformSelectionError(ValueError):
    pass


# ----------------------------------------------------------------------------------------------- selection
_ALIAS = {"terra": "TERRA", "aqua": "AQUA", "snpp": "SNPP", "npp": "SNPP", "suominpp": "SNPP", "noaa20": "NOAA20",
          "n20": "NOAA20", "noaa21": "NOAA21", "n21": "NOAA21"}


def _canon(name):
    return _ALIAS.get(re.sub(r"[^a-z0-9]", "", str(name).lower()))


def parse_selection(spec):
    """None/{} or all platforms -> FAMILY mode (existing family totals). Otherwise SUBSET mode (strict, see selected_frame)."""
    if spec in (None, {}):
        return {"mode": "FAMILY", "modis": list(MODIS_PLATFORMS), "viirs": list(VIIRS_PLATFORMS)}
    if not isinstance(spec, dict):
        raise PlatformSelectionError("'platforms' must be an object like {\"modis\": [\"TERRA\"], \"viirs\": [\"SNPP\"]}.")
    out = {}
    for fam, allowed in (("modis", MODIS_PLATFORMS), ("viirs", VIIRS_PLATFORMS)):
        v = spec.get(fam)
        if v is None:
            out[fam] = list(allowed); continue
        if not isinstance(v, (list, tuple)) or not v:
            raise PlatformSelectionError(f"Select at least one {fam.upper()} platform.")
        got = []
        for name in v:
            c = _canon(name)
            if c is None:
                raise PlatformSelectionError(f"Unknown platform '{name}'. Use TERRA, AQUA, SNPP, NOAA20 or NOAA21.")
            if c not in allowed:
                raise PlatformSelectionError(f"{LABEL[c]} is not a {fam.upper()} platform.")
            got.append(c)
        out[fam] = [p for p in allowed if p in got]
    full = out["modis"] == list(MODIS_PLATFORMS) and out["viirs"] == list(VIIRS_PLATFORMS)
    return {"mode": "FAMILY" if full else "SUBSET", **out}


def describe(ps):
    if ps["mode"] == "FAMILY":
        return "All available platforms (MODIS family vs VIIRS family)"
    return " + ".join(LABEL[p] for p in ps["modis"]) + " vs " + " + ".join(LABEL[p] for p in ps["viirs"])


# ----------------------------------------------------------------------------------------------- availability
def platform_availability(ds):
    """Boolean DataFrame (months x platform): the platform's sensor family was observed AND the month lies between the
    platform's first and last detection in the processed record. Unavailable is never treated as zero."""
    out = pd.DataFrame(index=ds.months)
    for p, fam in FAMILY_OF.items():
        ok = ds.status[fam].isin(coverage.OBSERVED).to_numpy().copy()
        span = ds.platform_span.get(p)
        if span is None:
            ok[:] = False
        else:
            ok &= (ds.months >= span[0]) & (ds.months <= span[1])
        out[p] = ok
    return out


def selected_frame(base, pf, ps):
    """modis/viirs frame for the selected platforms. FAMILY mode = the existing family totals. SUBSET mode is STRICT:
    a month counts only if EVERY selected platform of that family is available, so platform turn-on/off never
    leaks into a ratio."""
    if ps["mode"] == "FAMILY":
        return base[["modis", "viirs"]].copy()
    out = pd.DataFrame(index=base.index)
    for fam in ("modis", "viirs"):
        cols = ps[fam]
        out[fam] = pf[cols].sum(axis=1, min_count=len(cols))
    return out


# ----------------------------------------------------------------------------------------------- ratio statistics
def _evidence(n):
    if n < MIN_YEARS:
        return "INSUFFICIENT_EVIDENCE"
    return "EXPLORATORY" if n < EXPLORATORY_BELOW else "ADEQUATE"


def _q(r):
    return {"median": float(r.median()), "q25": float(r.quantile(.25)), "q75": float(r.quantile(.75))}


def calendar_ratio_table(frame, window=None):
    """Observed VIIRS/MODIS ratio per calendar month from usable overlap months (optionally within a window)."""
    r = frame if window is None else frame.loc[window[0]:window[1]]
    st = harmonize.classify_overlap(r)
    ov = r[st == harmonize.RATIO_USABLE]
    ratio = ov["viirs"] / ov["modis"]
    rows = []
    for cm in range(1, 13):
        g = ratio[ratio.index.month == cm]
        s = st[st.index.month == cm]
        n = int(len(g))
        row = {"calendar_month": cm, "n_observations": n, "n_years": int(len(set(g.index.year))),
               "n_overlap_months": int((s != harmonize.RATIO_NOT_BOTH).sum()),
               "n_zero_denominator": int((s == harmonize.RATIO_ZERO_DEN).sum()),
               "n_low_denominator": int((s == harmonize.RATIO_LOW_DEN).sum()),
               "median": None, "q25": None, "q75": None, "evidence": _evidence(n)}
        if n >= MIN_YEARS:
            q = _q(g); row.update(median=q["median"], q25=q["q25"], q75=q["q75"])
        rows.append(row)
    n = int(len(ratio)); ny = int(len(set(ratio.index.year)))
    glob = {"n_observations": n, "n_years": ny, "median": None, "q25": None, "q75": None, "evidence": _evidence(ny)}
    if n and ny >= MIN_YEARS:
        q = _q(ratio); glob.update(median=q["median"], q25=q["q25"], q75=q["q75"])
    return {"months": rows, "global": glob,
            "window": {"start": str(r.index[0]) if len(r) else None, "end": str(r.index[-1]) if len(r) else None}}


# ----------------------------------------------------------------------------------------------- monthly + overlap
def _num(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def _overlap(frame, a, b):
    st = harmonize.classify_overlap(frame)
    both = st != harmonize.RATIO_NOT_BOTH
    use = st == harmonize.RATIO_USABLE
    rng = (frame.index >= a) & (frame.index <= b)

    def blk(mask):
        idx = frame.index[mask]
        return {"first_month": str(idx[0]) if len(idx) else None, "last_month": str(idx[-1]) if len(idx) else None,
                "months_both_observed": int(both[mask].sum()), "usable_months": int(use[mask].sum()),
                "zero_denominator_months": int((st[mask] == harmonize.RATIO_ZERO_DEN).sum()),
                "low_denominator_months": int((st[mask] == harmonize.RATIO_LOW_DEN).sum()),
                "usable_years": sorted({int(y) for y in frame.index[mask & use.to_numpy()].year})}
    return {"definition": "months in which BOTH sensor families have an observed count for the selected platforms",
            "min_modis_count": MIN_COUNT, "whole_record": blk(both.to_numpy()), "in_range": blk(both.to_numpy() & rng)}


def _monthly(frame, pf, df, ds, ps, a, b):
    st = harmonize.classify_overlap(frame)
    with np.errstate(divide="ignore", invalid="ignore"):
        q = frame["viirs"] / frame["modis"]
    dfi = df.set_index("month")
    avail_cols = [p for p in PLATFORMS if pf[p].notna().any()]
    rows = []
    for p in frame.index[(frame.index >= a) & (frame.index <= b)]:
        m, v = _num(frame.at[p, "modis"]), _num(frame.at[p, "viirs"])
        d = dfi.loc[str(p)]
        s = st[p]
        gap = []
        if ps["mode"] == "SUBSET":
            gap = [x for x in ps["modis"] + ps["viirs"] if pd.isna(pf.at[p, x]) and
                   ds.status[FAMILY_OF[x]].at[p] in coverage.OBSERVED]
        rows.append({
            "month": str(p), "year": int(p.year), "calendar_month": int(p.month),
            "modis": m, "viirs": v, "raw_combined": None if m is None and v is None else (m or 0) + (v or 0),
            "harmonized": _num(d["harmonized"]), "h_lo": _num(d["h_lo"]), "h_hi": _num(d["h_hi"]), "source_used": d["source_used"],
            "modis_status": d["modis_status"], "viirs_status": d["viirs_status"], "data_status": d["data_status"],
            "incomplete": "INCOMPLETE_PERIOD" in (d["modis_status"], d["viirs_status"]),
            "both_observed": s != harmonize.RATIO_NOT_BOTH,
            "ratio": _num(q[p]) if s == harmonize.RATIO_USABLE else None, "ratio_status": s,
            "ratio_unstable": _num(q[p]) if s == harmonize.RATIO_LOW_DEN else None,
            "selection_gap": gap, "active_platforms": [x for x in avail_cols if not pd.isna(pf.at[p, x])]})
    return rows


# ----------------------------------------------------------------------------------------------- ratio over time
def _spearman(x, y):
    rx, ry = pd.Series(x).rank(), pd.Series(y).rank()
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def _ratio_over_time(monthly, cal):
    med = {r["calendar_month"]: r["median"] for r in cal["months"]}
    by = {}
    for r in monthly:
        by.setdefault(r["year"], []).append(r)
    annual = []
    for y, rs in sorted(by.items()):
        ov = [r for r in rs if r["both_observed"]]
        us = [r for r in rs if r["ratio"] is not None]
        row = {"year": y, "n_overlap_months": len(ov), "n_usable_months": len(us), "median_ratio": None, "pooled_ratio": None,
               "relative_to_calendar_median": None, "status": "NO_OVERLAP" if not ov else "INSUFFICIENT_USABLE_MONTHS"}
        if len(us) >= MIN_ANNUAL_MONTHS:
            row["median_ratio"] = float(np.median([r["ratio"] for r in us]))
            sm, sv = sum(r["modis"] for r in us), sum(r["viirs"] for r in us)
            row["pooled_ratio"] = sv / sm if sm > 0 else None
            rel = [r["ratio"] / med[r["calendar_month"]] for r in us if med.get(r["calendar_month"])]
            row["relative_to_calendar_median"] = float(np.median(rel)) if rel else None
            row["status"] = "COMPLETE_YEAR" if len(us) == 12 else "PARTIAL_YEAR"
        annual.append(row)
    pts = [(r["year"], r["relative_to_calendar_median"]) for r in annual if r["relative_to_calendar_median"] is not None]
    trend = {"n_years": len(pts), "spearman_rho": None, "evidence": "INSUFFICIENT_EVIDENCE",
             "note": "Rank correlation of year with the annual median ratio relative to its calendar-month median. "
                     "Descriptive only: no significance test, not a causal or physical trend."}
    if len(pts) >= MIN_TREND_YEARS:
        trend["spearman_rho"] = _spearman([p[0] for p in pts], [p[1] for p in pts])
        trend["evidence"] = "EXPLORATORY"
    first = next((r["month"] for r in monthly if r["both_observed"]), None)
    last = next((r["month"] for r in reversed(monthly) if r["both_observed"]), None)
    return {"annual": annual, "trend": trend, "overlap_start": first, "overlap_end": last}


# ----------------------------------------------------------------------------------------------- contribution
def _contribution(base, pf, avail, ds, a, b, ps):
    idx = base.index
    in_rng = (idx >= a) & (idx <= b)
    both = base[["modis", "viirs"]].notna().all(axis=1).to_numpy()
    cols = list(PLATFORMS)
    series = {p: pf[p] for p in cols}
    unk = base["n_UNKNOWN"]
    unk_total = float(unk[in_rng].sum())
    if unk_total > 0:
        cols.append("UNKNOWN"); series["UNKNOWN"] = unk
    selected = set(ps["modis"] + ps["viirs"])

    def block(mask):
        months = idx[mask]
        rows, total = [], 0.0
        for p in cols:
            s = series[p].loc[months]
            n_av = int(s.notna().sum())
            det = float(s.sum()) if n_av else None
            total += det or 0.0
            rows.append({"platform": p, "label": LABEL[p], "family": FAMILY_OF.get(p), "selected": p in selected,
                         "status": "UNAVAILABLE" if n_av == 0 else "AVAILABLE" if n_av == len(months) else "PARTIAL",
                         "months_in_range": int(len(months)), "months_available": n_av,
                         "months_unavailable": int(len(months) - n_av), "detections": det})
        for r in rows:
            r["percent"] = None if r["detections"] is None or total <= 0 else 100.0 * r["detections"] / total
        return {"total_detections": total if any(r["detections"] is not None for r in rows) else None, "platforms": rows,
                "months": int(len(months))}

    spans = {p: ({"first_month": str(ds.platform_span[p][0]), "last_month": str(ds.platform_span[p][1])}
                 if p in ds.platform_span else {"first_month": None, "last_month": None}) for p in PLATFORMS}
    for p in PLATFORMS:
        spans[p]["label"] = LABEL[p]; spans[p]["family"] = FAMILY_OF[p]
        spans[p]["months_available_in_record"] = int(avail[p].sum())
    by_year = []
    for y in sorted({int(i.year) for i in idx[in_rng]}):
        ym = in_rng & (idx.year == y)
        blk = block(ym)
        by_year.append({"year": y, "months": blk["months"], "total_detections": blk["total_detections"],
                        "detections": {r["platform"]: r["detections"] for r in blk["platforms"]},
                        "percent": {r["platform"]: r["percent"] for r in blk["platforms"]}})
    fam = {}
    for k in ("modis", "viirs"):
        s = base[k][in_rng]
        fam[k] = {"detections": _num(s.sum(min_count=1)), "months_observed": int(s.notna().sum()), "months_in_range": int(in_rng.sum())}
    tot = sum(v["detections"] or 0 for v in fam.values())
    for v in fam.values():
        v["percent"] = None if v["detections"] is None or tot <= 0 else 100.0 * v["detections"] / tot
    return {"range": {"start": str(a), "end": str(b)}, "overall": block(in_rng), "overlap_period": block(in_rng & both),
            "by_year": by_year, "family_totals": fam, "platform_record": spans,
            "caution": "Share of observed DETECTIONS. A larger share does not mean that platform saw more physical fires: "
                       "platforms differ in resolution, overpass time and the months they were observing."}


# ----------------------------------------------------------------------------------------------- validation
def loyo_report(frame, fit_frame=None, years=None):
    """Leave-one-year-out validation. For each held-out year the ratio tables are fitted on ``fit_frame`` WITH THAT YEAR
    EXCLUDED (``frame`` itself unless a regional fit frame is given) and then used to predict that year's MODIS counts
    from its VIIRS counts."""
    fit = frame if fit_frame is None else fit_frame
    st = harmonize.classify_overlap(frame)
    cand = sorted({int(y) for y in frame.index[(st != harmonize.RATIO_NOT_BOTH).to_numpy()].year})
    rows, P, A = [], [], []
    for y in cand:
        if years is not None and y not in years:
            continue
        yi = frame.index[frame.index.year == y]
        row = {"year": y, "status": None, "reason": None, "n_valid_months": 0, "n_overlap_months": int((st[yi] != harmonize.RATIO_NOT_BOTH).sum()),
               "n_excluded_low_or_zero_denominator": int(st[yi].isin([harmonize.RATIO_ZERO_DEN, harmonize.RATIO_LOW_DEN]).sum()),
               "months": [], "correlation": None, "correlation_note": None, "smape_pct": None, "mae": None, "bias": None,
               "abs_bias": None, "bias_pct": None, "abs_bias_pct": None, "climatology_smape_pct": None}
        try:
            tables = harmonize.ratio_tables(fit, exclude_year=y)
        except ValueError:
            tables = None
        n_fit_years = len({int(i.year) for i in harmonize.usable_overlap(fit, exclude_year=y).index})
        if n_fit_years < MIN_YEARS:          # too little evidence to fit a ratio WITHOUT this year: do not predict
            tables = None
        preds = {}
        for p in yi:
            actual = _num(frame.at[p, "modis"])
            item = {"month": str(p), "calendar_month": int(p.month), "actual": actual, "viirs": _num(frame.at[p, "viirs"]),
                    "predicted": None, "ratio_used": None, "ratio_source": None, "excluded_reason": None}
            if st[p] != harmonize.RATIO_USABLE:
                item["excluded_reason"] = st[p]
            elif tables is None:
                item["excluded_reason"] = "NO_CALIBRATION"
            else:
                r = harmonize.ratio_for(tables, p.month)
                if not r["med"] > 0:
                    item["excluded_reason"] = "UNDEFINED_RATIO"
                else:
                    item.update(predicted=float(frame.at[p, "viirs"] / r["med"]), ratio_used=float(r["med"]),
                                ratio_source="CALENDAR_MONTH" if tables["by_month"].get(p.month) and tables["by_month"][p.month]["med"] > 0 else "GLOBAL_FALLBACK")
                    preds[p] = item
            row["months"].append(item)
        n = len(preds)
        row["n_valid_months"] = n
        if tables is None:
            row["status"] = "NO_CALIBRATION"; row["reason"] = f"Fewer than {MIN_YEARS} other usable overlap years to fit the ratio without this year."
        elif n < MIN_VALID_MONTHS_YEAR:
            row["status"] = "INSUFFICIENT_VALID_MONTHS"
            row["reason"] = f"{n} valid comparison months; at least {MIN_VALID_MONTHS_YEAR} are needed before metrics are shown."
        else:
            pr = np.array([i["predicted"] for i in preds.values()]); ac = np.array([i["actual"] for i in preds.values()])
            row["status"] = "COMPLETE_YEAR" if n == 12 else "PARTIAL_YEAR"
            row["smape_pct"] = float(np.mean(200 * np.abs(pr - ac) / (np.abs(pr) + np.abs(ac))))
            row["mae"] = float(np.mean(np.abs(pr - ac)))
            row["bias"] = float(pr.sum() - ac.sum()); row["abs_bias"] = abs(row["bias"])
            row["bias_pct"] = float(100 * (pr.sum() / ac.sum() - 1)); row["abs_bias_pct"] = abs(row["bias_pct"])
            if pr.std() > 0 and ac.std() > 0:
                row["correlation"] = float(np.corrcoef(pr, ac)[0, 1])
                row["correlation_note"] = "Within one year this mostly reflects the shared seasonal cycle."
            else:
                row["correlation_note"] = "Not defined: predicted or actual counts do not vary within the year."
            # climatology baseline: median MODIS of the same calendar month in other observed years (needs >= MIN_YEARS years)
            errs = []
            for p, i in preds.items():
                h = frame["modis"][(frame.index.month == p.month) & (frame.index.year != y)].dropna()
                if len(h) >= MIN_YEARS:
                    c = float(h.median()); d = abs(c) + abs(i["actual"])
                    errs.append(200 * abs(c - i["actual"]) / d if d > 0 else 0.0)
            row["climatology_smape_pct"] = float(np.mean(errs)) if len(errs) == n else None
            P += list(pr); A += list(ac)
        rows.append(row)
    ok = [r for r in rows if r["smape_pct"] is not None]
    summ = {"years_listed": len(rows), "years_with_metrics": len(ok), "min_valid_months_per_year": MIN_VALID_MONTHS_YEAR,
            "evidence": _evidence(len(ok)), "median_smape_pct": float(np.median([r["smape_pct"] for r in ok])) if ok else None,
            "median_abs_bias_pct": float(np.median([r["abs_bias_pct"] for r in ok])) if ok else None,
            "pooled_correlation": float(np.corrcoef(P, A)[0, 1]) if len(P) > 2 and np.std(P) > 0 and np.std(A) > 0 else None,
            "pooled_correlation_note": "Pooled over months of all evaluated years; largely driven by the seasonal cycle.",
            "median_climatology_smape_pct": None}
    cl = [r["climatology_smape_pct"] for r in ok if r["climatology_smape_pct"] is not None]
    if cl:
        summ["median_climatology_smape_pct"] = float(np.median(cl))
    return rows, summ


# ----------------------------------------------------------------------------------------------- sensitivity
def _window_row(label, frame, a=None, b=None):
    r = frame if a is None else frame.loc[a:b]
    st = harmonize.classify_overlap(r)
    ov = r[st == harmonize.RATIO_USABLE]
    n = len(ov)
    row = {"label": label, "start": str(r.index[0]) if len(r) else None, "end": str(r.index[-1]) if len(r) else None,
           "n_usable_months": int(n), "n_years": int(len(set(ov.index.year))), "median": None, "q25": None, "q75": None,
           "evidence": "INSUFFICIENT_EVIDENCE"}
    if n >= MIN_WINDOW_MONTHS:
        q = _q(ov["viirs"] / ov["modis"]); row.update(median=q["median"], q25=q["q25"], q75=q["q75"], evidence=_evidence(row["n_years"]))
    return row


def _spread(rows, ref):
    v = [r["median"] for r in rows if r["median"] is not None]
    if len(v) < 2 or not ref or ref <= 0:
        return {"relative_spread": None, "label": "INSUFFICIENT_EVIDENCE"}
    s = (max(v) - min(v)) / ref
    return {"relative_spread": float(s), "label": "LARGE_SPREAD" if s > SENSITIVITY_REL_SPREAD else "SMALL_SPREAD"}


def _sensitivity(frame, base, pf, avail, a, b, ps):
    full = _window_row("Whole record", frame)
    rows = [full, _window_row("Selected date range", frame, a, b)]
    st = harmonize.classify_overlap(frame)
    yrs = sorted({int(y) for y in frame.index[(st == harmonize.RATIO_USABLE).to_numpy()].year})
    if len(yrs) >= 2:
        h = (len(yrs) + 1) // 2
        for lab, ys in (("Earlier half of overlap years", yrs[:h]), ("Later half of overlap years", yrs[h:])):
            rows.append(_window_row(lab, frame, pd.Period(f"{ys[0]}-01", "M"), pd.Period(f"{ys[-1]}-12", "M")))
    jack = {"n_years": len(yrs), "min_median": None, "max_median": None, "year_min": None, "year_max": None, "relative_spread": None}
    if len(yrs) >= 3 and full["median"]:
        vals = {}
        ov = frame[st == harmonize.RATIO_USABLE]
        for y in yrs:
            o = ov[ov.index.year != y]
            if len(o) >= MIN_WINDOW_MONTHS:
                vals[y] = float((o["viirs"] / o["modis"]).median())
        if vals:
            lo, hi = min(vals, key=vals.get), max(vals, key=vals.get)
            jack.update(min_median=vals[lo], max_median=vals[hi], year_min=lo, year_max=hi,
                        relative_spread=(vals[hi] - vals[lo]) / full["median"])
    time = {"windows": rows, "leave_one_year_out_global_median": jack, **_spread(rows, full["median"])}

    combos, meds = [], []
    sel_key = (tuple(ps["modis"]), tuple(ps["viirs"]))
    for m in ([ "TERRA"], ["AQUA"], ["TERRA", "AQUA"]):
        for v in (["SNPP"], ["NOAA20"], ["NOAA21"]):
            row = {"modis": m, "viirs": v, "label": " + ".join(LABEL[x] for x in m) + " vs " + " + ".join(LABEL[x] for x in v),
                   "is_selected": (tuple(m), tuple(v)) == sel_key}
            missing = [LABEL[x] for x in m + v if not avail[x].any()]
            if missing:
                row.update(status="UNAVAILABLE", reason=f"No data in the processed record for {', '.join(missing)}.", n_usable_months=0,
                           median=None, q25=None, q75=None, evidence="INSUFFICIENT_EVIDENCE")
            else:
                w = _window_row(row["label"], selected_frame(base, pf, {"mode": "SUBSET", "modis": m, "viirs": v}), a, b)
                row.update(status="OK" if w["median"] is not None else "INSUFFICIENT_EVIDENCE",
                           reason=None if w["median"] is not None else f"Fewer than {MIN_WINDOW_MONTHS} usable overlap months in the selected range.",
                           n_usable_months=w["n_usable_months"], median=w["median"], q25=w["q25"], q75=w["q75"], evidence=w["evidence"])
                if w["median"] is not None:
                    meds.append(w["median"])
            combos.append(row)
    ref = float(np.median(meds)) if meds else None
    plat = {"combinations": combos, "range": {"start": str(a), "end": str(b)}, **_spread([{"median": x} for x in meds], ref)}
    return {"time_period": time, "platform_combination": plat,
            "note": "Descriptive spread of observed ratios across periods and platform pairs; it is not a confidence interval."}



# ----------------------------------------------------------------------------------------------- timeline + product streams
def _timeline(ds):
    """Per platform: NASA-DOCUMENTED availability next to what the processed record actually contains. They are different
    evidence: documented = stated by NASA pages; detected = first/last month with a detection in this record."""
    rows = []
    pa = ds.meta.get("product_availability") or {}
    for p in PLATFORMS:
        d = DOCUMENTED_AVAILABILITY.get(p, {})
        span = ds.platform_span.get(p)
        first, last = (str(span[0]), str(span[1])) if span else (None, None)
        flags = []
        ds_, de_ = d.get("documented_start"), d.get("documented_end")
        if first and ds_ and first < ds_[:7]:
            flags.append("Detections precede the documented FIRMS start: check platform mapping and source files.")
        if last and de_ and last > de_[:7]:
            flags.append("Detections follow the documented end of delivery: check source files.")
        # FIRMS data_availability reply (if it was fetched): authoritative per-source first/last dates; config values stay as fallback.
        api = [{"source": k, "stream": v.get("stream"), "first": v.get("first"), "last": v.get("last")}
               for k, v in (pa.get("sources") or {}).items() if v.get("platform") == p]
        cov = [c for c in (ds.meta.get("source_coverage") or []) if split_source(c["source"])[0] == p]
        if api:
            api_first = min(x["first"] for x in api)
            if ds_ and api_first != ds_:
                flags.append(f"FIRMS availability reports {api_first} as first date but the stored documented start is {ds_}; check both.")
            if first and first < api_first[:7]:
                flags.append("Detections precede the FIRMS-reported availability start: check platform mapping and source files.")
        rows.append({"platform": p, "label": LABEL[p], "family": FAMILY_OF[p], "launch": d.get("launch"),
                     "documented_start": (min(x["first"] for x in api) if api else ds_), "documented_end": de_,
                     "documented_start_basis": (f"FIRMS data_availability API, retrieved {pa.get('retrieved')}" if api else
                                                f"config (NASA pages, retrieved {DOCUMENTED_RETRIEVED})" if ds_ else "not verified"),
                     "config_documented_start": ds_, "firms_availability": api, "download_coverage": cov,
                     "documented_note": d.get("note"), "documented_source": d.get("source"),
                     "detected_first_month": first, "detected_last_month": last, "in_record": span is not None, "flags": flags})
    return {"retrieved": DOCUMENTED_RETRIEVED, "availability_retrieved": pa.get("retrieved"), "rows": rows,
            "caution": "Documented dates come from NASA pages (retrieved on the date shown); 'detected' months are inferred from this record. "
                       "Neither proves clear-sky or valid observation of a given area."}


def _product_streams(ds):
    """Region-wide counts per platform and FIRMS product stream (NRT or SP). Mixed streams need care: NRT products use predictive orbit
    information and can differ from standard processing; recent NRT-only months are provisional."""
    pts = ds.points
    if "product_stream" not in pts.columns:
        return {"available": False, "rows": [], "notes": ["Cleaned data has no product_stream column (re-run the pipeline to record it)."]}
    g = pts.groupby(["platform", "product_stream"])["month"].agg(["size", "min", "max"]).reset_index()
    rows = [{"platform": r["platform"], "stream": r["product_stream"], "detections": int(r["size"]), "first_month": r["min"], "last_month": r["max"]}
            for _, r in g.iterrows()]
    notes = []
    for plat, sub in g.groupby("platform"):
        st = set(sub["product_stream"])
        if "NRT" in st and "SP" in st:
            first_nrt = sub.loc[sub["product_stream"] == "NRT", "min"].min()
            notes.append(f"{LABEL.get(plat, plat)} mixes standard-processing (SP) and near-real-time (NRT) detections; NRT appears from {first_nrt}. "
                         "Treat NRT-only months as provisional and check for a level shift at the join.")
        elif st == {"NRT"}:
            notes.append(f"{LABEL.get(plat, plat)} is NRT-only in this record: no standard-processing (science-quality) data.")
    if (pts["product_stream"] == "UNKNOWN").any():
        notes.append("Some detections have an unknown product stream (source folder name not ending in _SP or _NRT).")
    return {"available": True, "rows": rows, "notes": notes}

# ----------------------------------------------------------------------------------------------- calibration + assembly
def _calibration(ds, base, tables, basis, ps):
    ov = harmonize.usable_overlap(base[["modis", "viirs"]])
    n = int(len(ov))
    source = "AREA" if basis.startswith("AREA") else "REGION"
    expl = (f"The harmonised index for this selection uses a ratio estimated from the selection's own {n} usable overlap months "
            f"(minimum {MIN_AREA_RATIO_MONTHS})." if source == "AREA" else
            f"Only {n} usable overlap months exist inside the selection (minimum {MIN_AREA_RATIO_MONTHS}), so the REGIONAL ratio "
            "(whole processing region) is applied. Treat the index for this area as low reliability.")
    return {"source": source, "basis": basis, "explanation": expl, "usable_overlap_months_in_selection": n,
            "minimum_for_area_calibration": MIN_AREA_RATIO_MONTHS, "applies_to": "harmonised index and its uncertainty band (all available platforms)",
            "ratio_global_used": tables["global"],
            "ratio_by_calendar_month_used": [dict(calendar_month=m, **tables["by_month"][m]) if m in tables["by_month"] else
                                             {"calendar_month": m, "med": None, "q25": None, "q75": None, "n": 0} for m in range(1, 13)],
            "platform_selection_note": None if ps["mode"] == "FAMILY" else
            "A platform subset is selected: the comparison, ratio, validation and sensitivity panels use that subset; the harmonised "
            "index still uses all available platforms."}


def _provenance(ds):
    syn = ds.origin == ORIGIN_SYNTHETIC
    return {"data_origin": ds.origin, "is_synthetic": syn,
            "interpretation_scope": "ILLUSTRATIVE_ONLY" if syn else "OBSERVED_DETECTION_DIFFERENCES_ONLY",
            "statement": ("SYNTHETIC DEMONSTRATION DATA: these numbers only show that the calculations run. They say nothing about "
                          "real MODIS or VIIRS performance." if syn else
                          "Computed from NASA FIRMS detections as processed by this repository. They describe differences in OBSERVED "
                          "detections, not differences in actual fire occurrence, and are not universal sensor correction factors.")}


def build(ds, base, tables, basis, df, a, b, ps, missing_periods):
    avail = platform_availability(ds)
    pf = pd.DataFrame({p: base["n_" + p].where(avail[p]) for p in PLATFORMS}, index=base.index)
    frame = selected_frame(base, pf, ps)
    monthly = _monthly(frame, pf, df, ds, ps, a, b)
    overlap = _overlap(frame, a, b)
    cal_range = calendar_ratio_table(frame, (a, b))
    cal_full = calendar_ratio_table(frame)
    cal = _calibration(ds, base, tables, basis, ps)

    fit_frame, method = None, "AREA_LOYO"
    if ps["mode"] == "FAMILY" and cal["source"] == "REGION":
        fit_frame, method = ds.region_series()[["modis", "viirs"]], "REGION_TRANSFER_LOYO"
    years = {y for y in range(a.year, b.year + 1)}
    rows, vsum = loyo_report(frame, fit_frame, years)
    vsum["method"] = method
    vsum["method_note"] = ("Ratios fitted on this selection's other years." if method == "AREA_LOYO" else
                           "This selection uses the regional ratio, so each held-out year is predicted with the regional ratio fitted "
                           "WITHOUT that year and applied to this selection's VIIRS counts.")
    vsum["held_out_years_outside_range"] = int(len([y for y in {int(i.year) for i in frame.index[harmonize.classify_overlap(frame) == harmonize.RATIO_USABLE]} if y not in years]))

    notes = []
    prov = _provenance(ds)
    if prov["is_synthetic"]:
        notes.append(prov["statement"])
    notes.append(cal["explanation"])
    if cal["platform_selection_note"]:
        notes.append(cal["platform_selection_note"])
    if overlap["in_range"]["usable_months"] == 0:
        notes.append("No usable overlap month in the selected range: ratio panels show no values. This is missing evidence, not a ratio of zero.")
    if overlap["whole_record"]["low_denominator_months"] or overlap["whole_record"]["zero_denominator_months"]:
        notes.append(f"{overlap['whole_record']['zero_denominator_months']} overlap months have zero MODIS detections and "
                     f"{overlap['whole_record']['low_denominator_months']} have fewer than {MIN_COUNT}: no ratio is used from them (unstable ones are plotted hollow).")
    inc = sum(1 for r in monthly if r["incomplete"])
    if inc:
        notes.append(f"{inc} months in the range are INCOMPLETE_PERIOD (partial coverage evidence) and carry no count.")
    for p in PLATFORMS:
        if not avail[p].any():
            notes.append(f"{LABEL[p]} has no data in this record: shown as unavailable, not as zero.")
    unk = float(base["n_UNKNOWN"].sum())
    if unk > 0:
        notes.append(f"{int(unk)} detections have an unidentified platform; they count in family totals but in no platform series.")
    marks, ended = [], []
    for p in PLATFORMS:
        if avail[p].any():
            obs = ds.status[FAMILY_OF[p]].isin(coverage.OBSERVED).to_numpy()
            fam_first = obs.argmax()
            fam_last = len(obs) - 1 - obs[::-1].argmax()
            av = avail[p].to_numpy()
            first = int(av.argmax()); last = len(av) - 1 - av[::-1].argmax()
            if first > fam_first and ps["mode"] == "FAMILY":
                marks.append({"platform": p, "label": LABEL[p], "first_available_month": str(ds.months[first])})
            if last < fam_last and ps["mode"] == "FAMILY":
                ended.append({"platform": p, "label": LABEL[p], "last_detected_month": str(ds.months[last])})
    if marks:
        notes.append("Platform composition changes inside the record (" + ", ".join(f"{m['label']} from {m['first_available_month']}" for m in marks) +
                     "): a shift in the ratio at those months may reflect the platform mix, not sensor behaviour.")
    if ended:
        notes.append("Platforms with no detections after a given month while their sensor family continues (" +
                     ", ".join(f"{m['label']} after {m['last_detected_month']}" for m in ended) +
                     "): the family total after that month comes from the remaining platforms. NASA documents that Suomi NPP delivery ceased on 2 November 2026.")
    timeline = _timeline(ds)
    for r in timeline["rows"]:
        for f in r["flags"]:
            notes.append(f"{r['label']}: {f}")
    streams = _product_streams(ds)
    notes.extend(streams["notes"])

    out = {"schema": SCHEMA, "provenance": prov, "selection": {**ps, "description": describe(ps)},
           "range": {"start": str(a), "end": str(b)}, "data_period": {"first_month": str(ds.months[0]), "last_month": str(ds.months[-1])},
           "thresholds": THRESHOLDS, "calibration": cal, "overlap": overlap,
           "monthly": monthly, "missing_periods": missing_periods, "composition_changes": marks, "platform_endings": ended,
           "platform_timeline": timeline, "product_streams": streams, "attribution": ATTRIBUTION,
           "calendar_ratio": {"selected_range": cal_range, "whole_record": cal_full,
                              "caution": "Observed VIIRS/MODIS detection ratios for this area and period; not universal sensor correction factors."},
           "ratio_over_time": _ratio_over_time(monthly, cal_range),
           "contribution": _contribution(base, pf, avail, ds, a, b, ps),
           "validation": {"summary": vsum, "years": rows},
           "sensitivity": _sensitivity(frame, base, pf, avail, a, b, ps), "notes": notes}
    return _clean(out)


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if math.isnan(o) or math.isinf(o) else float(o)
    if isinstance(o, pd.Period):
        return str(o)
    return o
