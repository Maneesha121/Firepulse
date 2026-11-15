
"""Overlap-ratio harmonization (VIIRS -> MODIS-equivalent) with leave-one-year-out validation.

Method (engineering recommendation, not a published standard):
  ratio(calendar month) = median over overlap years of VIIRS_count / MODIS_count
  MODIS-equivalent       = VIIRS_count / ratio
Uncertainty band uses the inter-year IQR of the ratio. Falls back to a pooled ratio when a
calendar month has fewer than MIN_YEARS usable years.
"""
import numpy as np
import pandas as pd

from .config import MIN_COUNT, MIN_YEARS, SPLICE


def _stats(s):
    return {
        "med": float(s.median()),
        "q25": float(s.quantile(.25)),
        "q75": float(s.quantile(.75)),
        "n": int(len(s))
    }


# Per-month status of the VIIRS/MODIS ratio.
RATIO_USABLE = "USABLE"
RATIO_ZERO_DEN = "ZERO_DENOMINATOR"       # MODIS count is 0: ratio undefined
RATIO_ZERO_NUM = "ZERO_NUMERATOR"         # VIIRS count is 0: ratio is zero
RATIO_LOW_DEN = "LOW_DENOMINATOR"         # 0 < MODIS count < MIN_COUNT
RATIO_NOT_BOTH = "NOT_BOTH_OBSERVED"      # At least one sensor is unknown


def classify_overlap(region):
    """Classify whether each month can contribute to VIIRS/MODIS ratio estimation.

    A usable month requires:
      - Both MODIS and VIIRS observations
      - MODIS count >= MIN_COUNT
      - VIIRS count > 0

    Zero-VIIRS months are excluded from ratio estimation because they cannot
    provide a positive calibration ratio.
    """
    both = region["modis"].notna() & region["viirs"].notna()

    m = region["modis"]
    v = region["viirs"]

    st = pd.Series(
        RATIO_NOT_BOTH,
        index=region.index,
        dtype=object
    )

    # Classification order matters when both sensors report zero.
    st[both & (m == 0)] = RATIO_ZERO_DEN
    st[both & (m > 0) & (v == 0)] = RATIO_ZERO_NUM
    st[both & (m > 0) & (v > 0) & (m < MIN_COUNT)] = RATIO_LOW_DEN
    st[both & (m >= MIN_COUNT) & (v > 0)] = RATIO_USABLE

    return st


def usable_overlap(region, exclude_year=None):
    """Return overlap months eligible for ratio estimation."""
    ov = region[classify_overlap(region) == RATIO_USABLE]

    if exclude_year is not None:
        ov = ov[ov.index.year != exclude_year]

    return ov


def ratio_tables(region, exclude_year=None):
    """Calculate pooled and calendar-month VIIRS/MODIS ratio statistics."""
    ov = usable_overlap(region, exclude_year)

    if ov.empty:
        raise ValueError("no usable overlap months to estimate the ratio")

    r = ov["viirs"] / ov["modis"]

    by = {
        int(m): _stats(g)
        for m, g in r.groupby(r.index.month)
        if len(g) >= MIN_YEARS
    }

    return {
        "global": _stats(r),
        "by_month": by,
        "n_usable_months": int(len(ov))
    }


def ratio_for(tables, month):
    """Get a calendar-month ratio, falling back to the pooled ratio."""
    r = tables["by_month"].get(month)

    return r if r and r["med"] > 0 else tables["global"]


def harmonize(region, tables, splice=SPLICE):
    """Convert VIIRS counts to the MODIS-equivalent scale where required."""
    sp = pd.Period(splice, "M") if splice else None

    rows = []

    for ts, row in region.iterrows():
        r = ratio_for(tables, ts.month)

        use_v = (
            not np.isnan(row.viirs)
            and (
                np.isnan(row.modis)
                or (sp is not None and ts >= sp)
            )
        )

        if use_v and not (
            np.isfinite(r["med"]) and r["med"] > 0
        ):
            # A zero or non-finite ratio cannot convert VIIRS to
            # the MODIS scale. Keep the result unknown.
            h = lo = hi = np.nan
            src = ""

        elif use_v:
            h = row.viirs / r["med"]

            lo = (
                row.viirs / r["q75"]
                if np.isfinite(r["q75"]) and r["q75"] > 0
                else np.nan
            )

            hi = (
                row.viirs / r["q25"]
                if np.isfinite(r["q25"]) and r["q25"] > 0
                else np.nan
            )

            src = "VIIRS"

        elif not np.isnan(row.modis):
            h = lo = hi = row.modis
            src = "MODIS"

        else:
            h = lo = hi = np.nan
            src = ""

        rows.append((ts, h, lo, hi, src))

    return pd.DataFrame(
        rows,
        columns=["month", "harmonized", "h_lo", "h_hi", "source_used"]
    ).set_index("month")


def loo_validation(region):
    """Predict each overlap year's MODIS counts from VIIRS using ratios
    fitted WITHOUT that year.
    """
    ov = region.dropna()
    ov = ov[ov["modis"] >= MIN_COUNT]
    ov = ov[ov["viirs"] > 0]

    recs, P, A = [], [], []

    for y in sorted(set(ov.index.year)):
        try:
            tables = ratio_tables(region, exclude_year=y)
        except ValueError:
            continue

        g = ov[ov.index.year == y]

        pred = np.array([
            v / ratio_for(tables, m.month)["med"]
            for m, v in zip(g.index, g["viirs"])
        ])

        act = g["modis"].values

        recs.append({
            "year": int(y),
            "n_months": len(g),
            "mae": float(np.mean(np.abs(pred - act))),
            "bias_pct": float((pred.sum() / act.sum() - 1) * 100),
            "smape_pct": float(
                np.mean(
                    2 * np.abs(pred - act) / (pred + act + 1e-9)
                ) * 100
            )
        })

        P += list(pred)
        A += list(act)

    df = pd.DataFrame(recs)

    if df.empty:
        return df, {"years": 0}

    return df, {
        "years": int(len(df)),
        "pooled_corr": (
            float(np.corrcoef(P, A)[0, 1])
            if len(P) > 2
            else None
        ),
        "median_smape_pct": float(df["smape_pct"].median()),
        "median_abs_bias_pct": float(df["bias_pct"].abs().median())
    }
