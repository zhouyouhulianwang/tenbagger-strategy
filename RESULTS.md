# Measured Results (v8.2 → v8.4)

> **Bottom line**: after removing look-ahead bias and survivorship-flavored
> hand-tuning, the strategy as designed **does not beat buy-and-hold SPY**
> over the test window. The impressive numbers in earlier versions were
> largely artifacts of static "current" fundamentals applied to past dates.

Test window: **2020-01-10 → 2023-12-29** (1000 trading days, SPY total return **+25.9%**).
All versions run the same engine unless noted; transaction costs include
SEC fee (sell), FINRA TAF (sell), and market-cap-tiered slippage.

| Version | Universe | Fundamentals | Total Return | CAGR | Sharpe | Max DD | vs SPY |
|---|---|---|---|---|---|---|---|
| v8.2 (original) | 10 stocks | static 2024 snapshot | +29.7% | +9.2% | 1.06 | -12.2% | +3.8% |
| v8.3 (P0/P1 engine fixes) | 10 stocks | static 2024 snapshot | +73.5% | +20.4% | 1.27 | -18.3% | +47.6% |
| **v8.4 (PIT, de-biased)** | 10 stocks | SEC XBRL point-in-time | **+3.8%** | +1.3% | 0.16 | -35.0% | **-22.0%** |
| **v8.4 (PIT, de-biased)** | 487 stocks | SEC XBRL point-in-time | **+15.9%** | +5.1% | 0.37 | -17.6% | **-10.0%** |

Reading guide:

- **v8.3 > v8.2** is *not* "fix alpha". v8.3 is the first version that actually
  implements what the README describes (weekly full liquidation removed, risk
  controller and hedge engine wired into the backtest, SPY excluded from
  candidates, real VIX). The old +29.7% was the number produced by a different,
  buggier mechanism.
- **v8.4 ≪ v8.3** is the price of honesty: replacing the static 2024-01
  fundamental snapshot (which encodes 4 years of future knowledge) with
  point-in-time SEC filings collapses the measured edge to below the benchmark.

## Why the edge was an artifact (two concrete mechanisms)

1. **TSLA 2022** — the static snapshot carried `gm = 0.19` (TSLA's gross
   margin *after* the 2023-24 price cuts), which accidentally excluded TSLA
   from growth selection. Real-time 2022 filings showed ROE ~30%, GM ~27%,
   revenue +50% YoY — a textbook growth buy right before the -65% drawdown.
   v8.4 correctly buys it and correctly loses.
2. **NVDA 2023** — point-in-time filings at the AI inflection (May 2023)
   showed TTM net income -49% YoY, revenue -12%, PE > 200: fundamentals
   looked worst exactly before the +240% rally. The static 2024 snapshot
   "knew" the recovery and held NVDA throughout.

## What v8.4 changed (measurement integrity)

- `PointInTimeFundamentals`: quarterly snapshots from SEC XBRL
  `companyfacts`, each visible only from its earliest EDGAR `filed` date.
  TTM flows (revenue, net income, gross profit, dividends) built from
  quarterly facts with YTD differencing and Q4 = FY − 3Q derivation;
  PE/PB/ROE/GM/growth/PEG/dividend-yield/market-cap recomputed at each
  query date using that day's price and split-adjusted share counts.
- Removed `INNOVATION_PREMIUM` / `SECTOR_PREMIUM` hand-tuned score boosts.
- FINRA TAF now sell-side only (matches reality).
- `--universe full`: 487 validated tickers (12 rejected: subsidiaries,
  private companies, post-window IPOs — e.g. FDXF, HONA, SPCX, CRWV).

## Residual biases (still not fully clean)

- **Survivorship**: `Config.UNIVERSE` is a *current* S&P500+NDX constituent
  list; companies delisted during 2020-2023 are absent, so even the v8.4
  full-pool numbers are **optimistically biased**.
- Sectors for the 487-stock pool derive from current SIC codes (mild look-ahead).
- Price history: Nasdaq 1000-row daily endpoint (2020-01-10 → 2023-12-29);
  adjusted for splits, not independently cross-validated against a second vendor.

## Reproduce

```bash
python download_universe.py                                   # price histories -> data/universe/
python build_pit_fundamentals.py                              # PIT snapshots  -> data/pit_fundamentals_full.json
python tenbagger_v8_2_production.py --mode backtest                    # 10-stock dev universe
python tenbagger_v8_2_production.py --mode backtest --universe full    # full pool
```
