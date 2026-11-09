"""Fixed backtest rules. Agents must not edit this file.

- signal(df) -> position in [0, 1] decided at close t, applied to return t+1
- one-way cost per unit of turnover
- equal-weight across the market universe; benchmark = equal-weight buy & hold
- in-sample <= IS_END < out-of-sample
"""
import numpy as np
import pandas as pd

COST = {"US": 0.0005, "KR": 0.0025}
IS_END = "2022-12-31"


class LookaheadError(Exception):
    pass


def check_no_lookahead(signal, df: pd.DataFrame, cuts=(0.5, 0.8)) -> None:
    """Signal on truncated history must match signal on full history up to the cut."""
    full = signal(df)
    for c in cuts:
        k = int(len(df) * c)
        part = signal(df.iloc[:k])
        a, b = full.iloc[:k].astype(float), part.astype(float).reindex(full.index[:k])
        if not np.allclose(a.fillna(-1), b.fillna(-1), atol=1e-9):
            raise LookaheadError(f"signal at t uses data after t (cut {c})")


def asset_returns(df: pd.DataFrame, raw_pos: pd.Series, cost: float) -> pd.Series:
    pos = raw_pos.reindex(df.index).astype(float).fillna(0).clip(0, 1).shift(1).fillna(0)
    ret = df["Close"].pct_change().fillna(0)
    turnover = pos.diff().abs().fillna(pos.abs())
    return pos * ret - turnover * cost


def metrics(r: pd.Series, pos_days: pd.Series | None = None) -> dict:
    r = r.dropna()
    if len(r) < 2:
        return {}
    eq = (1 + r).cumprod()
    years = len(r) / 252
    sd = r.std()
    out = {
        "cagr": float(eq.iloc[-1] ** (1 / years) - 1),
        "sharpe": float(r.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0,
        "mdd": float((eq / eq.cummax() - 1).min()),
        "total": float(eq.iloc[-1] - 1),
    }
    if pos_days is not None:
        active = r[pos_days.reindex(r.index).fillna(0) > 0]
        out["win_rate"] = float((active > 0).mean()) if len(active) else 0.0
        out["exposure"] = float(pos_days.reindex(r.index).fillna(0).mean())
    return {k: round(v, 4) for k, v in out.items()}


def run_market(signal, data: dict[str, pd.DataFrame], market: str) -> dict:
    cost = COST[market]
    strat, bh, expo = {}, {}, {}
    for t, df in data.items():
        check_no_lookahead(signal, df)
        pos = signal(df)
        strat[t] = asset_returns(df, pos, cost)
        bh[t] = df["Close"].pct_change()
        expo[t] = pos.reindex(df.index).fillna(0).shift(1)
    s = pd.DataFrame(strat).mean(axis=1)
    b = pd.DataFrame(bh).mean(axis=1).fillna(0)
    e = pd.DataFrame(expo).mean(axis=1)
    out = {}
    for name, sl in (("is", slice(None, IS_END)), ("oos", slice(IS_END, None))):
        ms, mb = metrics(s[sl], e[sl]), metrics(b[sl])
        ms["excess_cagr"] = round(ms["cagr"] - mb["cagr"], 4)
        ms["bh_cagr"] = mb["cagr"]
        out[name] = ms
    weekly = lambda r: (1 + r).cumprod().resample("W").last().round(4)
    curve = pd.DataFrame({"strategy": weekly(s), "buy_hold": weekly(b)}).dropna()
    return {"metrics": out, "curve": {"dates": [d.strftime("%Y-%m-%d") for d in curve.index],
                                      **{c: curve[c].tolist() for c in curve}}}
