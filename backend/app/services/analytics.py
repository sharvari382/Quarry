"""Deterministic statistics the agent calls as tools.

The LLM decides *what* to analyse and explains the result; the numbers
themselves come from here, so they are reproducible and testable instead of
being "estimated" by the model.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _fmt(x: float) -> str:
    if abs(x) >= 1000:
        return f"{x:,.0f}"
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def _robust_scores(values: pd.Series, threshold: float) -> tuple[pd.Series, pd.Series, str, dict]:
    """Return (score, mask, method, stats) for one group of values."""
    valid = values.dropna()
    median = float(valid.median())
    mad = float((valid - median).abs().median())
    q1, q3 = (float(v) for v in valid.quantile([0.25, 0.75]))
    iqr = q3 - q1
    stats = {"median": median, "mad": mad, "q1": q1, "q3": q3}
    if mad > 0:
        score = 0.6745 * (values - median) / mad
        return score, score.abs() > threshold, "robust_z", stats
    if iqr > 0:
        score = (values - median) / iqr
        return score, (values < q1 - 1.5 * iqr) | (values > q3 + 1.5 * iqr), "iqr", stats
    # More than half the values are identical; anything different is unusual.
    score = (values - median).abs()
    return score, score > 0, "mode_deviation", stats


def detect_anomalies(df: pd.DataFrame, value_column: str, label_columns: list[str] | None = None,
                     threshold: float = 3.5, group_column: str | None = None, max_results: int = 25) -> dict:
    """Flag outliers with the robust (median/MAD) z-score, falling back to IQR fences.

    MAD is used instead of mean/std because the outliers we are hunting would
    otherwise inflate the std and hide themselves (masking). With `group_column`
    each value is judged against its own group (a 2,400 unit price is normal for
    a printer but not for receipt paper)."""
    if value_column not in df.columns:
        raise ValueError(f"Column '{value_column}' is not in the query result. Columns: {list(df.columns)}")
    if group_column and group_column not in df.columns:
        raise ValueError(f"Group column '{group_column}' is not in the query result.")
    values = pd.to_numeric(df[value_column], errors="coerce").astype(float)
    if values.notna().sum() < 8:
        return {"method": "none", "n_values": int(values.notna().sum()), "n_flagged": 0, "flagged": [],
                "summary": "Too few numeric values (need at least 8) to judge outliers."}

    score = pd.Series(np.nan, index=df.index)
    mask = pd.Series(False, index=df.index)
    group_stats: dict = {}
    methods = set()
    groups = df.groupby(group_column, dropna=False).groups.items() if group_column else [(None, df.index)]
    for key, idx in groups:
        g = values.loc[idx]
        if g.notna().sum() < 8:
            continue  # not enough data in this group to call anything unusual
        sc, mk, method, stats = _robust_scores(g, threshold)
        score.loc[idx], mask.loc[idx] = sc, mk.fillna(False)
        group_stats[key] = (method, stats)
        methods.add(method)

    mask = mask.fillna(False).astype(bool)
    # Sign rule: a negative value in a column that is otherwise never negative is suspicious
    # on its own (returns booked as sales, sign errors) even when it is small in magnitude.
    non_null = values.dropna()
    if (non_null >= 0).mean() >= 0.98:
        negatives = values < 0
        mask |= negatives.fillna(False)
        score = score.where(~negatives.fillna(False) | (score.abs() > threshold), -threshold - 0.01)
    labels = [c for c in (label_columns or []) if c in df.columns]
    flagged = []
    for idx in score[mask].abs().sort_values(ascending=False).index[:max_results]:
        key = df.at[idx, group_column] if group_column else None
        method, st = group_stats[key]
        v, med = float(values[idx]), st["median"]
        direction = "above" if v > med else "below"
        scope = f" for {group_column} = {key}" if group_column else ""
        if method == "robust_z" and med > 0 and abs(float(score[idx])) > 50:
            # Past ~50 robust SDs the SD count stops meaning anything to a reader; a ratio does.
            ratio = v / med
            size = f"{ratio:,.0f}x" if ratio >= 2 else f"{ratio:.2f}x"
            why = f"{_fmt(v)} is {size} the median ({_fmt(med)}){scope}"
        elif method == "robust_z":
            why = (f"{_fmt(v)} is {abs(float(score[idx])):.1f} robust standard deviations {direction} "
                   f"the median ({_fmt(med)}){scope}")
        elif method == "iqr":
            iqr = st["q3"] - st["q1"]
            lo, hi = st["q1"] - 1.5 * iqr, st["q3"] + 1.5 * iqr
            why = f"{_fmt(v)} is outside the IQR fences [{_fmt(lo)}, {_fmt(hi)}]{scope}"
        else:
            why = f"{_fmt(v)} differs from the dominant value {_fmt(med)}{scope}"
        if v < 0 <= st["q1"]:
            why += "; negative while the rest of the column is non-negative (possible return or data entry error)"
        flagged.append({
            "row": int(idx), "value": v, "score": round(float(score[idx]), 2), "direction": direction, "reason": why,
            "group": None if key is None else str(key),
            "labels": {c: (None if pd.isna(df.at[idx, c]) else str(df.at[idx, c])) for c in labels},
        })

    overall = _robust_scores(values, threshold)[3]
    n_valid, n_flag = int(values.notna().sum()), int(mask.sum())
    return {
        "method": "+".join(sorted(methods)) or "none",
        "threshold": threshold,
        "group_column": group_column,
        "n_values": n_valid,
        "n_flagged": n_flag,
        **overall,
        "flagged": flagged,
        "summary": f"{n_flag} of {n_valid} values flagged"
                   + (f" (judged within each {group_column})" if group_column else "") + ".",
    }


def profile_frame(df: pd.DataFrame) -> dict:
    cols = []
    for c in df.columns:
        s = df[c]
        entry = {"column": c, "dtype": str(s.dtype), "nulls": int(s.isna().sum()), "distinct": int(s.nunique())}
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            d = s.dropna().astype(float)
            if not d.empty:
                entry.update({k: round(float(v), 4) for k, v in
                              {"min": d.min(), "p25": d.quantile(.25), "median": d.median(), "mean": d.mean(),
                               "p75": d.quantile(.75), "max": d.max(), "sum": d.sum()}.items()})
        elif pd.api.types.is_datetime64_any_dtype(s):
            d = s.dropna()
            if not d.empty:
                entry.update({"min": d.min().isoformat(), "max": d.max().isoformat()})
        else:
            top = s.astype("string").value_counts().head(5)
            entry["top_values"] = {str(k): int(v) for k, v in top.items()}
        cols.append(entry)
    return {"rows": int(len(df)), "columns": cols}


def forecast(df: pd.DataFrame, date_column: str, value_column: str, periods: int = 6, freq: str = "MS") -> dict:
    """Linear trend plus multiplicative monthly seasonality when there is enough
    history (24+ periods); plain linear trend otherwise. Includes an ~80% band
    from residual spread. Intentionally simple and explainable."""
    if date_column not in df.columns or value_column not in df.columns:
        raise ValueError(f"Need columns '{date_column}' and '{value_column}'. Got {list(df.columns)}")
    periods = max(1, min(int(periods), 36))
    d = pd.DataFrame({"ds": pd.to_datetime(df[date_column], errors="coerce"),
                      "y": pd.to_numeric(df[value_column], errors="coerce")}).dropna()
    if d.empty:
        raise ValueError("No usable date/value pairs.")
    series = d.set_index("ds")["y"].resample(freq).sum()
    if len(series) < 4:
        raise ValueError("Need at least 4 periods of history to forecast.")

    t = np.arange(len(series))
    y = series.to_numpy(dtype=float)
    # Replace one-off spikes (robust z > 3.5 against a linear fit) before estimating
    # seasonality, so a single bulk order does not become "every March is huge".
    base = np.polyval(np.polyfit(t, y, 1), t)
    resid = y - base
    mad = np.median(np.abs(resid - np.median(resid)))
    cleaned = 0
    if mad > 0:
        spikes = np.abs(0.6745 * (resid - np.median(resid)) / mad) > 3.5
        cleaned = int(spikes.sum())
        y = np.where(spikes, base, y)
    seasonal = None
    if freq in ("MS", "M", "ME") and len(series) >= 24:
        slope, intercept = np.polyfit(t, y, 1)
        trend = intercept + slope * t
        ratio = pd.Series(np.where(trend != 0, y / trend, 1.0), index=series.index)
        seasonal = ratio.groupby(ratio.index.month).mean()
        method = "linear trend x monthly seasonality"
    else:
        slope, intercept = np.polyfit(t, y, 1)
        method = "linear trend"

    fitted = intercept + slope * t
    if seasonal is not None:
        fitted = fitted * series.index.month.map(seasonal).to_numpy()
    resid_std = float(np.std(y - fitted, ddof=1)) if len(y) > 2 else 0.0

    future_idx = pd.date_range(series.index[-1], periods=periods + 1, freq=freq)[1:]
    ft = np.arange(len(series), len(series) + periods)
    fy = intercept + slope * ft
    if seasonal is not None:
        fy = fy * future_idx.month.map(seasonal).to_numpy()
    band = 1.28 * resid_std
    return {
        "method": method,
        "history": [{"period": i.date().isoformat(), "value": round(float(v), 2)} for i, v in series.items()],
        "forecast": [{"period": i.date().isoformat(), "value": round(float(v), 2),
                      "low": round(float(v - band), 2), "high": round(float(v + band), 2)}
                     for i, v in zip(future_idx, fy, strict=True)],
        "slope_per_period": round(float(slope), 4),
        "residual_std": round(resid_std, 2),
        "outliers_smoothed": cleaned,
    }
