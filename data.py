"""Download daily prices once and cache them locally as CSV.

Runs read from the cache, so results are reproducible until you explicitly
refresh. Dividend-adjusted open/close are derived from Yahoo's Adj Close.

Yahoo often rate-limits shared cloud servers, so a copy of popular tickers
ships in seed/ and is used when a download fails.
"""
import re
import time
from pathlib import Path

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

CACHE_DIR = Path(__file__).parent / "data"
SEED_DIR = Path(__file__).parent / "seed"
RETRY_WAITS = (2, 5)  # seconds to wait before each retry after a rate-limit
TICKER_RE = re.compile(r"^[A-Z0-9.\-^]{1,12}$")


def _cache_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker}.csv"


class PriceDataError(Exception):
    """Prices could not be loaded; the message is meant for the user."""


def _download(ticker: str) -> pd.DataFrame:
    raw = yf.Ticker(ticker).history(period="max", auto_adjust=False, raise_errors=True)
    if raw is None or raw.empty:
        raise PriceDataError(f"Yahoo Finance has no price data for {ticker}. Check the symbol.")
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
        return _read(path)
    try:
        df = _download_with_retry(ticker)
    except PriceDataError:
        raise
    except Exception as e:  # noqa: BLE001 - any download failure falls back to the saved copy
        seed = SEED_DIR / f"{ticker}.csv"
        if seed.exists():
            return _read(seed)
        if isinstance(e, YFRateLimitError):
            raise PriceDataError(
                "Yahoo Finance is temporarily refusing downloads (rate-limited). "
                "Wait a minute and try again, or pick a ticker that has saved prices."
            ) from e
        raise PriceDataError(f"Could not download prices for {ticker}: {e}") from e
    CACHE_DIR.mkdir(exist_ok=True)
    df.to_csv(path)
    return df


def _download_with_retry(ticker: str) -> pd.DataFrame:
    for wait in RETRY_WAITS:
        try:
            return _download(ticker)
        except YFRateLimitError:
            time.sleep(wait)
    return _download(ticker)


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, index_col="date", parse_dates=["date"])


def saved_tickers() -> list:
    return sorted(p.stem for p in SEED_DIR.glob("*.csv"))
