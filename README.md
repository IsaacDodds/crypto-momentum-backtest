# Cross-sectional crypto momentum backtest

A self-contained backtest of a long-only cross-sectional momentum strategy
on a universe of 10 large-cap USD crypto pairs, evaluated against an
equal-weight buy-and-hold benchmark.

The repo ships two strategy versions:

- **v1, naive cross-sectional momentum** (top-3 by trailing 60-day return,
  monthly rebalance). Loses money over 2021 to 2026 and underperforms the
  benchmark with a t-statistic of −2.5.
- **v2, momentum with a BTC 200-day trend filter** (deploy capital only when
  BTC is above its 200-day moving average). Recovers a positive return and
  roughly halves the max drawdown against both v1 and the benchmark, but
  still does not beat equal-weight buy-and-hold on a Sharpe basis in this
  sample.

Naive cross-sectional momentum on this universe is dominated by buy-and-hold
over 2021 to 2026. The trend filter works as a drawdown control, not as an
alpha source.

---

## Results

| metric | v1 naive | v2 + BTC 200d trend filter | benchmark (equal-weight) |
|---|---:|---:|---:|
| annualised return | -7.7% | +10.8% | +35.6% |
| annualised vol | 74.3% | 48.9% | 75.6% |
| Sharpe (rf = 4%) | -0.16 | 0.14 | 0.42 |
| max drawdown | -89.8% | -53.8% | -81.9% |
| daily hit rate | 49.7% | 25.6% | 52.5% |
| annual turnover | 11.1x | 14.9x | 0.0x |
| t-stat (excess daily vs bench) | -2.54 | -1.36 | n/a |
| information ratio vs bench | -1.09 | -0.58 | n/a |

Sample: 2021-01-01 to 2026-05-25, daily close (yfinance).

![Equity curves](equity_curve.png)

![v2 drawdown](drawdown.png)

---

## Findings

1. **Buy-and-hold dominates.** Equal-weight large-cap crypto returned
   35.6% annualised with Sharpe 0.42 over 2021 to 2026. Momentum has to beat
   that, and does not.
2. **Naive momentum anti-selects at turning points.** The top-3 trailing
   60-day winners are reliably late-cycle names (LUNA-like episodes) that
   mean-revert harder than the field. A t-stat of −2.5 against the benchmark
   is statistically significant underperformance.
3. **The regime filter cuts drawdown roughly in half.** The 200-day BTC trend
   filter takes max drawdown from −89.8% (v1) and −81.9% (benchmark) down
   to −53.8%. That is a real risk-management improvement even though it
   does not generate alpha.
4. **Turnover is high and corrosive.** v2 turns over about 15 times a year.
   At the modelled 10 bps round-trip cost that eats about 75 bps annually,
   which is meaningful but not the main driver of underperformance.
5. **Conclusion.** This momentum specification on this universe is not a
   strategy. The trend filter is useful as a defensive overlay on any
   long-only crypto exposure. The next research directions would be
   (a) long-short cross-sectional momentum, (b) risk-parity weighting
   instead of equal-weight, and (c) a finer-grained universe of around 50
   assets where dispersion is larger.

---

## Methodology

- **Universe.** Top-10 USD crypto pairs by market cap: BTC, ETH, SOL,
  BNB, XRP, ADA, AVAX, LINK, DOT, LTC. The universe is fixed in advance, so
  there is no survivorship bias from end-of-period selection.
- **Signal.** Trailing 60-day percentage return.
- **Portfolio construction.** At each month-end rebalance, hold the top-K
  assets equal-weighted (K = 3 for v1 and v2). Cash otherwise.
- **Trend filter (v2).** Multiply weights by 1{BTC > BTC 200-day MA}.
  When BTC is below its 200-day MA on the rebalance bar, hold cash.
- **Costs.** 10 bps round-trip transaction cost on turnover (5 bps each
  side per leg).
- **Risk-free rate.** 4% annual flat for Sharpe.
- **Annualisation.** 365 days per year (crypto trades daily).
- **No look-ahead.** Returns use yesterday's close weights against today's
  return.

---

## Reproduce

```bash
pip install yfinance pandas matplotlib numpy
python backtest.py
```

Outputs `metrics.json`, `results.csv`, `equity_curve.png` and `drawdown.png`
in the repo root.

---

## Limitations

- Single sample period (2021 to 2026). Crypto regimes change fast; this is
  one draw from a small distribution.
- Universe selected with hindsight (the 10 names that are large-cap today).
- No slippage, no exchange-specific borrow costs, no taxes.
- Long-only by construction. Long-short would change the picture
  materially.
- Monthly rebalance is a coarse choice. Daily or vol-targeted rebalancing
  would change the turnover and risk dynamics.

---

## Author

Isaac Dodds, MSc Advanced Machine Learning, University of Bath.
