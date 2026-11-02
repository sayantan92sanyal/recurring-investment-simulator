"""Replay a buying schedule against historical prices.

Budget rule: every calendar month receives the same fixed budget, split evenly
across that month's scheduled buys (e.g. $360 over 4 Tuesdays = $90 each, over
5 Tuesdays = $72 each). A buy belongs to the month it was *scheduled* in, even
if a holiday pushes execution into the next month.

Prices are dividend-adjusted, so holding adjusted shares is equivalent to
reinvesting every dividend.
"""
from typing import Dict, List

import numpy as np
import pandas as pd

from metrics import xirr
from schedule import Config, schedule


def build_buys(
    cfg: Config, prices: pd.DataFrame, monthly_budget: float, fill: str = "close", fee: float = 0.0
) -> pd.DataFrame:
    """Every buy over the full price history, with amount, fill price and shares."""
    buys = schedule(cfg, prices.index)
    buys["month"] = buys["scheduled"].dt.to_period("M")
    per_month = buys.groupby("month")["scheduled"].transform("count")
    buys["amount"] = monthly_budget / per_month

    price_col = "adj_open" if fill == "open" else "adj_close"
    buys["price"] = prices[price_col].reindex(buys["executed"]).values
    buys["shares"] = np.where(
        buys["executed"].notna(), np.maximum(buys["amount"] - fee, 0.0) / buys["price"], 0.0
    )
    buys["shares"] = buys["shares"].fillna(0.0)
    return buys


def complete_months(prices: pd.DataFrame) -> pd.PeriodIndex:
    """Months fully covered by the data (excludes the first and last, which may be partial)."""
    months = prices.index.to_period("M").unique()
    return months[1:-1]


def valuation_date(prices: pd.DataFrame, end_month: pd.Period) -> pd.Timestamp:
    return prices.index[prices.index.to_period("M") <= end_month][-1]


def run_window(
    buys: pd.DataFrame, prices: pd.DataFrame, start_month: pd.Period, end_month: pd.Period
) -> Dict:
    """Result of one config over [start_month, end_month], valued at the last close of end_month.

    Money for buys that execute after the valuation date (holiday roll past the
    window end) is counted as uninvested cash.
    """
    value_date = valuation_date(prices, end_month)
    window = buys[(buys["month"] >= start_month) & (buys["month"] <= end_month)]
    done = window["executed"].notna() & (window["executed"] <= value_date)

    invested = window["amount"].sum()
    shares = window.loc[done, "shares"].sum()
    cash = window.loc[~done, "amount"].sum()
    holdings = shares * prices.at[value_date, "adj_close"]
    final_value = holdings + cash

    executed = window.loc[done]
    flows_dates = list(executed["executed"]) + [value_date]
    flows = list(-executed["amount"]) + [holdings]
    return {
        "invested": invested,
        "final_value": final_value,
        "profit": final_value - invested,
        "return_pct": (final_value / invested - 1) * 100,
        "xirr_pct": xirr(flows_dates, flows) * 100,
        "avg_cost": executed["amount"].sum() / shares if shares else np.nan,
        "shares": shares,
        "trades": int(done.sum()),
        "first_buy": executed["executed"].min(),
        "value_date": value_date,
    }


def leaderboard(
    prices: pd.DataFrame,
    configs: List[Config],
    monthly_budget: float,
    start_month: pd.Period,
    end_month: pd.Period,
    fill: str = "close",
    fee: float = 0.0,
) -> pd.DataFrame:
    rows = []
    for cfg in configs:
        buys = build_buys(cfg, prices, monthly_budget, fill, fee)
        res = run_window(buys, prices, start_month, end_month)
        rows.append({"config": cfg.label, "group": cfg.group, **res})
    df = pd.DataFrame(rows).sort_values("final_value", ascending=False).reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))
    return df


def value_curve(
    buys: pd.DataFrame,
    prices: pd.DataFrame,
    start_month: pd.Period,
    end_month: pd.Period,
    monthly_budget: float,
) -> pd.DataFrame:
    """Daily account value (holdings + not-yet-invested cash) and money contributed so far,
    assuming each month's budget lands in the account on that month's first trading day."""
    value_date = valuation_date(prices, end_month)
    days = prices.index[
        (prices.index.to_period("M") >= start_month) & (prices.index <= value_date)
    ]
    window = buys[(buys["month"] >= start_month) & (buys["month"] <= end_month)]
    window = window[window["executed"].notna()]

    spent = window.groupby("executed")["amount"].sum().reindex(days, fill_value=0).cumsum()
    shares = window.groupby("executed")["shares"].sum().reindex(days, fill_value=0).cumsum()
    month_starts = days.to_period("M")
    deposits = pd.Series(month_starts != np.roll(month_starts, 1), index=days)
    deposits.iloc[0] = True
    contributed = deposits.cumsum() * monthly_budget

    value = shares * prices["adj_close"].reindex(days) + (contributed - spent)
    return pd.DataFrame({"value": value, "contributed": contributed})


def rolling(
    prices: pd.DataFrame,
    configs: List[Config],
    monthly_budget: float,
    window_months: int,
    first_month: pd.Period,
    last_month: pd.Period,
    fill: str = "close",
    fee: float = 0.0,
) -> pd.DataFrame:
    """Run every config over every `window_months`-long window, stepping one month.

    Returns one row per (window_start, config) with final value and return %.
    """
    starts = pd.period_range(first_month, last_month - (window_months - 1), freq="M")
    if len(starts) == 0:
        return pd.DataFrame()

    adj_close = prices["adj_close"]
    month_of_day = prices.index.to_period("M")
    rows = []
    for cfg in configs:
        buys = build_buys(cfg, prices, monthly_budget, fill, fee)
        month = buys["month"].values
        executed = buys["executed"].values
        amount = buys["amount"].values
        shares = buys["shares"].values
        for start in starts:
            end = start + (window_months - 1)
            value_date = prices.index[month_of_day <= end][-1]
            in_win = (month >= start) & (month <= end)
            done = in_win & ~pd.isna(executed) & (executed <= np.datetime64(value_date))
            invested = amount[in_win].sum()
            final_value = shares[done].sum() * adj_close.at[value_date] + amount[in_win & ~done].sum()
            rows.append(
                {
                    "window_start": start,
                    "config": cfg.label,
                    "group": cfg.group,
                    "final_value": final_value,
                    "return_pct": (final_value / invested - 1) * 100,
                }
            )
    df = pd.DataFrame(rows)
    # Rank within each window (1 = best) so schedules can be compared across
    # windows regardless of how the market moved overall.
    df["rank"] = df.groupby("window_start")["return_pct"].rank(ascending=False, method="min")
    return df


def rolling_summary(roll: pd.DataFrame) -> pd.DataFrame:
    """Per config: typical total return across windows, and how often it ranks near the top."""
    n_configs = roll["config"].nunique()
    top_cut = max(1, round(n_configs * 0.1))
    summary = roll.groupby(["config", "group"]).agg(
        median_return_pct=("return_pct", "median"),
        mean_return_pct=("return_pct", "mean"),
        worst_return_pct=("return_pct", "min"),
        best_return_pct=("return_pct", "max"),
        avg_rank=("rank", "mean"),
        top10_pct=("rank", lambda s: (s <= top_cut).mean() * 100),
    )
    return summary.sort_values("median_return_pct", ascending=False).reset_index()
