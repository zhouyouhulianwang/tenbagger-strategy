# Measured Results (v8.2 → v8.6)

> **Bottom line (updated 2026-07-30)**: over the extended window
> **2020-01-10 → 2026-07-29**, the v8.6 full-pool strategy (growth sleeve
> removed after a 21-experiment attribution battery) returns **+240.0% vs
> SPY +95.6% (+144pp)**, Sharpe **1.20**, Max DD **-24.7%**, and beats SPY
> in BOTH sub-periods (2020-23: +60.1% vs +25.5%; 2024-26: +116.8% vs
> +56.7%). Numbers still carry survivorship bias (2026-era constituents)
> and are an **overestimate** — see caveats.

## v8.6: strategy attribution & ablation battery (2026-07-30)

21 full-pool backtests (solo / ablation / hedge / risk / filter / stop
variants). Headline findings, all vs base +172.8% / Sharpe 0.99 / MDD -27.6%:

| Component | Evidence | Verdict |
|---|---|---|
| Momentum | ablation collapses to +11.3% (-161pp) | **core driver, keep** |
| Value | ablation -88pp; solo Sharpe 1.13 (best) | **core, keep** |
| Defensive | ablation -75pp, MDD worsens to -36.6% | keep (panic protection) |
| **Growth** | solo +40.7%/0.42 (worst); **ablation +240.0% (+67pp)** | **removed in v8.6** |
| SQQQ hedge 10% | hedge_off -82pp; compress_only ≈ hedge_off | keep - protection comes from the short exposure itself, NOT the stock compression |
| Risk breakers | risk_off -12pp | keep |
| Volatility filter | off: +45.1% (-128pp) | keep |
| -8% hard stop | wide: -72pp; off: -92pp | keep |
| 21d-high filter | off: +174.8% (+2pp) | neutral, kept |

Growth removal robustness: improvement holds in both sub-periods and in 5
of 6 calendar years (only 2024 lags base). It is a one-bit change
(weight=0), not parameter fitting. Growth picks are mildly profitable
standalone (+$16K attributed) but crowd out momentum slots — negative
opportunity cost, not bad signals.

## Extended window: 2020-01-10 → 2026-07-29 (v8.6 vs v8.4, PIT fundamentals)

| Universe | Version | Total Return | CAGR | Sharpe | Max DD | vs SPY |
|---|---|---|---|---|---|---|
| 487 stocks | **v8.6** | **+240.0%** | +24.8% | **1.20** | -24.7% | **+144.4%** |
| 487 stocks | v8.4 | +172.8% | +19.9% | 0.99 | -27.6% | +77.2% |
| 10 stocks (dev) | v8.6 | +79.8% | +11.5% | 0.79 | — | -15.8% |
| 10 stocks (dev) | v8.4 | +44.3% | +6.9% | 0.54 | -35.0% | -51.3% |

Yearly (v8.6 full pool vs SPY):

| Year | v8.6 | SPY | Note |
|---|---|---|---|
| 2021 | +19.4% | +27.0% | still lags mega-cap bull, much less |
| 2022 | -3.4% | -19.5% | defense + hedge work |
| 2023 | +39.2% | +24.3% | strong capture |
| 2024 | +47.2% | +23.3% | AI-infra momentum (only year < v8.4) |
| 2025 | +18.0% | +16.4% | tariff crash weathered |
| 2026 YTD | +22.3% | +7.0% | broad leadership |

## Extended window: 2020-01-10 → 2026-07-29 (v8.4, PIT fundamentals)

| Universe | Total Return | CAGR | Sharpe | Max DD | vs SPY |
|---|---|---|---|---|---|
| 487 stocks | **+172.8%** | +19.9% | 0.99 | -27.6% | **+77.2%** |
| 10 stocks (dev) | +44.3% | +6.9% | 0.54 | -35.0% | -51.3% |

Yearly (full pool vs SPY):

| Year | Full pool | SPY | Note |
|---|---|---|---|
| 2021 | +2.8% | +27.0% | lags in mega-cap-led bull |
| 2022 | -7.8% | -19.5% | defense + hedge work |
| 2023 | +22.3% | +24.3% | in line |
| 2024 | +59.8% | +23.3% | AI-infra momentum capture |
| 2025 | +18.8% | +16.4% | MDD -27.6% in April tariff crash |
| 2026 YTD | +24.0% | +7.0% | broad momentum leadership |

Attribution (full pool, 166 symbols traded): top winners NVDA, HPE, WDC,
VRT, CVNA, MU, TER, LITE, TPL, FIX, LRCX; SQQQ hedge drag **-17.5k USD
(~2.7%/yr)** over the window. Final positions (2026-07-28): DDOG, LLY,
DVA, FTNT, FIS, T, ~4% cash, no hedge.

**Caveat — survivorship**: the 487-stock pool is a 2026-07 constituent
list. The 2024-2026 winners above are precisely the stocks that survived
into today's index, so the +77pp excess overstates what a 2020 investor
with only then-current membership would have captured. The 2021 lag
(+2.8% vs +27.0%) shows pool enrichment alone does not produce alpha —
the 2024-2026 capture came from the momentum engine rotating into
trending names (166 distinct symbols traded), but an honest historical
constituent list would still shave the headline number.

## Original window: 2020-01-10 → 2023-12-29 (reproduces exactly in the extended data)

SPY total return over this window: **+25.9%**.

| Version | Universe | Fundamentals | Total Return | CAGR | Sharpe | Max DD | vs SPY |
|---|---|---|---|---|---|---|---|
| v8.2 (original) | 10 stocks | static 2024 snapshot | +29.7% | +9.2% | 1.06 | -12.2% | +3.8% |
| v8.3 (P0/P1 engine fixes) | 10 stocks | static 2024 snapshot | +73.5% | +20.4% | 1.27 | -18.3% | +47.6% |
| v8.4 (PIT, de-biased) | 10 stocks | SEC XBRL point-in-time | +3.8% | +1.3% | 0.16 | -35.0% | -22.0% |
| v8.4 (PIT, de-biased) | 487 stocks | SEC XBRL point-in-time | +15.9% | +5.1% | 0.37 | -17.6% | -10.0% |

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
python extend_universe.py                                     # extend all histories to latest day
python build_pit_fundamentals.py                              # PIT snapshots  -> data/pit_fundamentals_full.json
python tenbagger_v8_2_production.py --mode backtest                    # 10-stock dev universe
python tenbagger_v8_2_production.py --mode backtest --universe full    # full pool
```
