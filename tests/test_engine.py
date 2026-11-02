import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metrics import xirr  # noqa: E402
from schedule import Config, all_configs, schedule  # noqa: E402
from simulate import build_buys, leaderboard, rolling, rolling_summary, run_window, value_curve  # noqa: E402


def make_prices(start="2024-01-01", end="2024-04-30", holidays=(), price_fn=None):
    days = pd.bdate_range(start, end)
    days = days[~days.isin(pd.to_datetime(list(holidays)))]
    px = np.array([price_fn(d) if price_fn else 100.0 for d in days])
    return pd.DataFrame(
        {"open": px, "close": px, "adj_open": px, "adj_close": px}, index=days
    )


def test_config_count():
    # 1 daily + 5 weekly + 10 bi-weekly + 20 Nth-weekday + 28 day-of-month
    assert len(all_configs()) == 64
    assert len({c.label for c in all_configs()}) == 64


def test_weekly_rolls_holiday_to_next_trading_day():
    prices = make_prices(holidays=["2024-01-15"])  # a Monday
    sched = schedule(Config("weekly", weekday=0), prices.index)
    row = sched[sched["scheduled"] == "2024-01-15"].iloc[0]
    assert row["executed"] == pd.Timestamp("2024-01-16")


def test_monthly_budget_split_evenly_within_month():
    prices = make_prices()
    buys = build_buys(Config("weekly", weekday=1), prices, monthly_budget=360)
    # January 2024 has 5 Tuesdays, February has 4.
    jan = buys[buys["month"] == pd.Period("2024-01")]
    feb = buys[buys["month"] == pd.Period("2024-02")]
    assert len(jan) == 5 and np.allclose(jan["amount"], 72)
    assert len(feb) == 4 and np.allclose(feb["amount"], 90)
    for m in buys["month"].unique():
        assert buys.loc[buys["month"] == m, "amount"].sum() == pytest.approx(360)


def test_every_config_invests_same_total():
    prices = make_prices()
    lb = leaderboard(prices, all_configs(), 360, pd.Period("2024-02"), pd.Period("2024-03"))
    assert np.allclose(lb["invested"], 720)


def test_flat_prices_give_zero_return():
    prices = make_prices()
    lb = leaderboard(prices, all_configs(), 360, pd.Period("2024-02"), pd.Period("2024-03"))
    assert np.allclose(lb["final_value"], 720)
    assert np.allclose(lb["return_pct"], 0)


def test_hand_computed_monthly_day_one():
    # Price is 100 in Feb and 200 from March 1st onward; buying on the 1st of
    # Feb and Mar: 360/100 + 360/200 = 5.4 shares, worth 5.4 * 200 = 1080.
    prices = make_prices(price_fn=lambda d: 100.0 if d < pd.Timestamp("2024-03-01") else 200.0)
    buys = build_buys(Config("monthly_dom", dom=1), prices, 360)
    res = run_window(buys, prices, pd.Period("2024-02"), pd.Period("2024-03"))
    assert res["shares"] == pytest.approx(5.4)
    assert res["final_value"] == pytest.approx(1080)
    assert res["trades"] == 2


def test_fee_reduces_shares():
    prices = make_prices()
    buys = build_buys(Config("monthly_dom", dom=1), prices, 360, fee=10)
    res = run_window(buys, prices, pd.Period("2024-02"), pd.Period("2024-03"))
    assert res["final_value"] == pytest.approx(700)


def test_buy_rolled_past_window_end_counts_as_cash():
    # Friday 2024-03-29 is a holiday, so that weekly buy executes in April,
    # after the March valuation date: its money is held as cash.
    prices = make_prices(
        holidays=["2024-03-29"],
        price_fn=lambda d: 100.0 if d < pd.Timestamp("2024-04-01") else 50.0,
    )
    buys = build_buys(Config("weekly", weekday=4), prices, 360)
    res = run_window(buys, prices, pd.Period("2024-03"), pd.Period("2024-03"))
    assert res["invested"] == pytest.approx(360)
    assert res["final_value"] == pytest.approx(360)
    assert res["trades"] == 4  # 5 Fridays scheduled, 1 rolled out of the window


def test_open_fill_uses_open_price():
    prices = make_prices()
    prices["adj_open"] = 50.0
    buys = build_buys(Config("monthly_dom", dom=1), prices, 360, fill="open")
    res = run_window(buys, prices, pd.Period("2024-02"), pd.Period("2024-02"))
    assert res["shares"] == pytest.approx(7.2)


def test_value_curve_ends_at_final_value():
    prices = make_prices(price_fn=lambda d: 100 + d.dayofyear)
    cfg = Config("biweekly", weekday=2, phase=1)
    buys = build_buys(cfg, prices, 360)
    res = run_window(buys, prices, pd.Period("2024-02"), pd.Period("2024-03"))
    curve = value_curve(buys, prices, pd.Period("2024-02"), pd.Period("2024-03"), 360)
    assert curve["value"].iloc[-1] == pytest.approx(res["final_value"])
    assert curve["value"].iloc[0] == pytest.approx(360)  # first month's deposit, whether invested or not
    assert curve["contributed"].iloc[-1] == pytest.approx(res["invested"])


def test_rolling_matches_single_window():
    prices = make_prices(end="2024-08-31", price_fn=lambda d: 100 + np.sin(d.dayofyear / 5) * 10)
    cfgs = [Config("weekly", weekday=3), Config("monthly_nth", weekday=0, nth=2)]
    roll = rolling(prices, cfgs, 360, 3, pd.Period("2024-02"), pd.Period("2024-07"))
    assert roll["window_start"].nunique() == 4
    lb = leaderboard(prices, cfgs, 360, pd.Period("2024-03"), pd.Period("2024-05")).set_index("config")
    sub = roll[roll["window_start"] == pd.Period("2024-03")].set_index("config")
    for label in lb.index:
        assert sub.at[label, "final_value"] == pytest.approx(lb.at[label, "final_value"])
    summary = rolling_summary(roll)
    assert set(summary["config"]) == {c.label for c in cfgs}
    assert summary["avg_rank"].between(1, 2).all()


def test_xirr_simple_year():
    dates = [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31")]
    assert xirr(dates, [-100, 110]) == pytest.approx(0.10, abs=1e-3)
