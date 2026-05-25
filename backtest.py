"""
Cross-Sectional Crypto Momentum Backtest
=========================================

A self-contained backtest of a long-only cross-sectional momentum strategy on
a universe of liquid crypto assets, evaluated against an equal-weight
buy-and-hold benchmark.

Method
------
1. Universe: 10 liquid USD spot pairs (BTC, ETH, SOL, BNB, XRP, ADA, AVAX,
   LINK, DOT, LTC).
2. Signal: trailing N-day return (lookback window).
3. Portfolio: at each monthly rebalance, long the top K assets by trailing
   return, equal-weighted. Cash otherwise.
4. Costs: 10 bps round-trip transaction cost on rebalances (turnover-aware).
5. Metrics: annualised return, annualised volatility, Sharpe ratio, max
   drawdown, hit rate, turnover, t-statistic of daily excess returns,
   information ratio vs equal-weight benchmark.

Run
---
    python backtest.py

Outputs
-------
    results.csv             — per-rebalance portfolio holdings + returns
    metrics.json            — summary metrics
    equity_curve.png        — strategy vs benchmark equity curve
    drawdown.png            — strategy underwater plot
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

warnings.simplefilter("ignore", category=FutureWarning)

OUT_DIR = Path(__file__).resolve().parent
UNIVERSE = [
    "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
    "ADA-USD", "AVAX-USD", "LINK-USD", "DOT-USD", "LTC-USD",
]
START = "2021-01-01"
END = datetime.now(timezone.utc).strftime("%Y-%m-%d")

LOOKBACK_DAYS = 60          # trailing return window for momentum signal
TOP_K = 3                   # number of assets held at any time
REBALANCE_FREQ = "ME"       # month-end rebalance ("ME" = month-end)
TXN_BPS_ROUND_TRIP = 10     # 10 basis points round-trip transaction cost
RF_ANNUAL = 0.04            # 4% risk-free rate for Sharpe calculation
TRADING_DAYS_PER_YEAR = 365 # crypto trades every day
TREND_FILTER_MA = 200       # v2: only deploy capital when BTC > 200d MA
TREND_FILTER_TICKER = "BTC-USD"


@dataclass
class Metrics:
    """Headline backtest metrics."""
    ann_return: float
    ann_vol: float
    sharpe: float
    max_drawdown: float
    hit_rate: float
    annual_turnover: float
    t_stat_excess: float
    info_ratio: float

    def as_dict(self) -> dict[str, float]:
        return {
            "annualised_return": round(self.ann_return, 4),
            "annualised_vol": round(self.ann_vol, 4),
            "sharpe_ratio": round(self.sharpe, 3),
            "max_drawdown": round(self.max_drawdown, 4),
            "hit_rate_daily": round(self.hit_rate, 4),
            "annual_turnover": round(self.annual_turnover, 3),
            "t_stat_daily_excess_vs_bench": round(self.t_stat_excess, 3),
            "info_ratio_vs_bench": round(self.info_ratio, 3),
        }


def fetch_prices() -> pd.DataFrame:
    """Download daily-close prices for the universe. Returns wide DataFrame
    indexed by date with one column per ticker."""
    raw = yf.download(
        UNIVERSE,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    # yfinance returns a MultiIndex when given a list — pick the Close level.
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
    else:
        close = raw[["Close"]].rename(columns={"Close": UNIVERSE[0]})
    close = close.dropna(how="all").ffill()
    return close


def build_signal(prices: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Trailing `lookback`-day total return — the momentum signal."""
    return prices.pct_change(lookback)


def build_target_weights(
    signal: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex,
    top_k: int,
) -> pd.DataFrame:
    """At each rebalance date, hold equal-weighted top-K by signal. Between
    rebalances, weights are constant (held), which is the standard sparse-
    rebalance convention."""
    # Sparse weight matrix: only rebalance rows have allocations; the rest
    # stay NaN until ffilled, which gives proper hold-between-rebalances
    # behaviour AND correctly zeroes-out previous winners on rebalance.
    sparse = pd.DataFrame(np.nan, index=signal.index, columns=signal.columns)
    for date in rebalance_dates:
        if date not in signal.index:
            continue
        row = signal.loc[date].dropna()
        if len(row) < top_k:
            continue
        winners = row.nlargest(top_k).index
        sparse.loc[date, :] = 0.0  # ALL assets explicitly zero at rebalance
        sparse.loc[date, winners] = 1.0 / top_k
    weights = sparse.ffill().fillna(0.0)
    return weights


def compute_returns(
    prices: pd.DataFrame, weights: pd.DataFrame, txn_bps: float
) -> tuple[pd.Series, pd.Series]:
    """Return strategy daily returns and benchmark (equal-weight) daily returns.

    Costs are applied on weight changes (turnover) at the bar where weights
    move, in basis points of notional rebalanced (half of round-trip per side
    per asset).
    """
    daily = prices.pct_change().fillna(0.0)

    # Align weights to returns: shift by one bar so today's return uses
    # yesterday's allocation (no look-ahead).
    held = weights.shift(1).fillna(0.0)

    # Turnover at each bar = sum of absolute weight changes.
    turnover = weights.diff().abs().sum(axis=1).fillna(0.0)
    cost = turnover * (txn_bps / 1e4) / 2.0  # one-side cost per leg

    strat_ret = (held * daily).sum(axis=1) - cost

    bench_w = pd.DataFrame(
        1.0 / len(prices.columns),
        index=prices.index,
        columns=prices.columns,
    )
    bench_ret = (bench_w.shift(1).fillna(0.0) * daily).sum(axis=1)

    return strat_ret, bench_ret


def equity_curve(daily_returns: pd.Series) -> pd.Series:
    return (1.0 + daily_returns).cumprod()


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())


def metrics(
    strat: pd.Series, bench: pd.Series, weights: pd.DataFrame
) -> Metrics:
    """Compute headline metrics."""
    eq = equity_curve(strat)
    n_years = len(strat) / TRADING_DAYS_PER_YEAR
    ann_ret = float(eq.iloc[-1] ** (1.0 / n_years) - 1.0)
    ann_vol = float(strat.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else float("nan")
    mdd = max_drawdown(eq)
    hit = float((strat > 0).mean())

    annual_turnover = float(
        weights.diff().abs().sum(axis=1).sum() / n_years
    )

    excess = strat - bench
    if excess.std() > 0:
        t_stat = float(excess.mean() / (excess.std() / np.sqrt(len(excess))))
        info = float(excess.mean() * TRADING_DAYS_PER_YEAR / (
            excess.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
        ))
    else:
        t_stat = float("nan")
        info = float("nan")

    return Metrics(
        ann_return=ann_ret,
        ann_vol=ann_vol,
        sharpe=sharpe,
        max_drawdown=mdd,
        hit_rate=hit,
        annual_turnover=annual_turnover,
        t_stat_excess=t_stat,
        info_ratio=info,
    )


def apply_trend_filter(
    weights: pd.DataFrame, prices: pd.DataFrame, ma_window: int, ticker: str
) -> pd.DataFrame:
    """v2: zero out weights on bars when `ticker` is below its `ma_window`-day
    moving average. Acts as a market-regime risk-off filter."""
    if ticker not in prices.columns:
        return weights
    ma = prices[ticker].rolling(ma_window).mean()
    risk_on = (prices[ticker] > ma).astype(float).reindex(weights.index).fillna(0.0)
    return weights.mul(risk_on, axis=0)


def plot_equity(curves: dict[str, pd.Series], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    styles = {"v1": ("v1: naive momentum top-K", "-", 2.0),
              "v2": (f"v2: momentum + BTC {TREND_FILTER_MA}d trend filter", "-", 2.5),
              "benchmark": ("equal-weight benchmark", "--", 1.5)}
    for name, series in curves.items():
        label, ls, lw = styles.get(name, (name, "-", 1.5))
        equity_curve(series).plot(ax=ax, label=label, lw=lw, linestyle=ls)
    ax.set_title("Cross-Sectional Crypto Momentum — Equity Curves (log scale)")
    ax.set_ylabel("Cumulative growth of £1")
    ax.set_xlabel("Date")
    ax.set_yscale("log")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_drawdown(strat: pd.Series, path: Path) -> None:
    eq = equity_curve(strat)
    dd = eq / eq.cummax() - 1.0
    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.fill_between(dd.index, dd.values, 0.0, color="crimson", alpha=0.4)
    ax.set_title("Strategy Drawdown (underwater plot)")
    ax.set_ylabel("Drawdown")
    ax.set_xlabel("Date")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def main() -> None:
    print(f"[1/6] Fetching prices for {len(UNIVERSE)} assets: {START} to {END} ...")
    prices = fetch_prices()
    print(f"      Got {len(prices)} daily bars for {len(prices.columns)} assets.")

    print(f"[2/6] Building momentum signal (lookback={LOOKBACK_DAYS}d) ...")
    signal = build_signal(prices, LOOKBACK_DAYS)

    print(f"[3/6] Building target weights (top-{TOP_K}, {REBALANCE_FREQ} rebalance) ...")
    rebalance_dates = pd.date_range(prices.index[0], prices.index[-1], freq=REBALANCE_FREQ)
    rebalance_dates = rebalance_dates.intersection(prices.index)
    w_v1 = build_target_weights(signal, rebalance_dates, TOP_K)

    print(f"[4/6] Applying {TREND_FILTER_MA}d {TREND_FILTER_TICKER} trend filter (v2) ...")
    w_v2 = apply_trend_filter(w_v1, prices, TREND_FILTER_MA, TREND_FILTER_TICKER)

    print(f"[5/6] Computing returns ...")
    v1_ret, bench_ret = compute_returns(prices, w_v1, TXN_BPS_ROUND_TRIP)
    v2_ret, _ = compute_returns(prices, w_v2, TXN_BPS_ROUND_TRIP)

    print(f"[6/6] Computing metrics + writing outputs ...")
    m_v1 = metrics(v1_ret, bench_ret, w_v1)
    m_v2 = metrics(v2_ret, bench_ret, w_v2)
    m_bench = metrics(bench_ret, bench_ret, pd.DataFrame(0.0, index=bench_ret.index, columns=prices.columns))

    summary = {
        "v1_naive_momentum": m_v1.as_dict(),
        "v2_momentum_plus_trend_filter": m_v2.as_dict(),
        "benchmark_equal_weight": m_bench.as_dict(),
    }
    (OUT_DIR / "metrics.json").write_text(json.dumps(summary, indent=2))
    pd.concat(
        {"v1_strategy": v1_ret, "v2_strategy": v2_ret, "benchmark": bench_ret},
        axis=1,
    ).to_csv(OUT_DIR / "results.csv")
    plot_equity({"v1": v1_ret, "v2": v2_ret, "benchmark": bench_ret}, OUT_DIR / "equity_curve.png")
    plot_drawdown(v2_ret, OUT_DIR / "drawdown.png")

    print("\n=== v1 naive momentum (no filter) ===")
    for k, v in m_v1.as_dict().items():
        print(f"  {k:35s} {v}")
    print("\n=== v2 momentum + BTC 200d trend filter ===")
    for k, v in m_v2.as_dict().items():
        print(f"  {k:35s} {v}")
    print("\n=== benchmark (equal-weight buy & hold) ===")
    for k, v in m_bench.as_dict().items():
        print(f"  {k:35s} {v}")
    print(f"\nOutputs written to: {OUT_DIR}")


if __name__ == "__main__":
    main()
