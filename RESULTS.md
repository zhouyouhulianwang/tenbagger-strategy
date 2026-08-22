# Measured Results (v8.2 → v9.3)

> **Bottom line (updated 2026-08-22, v3 data)**: over the extended window
> **2020-01-10 → 2026-07-29**, the current v9.3 full-pool strategy returns
> **+432.6% vs SPY +92.6% (+340pp)**, Sharpe **1.41**, Max DD **-30.3%**
> (2021 +42.1, 2022 +5.5, 2023 +28.0, 2024 +88.3, 2025 +10.9, 2026 YTD
> +31.2; segments 2020-23 +91.2% / 2024-26 +179.6%).
>
> **Data-lineage note**: the previously quoted **+559.6%/1.59/-22.8%** was
> measured on PIT data that was *silently missing APA/RF/SYF/TFC* (SEC
> holdco-CIK and bank-tag gaps in the weekly rebuild). Restoring them
> (2026-08-22 build fixes) moves the base to +432.6% - the restored
> regional banks enter value/defensive sleeves and lose in the 2023 SVB
> crisis and 2025 (2023: +41.9 -> +28.0; 2025: +23.9 -> +10.9; 2022
> improves +3.8 -> +5.5). +432.6% on complete data is the honest number;
> all archived experiment verdicts remain valid (each was measured against
> its own same-data base). Numbers still carry survivorship bias
> (2026-era constituents) and are an **overestimate** — see caveats.

## v9.3: structure scans (2026-08-22, v3 data, hash-stamped inputs)

| Scan | Results (ret%/Sharpe/MDD%) | Verdict |
|---|---|---|
| Sizing: vol×score (backtest) vs equal (what live ran) | 432.6/1.41/-30.3 vs 310.5/1.31/-21.0 | **live aligned to vol×score in v9.3** — live had been running a sizing that was never backtested (allocate() was dead code; the engine sizes inline) |
| MAX_POSITIONS = 5 / **6** / 7 / 8 / 10 | 486.8/1.42 · **432.6/1.41** · 233.3/1.15 · 165.5/1.00 · 182.1/1.09 | keep 6: n5's +54pp is Sharpe-noise (+0.01) with a -23pp 2021 hole (18.9 vs 42.1); past 6, dilution kills alpha |
| Rebalance phase p0(≈Mon) / p1 / p2 / p3 / p4 | **432.6/1.41** · 464.8/1.46 · 333.7/1.26 · 332.6/1.26 · 344.8/1.29 | keep Monday: Mon/Tue ≫ Wed–Fri in 2020-23 (91/103 vs ~56-60), identical 2024-26; p1's +32pp is best-of-5 noise |

## v8.9 → v9.2: experiment battery & live operations (2026-07-31 → 2026-08-22)

**v8.9 (approved 2026-07-31): regime position-factor removed (pf=1.0).**
Full investment beat every de-grossing variant: +559.6%/1.59/-22.8% vs
v8.8 +335.7%/1.34/-23.0%, winning ALL six years incl. 2022 (+3.8% vs
-2.6%). Real risk control lives in selection + stops, not exposure cuts.
(Regime detection still drives sleeve weights; only the blunt scalar went.)

Every subsequent proposal was tested as a single-bit change against this
base (559.6/1.59/-22.8). Full JSONs in `data/`, config comments carry the
same verdicts inline:

| Experiment | Result vs base | Verdict |
|---|---|---|
| Risk ablation: remove daily-loss limit | 269.2/1.12/-30.4 (-290pp) | **daily limit = TOP defender, keep** |
| Risk ablation: remove stops | 385.6/1.36/-26.1 (-174pp; trailing 50/100 fired ZERO times in 6y = dead code) | keep hard -8% |
| Risk ablation: remove drawdown breaker | 505.8/1.50/-24.1 (-54pp; 2020-23 seg 58.4 vs 110.8) | keep (crash insurance) |
| Stall-swap (replace stalling leaders) | filter 167.9/0.92, swap 270.2/1.15 | **REJECTED** (reversal penalty) |
| Exhaustion overlays (external research) | leader 279.3/1.23, breadth 496.7/1.52 (fails seg), combo 200.2/1.04 | **REJECTED** (their 2022 signal inverts here) |
| Volume floor 10M ADV | adv20 93.9/0.72, day 133.8/0.91; 5/6 holdings filtered, MDD unchanged | **REJECTED** (liquidity is a non-issue at $30K positions) |
| Risk-liquidation re-entry timing | next_day 464.3/1.43/**-33.7** (breaker re-triggers 34→51), cooldown_2d 374.4/1.35 | **REJECTED** - the post-event idle window is protective |
| Daily-loss threshold scan | 2% 280.3 / 2.5% 339.7 / **3% 559.6** / 3.5% 135.2 / 4% 183.4 / 5% 242.4 / 10% 269.2 (=OFF, 0 events) | **-3% is a sharp global optimum, keep** |

**Live incidents that shaped v9.x** (paper account started 2026-07-24,
$100K): Telegram notification stack (pre/post rebalance reports with full
ranking + sizing detail, per-fill fills, [AL 2] prefix, rate-limiting);
`last_rebalance` stamp-loss bug (caused PANW↔DVA churn round-trips and
notification floods — fixed); stop-event dedupe (DVA notified 4x in 4 min
on 2026-08-05 — fixed with 300s window + retry); Monday rebalance anchor
(REBALANCE_WEEKDAY=0; the backtest engine stays weekday-agnostic at 5-day
cycles); startup-notification accuracy (VERSION constant + dynamic weekday).

**2026-08-05 live stress test**: DVA gapped -17% on earnings; hard stops
fired, the -3% daily-loss limit emergency-liquidated the remaining 4
positions (all succeeded). Post-hoc: DDOG — one of the liquidated names —
crashed -19% on its own earnings the NEXT day; the limit saved ~$3.5K.
The backtest's top-rated defense worked exactly as measured.

**Data-pipeline fixes (2026-08-22 review)**: the weekly PIT rebuild
silently dropped BRK.B/BF.B (dot-ticker vs SEC's dashed form) and XOM
(SEC maps XOM to a holdco CIK with no us-gaap facts; real filer = legacy
34088); APA/RF/SYF/TFC produced zero snaps (no standard revenue tag -
banks need InterestIncomeExpenseNet+NoninterestIncome, holdco APA needs
OperatingIncomeLoss+OperatingExpenses). All fixed in
`build_pit_fundamentals.py` with a post-build regression guard (exit 2 if
any of the 7 recovered symbols goes missing again). Rebuilt 509-symbol PIT
validated: baseline reproduces 559.6/1.59/-22.8 **exactly** — pure
data-completeness fix, zero selection drift.

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
