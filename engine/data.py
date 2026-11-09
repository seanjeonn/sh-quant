"""Fixed universe + cached daily OHLCV. Agents must not edit this file."""
import datetime as dt
from pathlib import Path

import pandas as pd

START = "2015-01-01"
CACHE = Path(__file__).resolve().parent.parent / "data" / "cache"

UNIVERSE = {
    "US": ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "XOM", "JNJ", "BRK-B"],
    # KODEX200 + large caps listed before 2015
    "KR": ["069500", "005930", "000660", "207940", "005380", "000270", "035420", "051910", "006400", "105560", "055550", "035720"],
}
COLS = ["Open", "High", "Low", "Close", "Volume"]


def _fetch(market: str, ticker: str) -> pd.DataFrame:
    if market == "US":
        import yfinance as yf
        df = yf.Ticker(ticker).history(start=START, auto_adjust=True)
        df.index = df.index.tz_localize(None)
    else:
        import FinanceDataReader as fdr
        df = fdr.DataReader(ticker, START)
    return df[COLS].dropna()


def load(market: str) -> dict[str, pd.DataFrame]:
    """{ticker: OHLCV DataFrame}. Cache refreshed once per day."""
    CACHE.mkdir(parents=True, exist_ok=True)
    out = {}
    for t in UNIVERSE[market]:
        f = CACHE / f"{market}_{t}.csv"
        fresh = f.exists() and dt.date.fromtimestamp(f.stat().st_mtime) == dt.date.today()
        if fresh:
            df = pd.read_csv(f, index_col=0, parse_dates=True)
        else:
            try:
                df = _fetch(market, t)
                df.to_csv(f)
            except Exception as e:  # stale cache beats no data
                if not f.exists():
                    print(f"[data] skip {market}:{t}: {e}")
                    continue
                df = pd.read_csv(f, index_col=0, parse_dates=True)
        out[t] = df
    return out
