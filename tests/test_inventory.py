import numpy as np
import pandas as pd
import pytest

from inventory.model import Config, Item, forecast, run_pair


def series(value=5, n=70):
    return pd.Series(float(value), index=pd.date_range("2024-01-01", periods=n))


def test_future_demand_cannot_change_first_order():
    s = series()
    start = s.index[28]
    changed = s.copy()
    changed.loc[start:] = 10000
    args = (0, Item(10, 3, 10, 0.95), start, Config(days=7), "adaptive")
    a, b = run_pair(s, *args), run_pair(changed, *args)
    assert a.iloc[0].order == b.iloc[0].order
    assert a.iloc[0].reorder_point == b.iloc[0].reorder_point


def test_conservation_receipts_and_no_premature_arrival():
    s = series()
    frame = run_pair(
        s, 0, Item(10, 3, 10, 0.95), s.index[28], Config(days=14), "adaptive"
    )
    assert frame.iloc[0].order > 0
    assert frame.iloc[:3].received.sum() == 0
    assert frame.iloc[3].received == frame.iloc[0].order
    assert (frame.closing >= 0).all()
    previous = np.r_[0, frame.closing.to_numpy()[:-1]]
    assert np.allclose(
        previous + frame.received - frame.expired - frame.sold, frame.closing
    )


def test_expiry_removes_inventory_before_fulfilment():
    s = series(0)
    frame = run_pair(
        s, 10, Item(10, 2, 2, 0.95), s.index[28], Config(days=5), "adaptive"
    )
    assert frame.iloc[2].expired == 10
    assert frame.iloc[2].closing == 0


def test_forecast_shrinks_sparse_weekday_estimates():
    history = series(0, 14)
    history.loc[history.index.dayofweek == 0] = 20
    prediction = forecast(history, pd.date_range("2024-01-15", periods=7), True)
    assert 0 < prediction[0] < 20
    assert prediction[0] > prediction[1]


def test_missing_date_and_invalid_input_fail():
    s = series().drop(pd.Timestamp("2024-01-30"))
    with pytest.raises(ValueError, match="Missing evaluation"):
        run_pair(
            s,
            0,
            Item(10, 3, 10, 0.95),
            pd.Timestamp("2024-01-29"),
            Config(days=7),
            "static",
        )
    with pytest.raises(ValueError):
        Item(10, 0, 5, 0.95)
    with pytest.raises(ValueError):
        Config(order_cost=float("nan"))


def test_identical_case_is_deterministic():
    s = series()
    args = (s, 10, Item(10, 3, 20, 0.95), s.index[28], Config(days=10), "adaptive")
    pd.testing.assert_frame_equal(run_pair(*args), run_pair(*args))
