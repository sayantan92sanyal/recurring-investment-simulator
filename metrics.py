"""Return metrics."""
from typing import Sequence

import numpy as np
import pandas as pd


def xirr(dates: Sequence[pd.Timestamp], flows: Sequence[float]) -> float:
    """Annualised money-weighted return (the rate at which the flows' NPV is zero).

    Deterministic bisection; returns NaN if there is no sign change.
    """
    if len(flows) < 2:
        return np.nan
    t0 = min(dates)
    years = np.array([(d - t0).days / 365.0 for d in dates])
    cf = np.asarray(flows, dtype=float)

    def npv(rate: float) -> float:
        return float(np.sum(cf / (1.0 + rate) ** years))

    lo, hi = -0.99, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if np.sign(f_lo) == np.sign(f_hi):
        return np.nan
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9:
            break
        if np.sign(f_mid) == np.sign(f_lo):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return (lo + hi) / 2
