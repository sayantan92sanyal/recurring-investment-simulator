"""Turn an investment configuration into concrete buy dates.

A configuration says *when* you intend to buy (e.g. "every other Tuesday").
The schedule is generated on the calendar, then each scheduled date is rolled
forward to the next trading day if the market is closed (as brokers do).
"""
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}

# Bi-weekly phase is decided by counting whole weeks from this fixed Monday, so
# "phase A" always refers to the same set of weeks regardless of the window.
BIWEEKLY_ANCHOR = pd.Timestamp("2000-01-03")

GROUPS = ["Daily", "Weekly", "Bi-weekly", "Monthly (Nth weekday)", "Monthly (date)"]


@dataclass(frozen=True)
class Config:
    kind: str  # daily | weekly | biweekly | monthly_nth | monthly_dom
    weekday: Optional[int] = None  # 0 = Mon … 4 = Fri
    phase: Optional[int] = None  # bi-weekly: 0 = A, 1 = B
    nth: Optional[int] = None  # monthly_nth: 1..4
    dom: Optional[int] = None  # monthly_dom: 1..28

    @property
    def group(self) -> str:
        return {
            "daily": "Daily",
            "weekly": "Weekly",
            "biweekly": "Bi-weekly",
            "monthly_nth": "Monthly (Nth weekday)",
            "monthly_dom": "Monthly (date)",
        }[self.kind]

    @property
    def label(self) -> str:
        if self.kind == "daily":
            return "Daily"
        if self.kind == "weekly":
            return f"Weekly · {WEEKDAYS[self.weekday]}"
        if self.kind == "biweekly":
            return f"Bi-weekly · {WEEKDAYS[self.weekday]} ({'AB'[self.phase]})"
        if self.kind == "monthly_nth":
            return f"Monthly · {ORDINALS[self.nth]} {WEEKDAYS[self.weekday]}"
        return f"Monthly · day {self.dom}"


def all_configs() -> List[Config]:
    configs = [Config("daily")]
    configs += [Config("weekly", weekday=w) for w in range(5)]
    configs += [Config("biweekly", weekday=w, phase=p) for w in range(5) for p in range(2)]
    configs += [Config("monthly_nth", weekday=w, nth=n) for n in range(1, 5) for w in range(5)]
    configs += [Config("monthly_dom", dom=d) for d in range(1, 29)]
    return configs


def config_by_label(label: str) -> Config:
    for cfg in all_configs():
        if cfg.label == label:
            return cfg
    raise KeyError(label)


def _calendar_dates(cfg: Config, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    cal = pd.date_range(start, end, freq="D")
    if cfg.kind == "weekly":
        return cal[cal.weekday == cfg.weekday]
    if cfg.kind == "biweekly":
        weeks = (cal - BIWEEKLY_ANCHOR).days // 7
        return cal[(cal.weekday == cfg.weekday) & (weeks % 2 == cfg.phase)]
    if cfg.kind == "monthly_nth":
        nth = (cal.day - 1) // 7 + 1
        return cal[(cal.weekday == cfg.weekday) & (nth == cfg.nth)]
    if cfg.kind == "monthly_dom":
        return cal[cal.day == cfg.dom]
    raise ValueError(cfg.kind)


def schedule(cfg: Config, trading_days: pd.DatetimeIndex) -> pd.DataFrame:
    """Scheduled and executed dates for `cfg` across the span of `trading_days`.

    Returns columns: scheduled, executed (NaT if it would roll past the data).
    """
    if cfg.kind == "daily":
        return pd.DataFrame({"scheduled": trading_days, "executed": trading_days})

    scheduled = _calendar_dates(cfg, trading_days[0], trading_days[-1])
    idx = trading_days.searchsorted(scheduled, side="left")
    in_range = idx < len(trading_days)
    executed = pd.Series(pd.NaT, index=range(len(scheduled)), dtype="datetime64[ns]")
    executed[in_range] = trading_days[idx[in_range]]
    return pd.DataFrame({"scheduled": scheduled, "executed": executed.values})
