import numpy as np
import pandas as pd
import pytest

from engine.backtest import LookaheadError, asset_returns, check_no_lookahead


def _df(n=300, seed=0):
    rng = np.random.default_rng(seed)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, n)),
                      index=pd.bdate_range("2020-01-01", periods=n))
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1.0})


def test_cheating_signal_rejected():
    peek = lambda df: (df["Close"].shift(-1) > df["Close"]).astype(float)
    with pytest.raises(LookaheadError):
        check_no_lookahead(peek, _df())


def test_honest_signal_passes():
    sma = lambda df: (df["Close"] > df["Close"].rolling(20).mean()).astype(float)
    check_no_lookahead(sma, _df())


def test_always_long_equals_buy_hold_minus_entry_cost():
    df = _df()
    r = asset_returns(df, pd.Series(1.0, index=df.index), cost=0.01)
    bh = df["Close"].pct_change().fillna(0)
    diff = r - bh
    # day 0 flat, day 1 pays entry cost on first applied position, nothing else
    assert diff.iloc[0] == 0
    assert np.isclose(diff.iloc[1], -0.01)
    assert np.allclose(diff.iloc[2:], 0)
