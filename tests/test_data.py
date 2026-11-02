import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import data  # noqa: E402


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    cache, seed = tmp_path / "data", tmp_path / "seed"
    seed.mkdir()
    monkeypatch.setattr(data, "CACHE_DIR", cache)
    monkeypatch.setattr(data, "SEED_DIR", seed)
    monkeypatch.setattr(data, "RETRY_WAITS", (0, 0))
    return cache, seed


def _frame():
    idx = pd.DatetimeIndex(["2024-01-02", "2024-01-03"], name="date")
    return pd.DataFrame({"open": [1.0, 2.0], "close": [1.0, 2.0], "adj_open": [1.0, 2.0], "adj_close": [1.0, 2.0]},
                        index=idx)


def _rate_limited(ticker):
    raise data.YFRateLimitError()


def test_falls_back_to_seed_when_download_fails(dirs, monkeypatch):
    _, seed = dirs
    _frame().to_csv(seed / "VOO.csv")
    monkeypatch.setattr(data, "_download", _rate_limited)
    df = data.load_prices("voo")
    assert df["close"].tolist() == [1.0, 2.0]


def test_rate_limit_without_seed_explains_the_cause(dirs, monkeypatch):
    monkeypatch.setattr(data, "_download", _rate_limited)
    with pytest.raises(data.PriceDataError, match="rate-limit"):
        data.load_prices("ZZZ")


def test_retries_rate_limit_before_succeeding(dirs, monkeypatch):
    calls = []

    def flaky(ticker):
        calls.append(ticker)
        if len(calls) < 3:
            raise data.YFRateLimitError()
        return _frame()

    monkeypatch.setattr(data, "_download", flaky)
    assert len(data.load_prices("QQQ")) == 2
    assert len(calls) == 3


def test_fresh_download_preferred_over_seed(dirs, monkeypatch):
    cache, seed = dirs
    old = _frame().iloc[:1]
    old.to_csv(seed / "VOO.csv")
    monkeypatch.setattr(data, "_download", lambda t: _frame())
    assert len(data.load_prices("VOO")) == 2
    assert (cache / "VOO.csv").exists()
