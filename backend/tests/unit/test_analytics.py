import numpy as np
import pandas as pd
import pytest

from app.services.analytics import detect_anomalies, forecast, profile_frame


def test_flags_planted_outlier_with_reason():
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"id": range(200), "amount": rng.normal(100, 10, 200)})
    df.loc[57, "amount"] = 1000
    res = detect_anomalies(df, "amount", ["id"])
    assert res["method"] == "robust_z"
    top = res["flagged"][0]
    assert top["row"] == 57 and top["labels"]["id"] == "57" and "the median" in top["reason"]


def test_mean_std_would_mask_but_mad_does_not():
    # Two huge outliers inflate the std so much a classic z-score (>3) misses them.
    df = pd.DataFrame({"v": [10, 11, 9, 10, 12, 10, 11, 9, 10, 500, 520]})
    z = (df.v - df.v.mean()) / df.v.std()
    assert (z.abs() > 3).sum() == 0
    assert detect_anomalies(df, "v")["n_flagged"] == 2


def test_grouped_detection_judges_within_group():
    df = pd.DataFrame({"product": ["paper"] * 20 + ["printer"] * 20,
                       "price": [24.0] * 19 + [2400.0] + [2390.0 + i for i in range(20)]})
    df.loc[0:18, "price"] = [24 + (i % 3) for i in range(19)]
    ungrouped = detect_anomalies(df, "price")
    grouped = detect_anomalies(df, "price", group_column="product")
    assert grouped["n_flagged"] == 1 and grouped["flagged"][0]["group"] == "paper"
    assert ungrouped["n_flagged"] != 1


def test_negative_in_non_negative_column_is_flagged():
    df = pd.DataFrame({"qty": [2, 3, 1, 2, 4, 2, 3, 1, 2, 2] * 10 + [-3]})
    res = detect_anomalies(df, "qty")
    assert any(f["value"] == -3 and "negative" in f["reason"] for f in res["flagged"])


def test_too_few_values():
    assert detect_anomalies(pd.DataFrame({"v": [1, 2, 3]}), "v")["method"] == "none"


def test_unknown_column_is_a_clear_error():
    with pytest.raises(ValueError, match="not in the query result"):
        detect_anomalies(pd.DataFrame({"v": range(10)}), "nope")


def test_forecast_linear_trend():
    dates = pd.date_range("2024-01-01", periods=12, freq="MS")
    df = pd.DataFrame({"d": dates, "v": [100 + 10 * i for i in range(12)]})
    res = forecast(df, "d", "v", periods=3)
    assert res["method"] == "linear trend"
    assert [round(p["value"]) for p in res["forecast"]] == [220, 230, 240]


def test_forecast_ignores_single_spike_for_seasonality():
    dates = pd.date_range("2023-01-01", periods=36, freq="MS")
    vals = [1000.0] * 36
    vals[26] = 10_000  # one-off March spike
    res = forecast(pd.DataFrame({"d": dates, "v": vals}), "d", "v", periods=3)
    march = next(p for p in res["forecast"] if p["period"].endswith("-03-01"))
    assert march["value"] < 1500 and res["outliers_smoothed"] == 1


def test_forecast_needs_history():
    df = pd.DataFrame({"d": pd.to_datetime(["2024-01-01", "2024-02-01"]), "v": [1, 2]})
    with pytest.raises(ValueError, match="at least 4"):
        forecast(df, "d", "v")


def test_profile():
    df = pd.DataFrame({"n": [1, 2, 3], "t": ["a", "a", "b"]})
    p = profile_frame(df)
    assert p["rows"] == 3 and p["columns"][0]["sum"] == 6 and p["columns"][1]["top_values"] == {"a": 2, "b": 1}
