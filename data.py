"""Download daily prices once and cache them locally as CSV.

Runs read from the cache, so results are reproducible until you explicitly
refresh. Dividend-adjusted open/close are derived from Yahoo's Adj Close.
"""
import re
from pathlib import Path

import pandas as pd
import yfinance as yf

CACHE_DIR = Path(__file__).parent / "data"
TICKER_RE = re.compile(r"^[A-Z0-9.\-^]{1,12}$")


def _cache_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker}.csv"


def _download(ticker: str) -> pd.DataFrame:
    raw = yf.download(ticker, period="max", auto_adjust=False, progress=False)
    if raw is None or raw.empty:
        raise ValueError(f"No price data found for {ticker}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.xs(ticker, axis=1, level=1)
    raw = raw.dropna(subset=["Open", "Close", "Adj Close"])
    raw = raw[raw["Close"] > 0]
    ratio = raw["Adj Close"] / raw["Close"]
    df = pd.DataFrame(
        {
            "open": raw["Open"],
            "close": raw["Close"],
            "adj_open": raw["Open"] * ratio,
            "adj_close": raw["Adj Close"],
        }
    )
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.index.name = "date"
    # Today's bar may still be moving; keep only finished sessions.
    return df[df.index < pd.Timestamp.today().normalize()]


def load_prices(ticker: str, refresh: bool = False) -> pd.DataFrame:
    ticker = ticker.strip().upper()
    if not TICKER_RE.match(ticker):
        raise ValueError(f"Invalid ticker: {ticker!r}")
    path = _cache_path(ticker)
    if path.exists() and not refresh:
        return pd.read_csv(path, index_col="date", parse_dates=["date"])
    df = _download(ticker)
    CACHE_DIR.mkdir(exist_ok=True)
    df.to_csv(path)
    return df
