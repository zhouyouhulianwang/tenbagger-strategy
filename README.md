# Tenbagger Strategy v8.2

> **Status**: Active on Alpaca Paper Trading (Account: paper trading 2) for simulation and validation.

Multi-factor quantitative trading system with real-time conditional hedge, 520-stock universe (S&P 500 + NASDAQ 100), and six-layer risk defense.

---

## Live Status

| Item | Detail |
|------|--------|
| **Account** | Alpaca Paper Trading (paper trading 2) |
| **Mode** | Paper Trading with intraday monitoring |
| **Universe** | 520 stocks (S&P 500 + NASDAQ 100) |
| **Hedge** | SQQQ 10% conditional (VIX >= 25) |
| **Status** | Running |

---

## Strategy Architecture

### Six-Layer Risk Defense

```
Layer 1: Trailing stop -20% (individual stock crash)
Layer 2: Rank hysteresis 22 (relative weakness)
Layer 3: Absolute momentum filter (negative trend)
Layer 4: VIX five-tier overlay (panic de-risking)
Layer 5: SQQQ conditional hedge (panic reverse profit)
Layer 6: Intraday VIX escalation immediate trim (minute-level)
```

### Conditional Hedge (Real-Time Intraday)

```
VIX >= 25.0   -> ACTIVATE:  Buy SQQQ 10% market order
VIX <= 24.75  -> DEACTIVATE: Sell all SQQQ market order
24.75 < VIX < 25 -> HOLD: Narrow hysteresis band (no action)
Switches > 2/day -> CIRCUIT BROKEN: No more switches today
```

**Research**: Permanent hedge costs 9%/year; conditional hedge (VIX>=25) delivers Sharpe 2.56, max drawdown -23.2%, 2022 bear market +29.8% vs +13.3% baseline.

### Five Sub-Strategies with Dynamic Weighting

| Strategy | Signal Type |
|----------|-------------|
| Momentum | Multi-period weighted momentum + RS rating |
| Sector Rotation | Industry momentum ranking + acceleration |
| Growth | CANSLIM-inspired growth stock selection |
| Value | Low PE/PB + high dividend + mean reversion |
| Defensive | Low volatility + defensive sectors |

Regime-based dynamic weights: BULL / NEUTRAL / BEAR / PANIC.

### DCL Execution Discipline

```
Data    -> Refresh latest prices and positions
Check   -> Generate stop-loss / risk control signals
Signal  -> Generate stock selection signals (5 strategies)
Order   -> Execute trades ONLY after signal confirmation
```

---

## Key Fixes (v8.1 -> v8.2)

### Critical Bugs

| Bug | Impact | Fix |
|-----|--------|-----|
| RiskCtrl division-by-zero | Daily loss limit completely failed | `_last_equity=None` instead of `0` |
| Trailing stop 100% unreachable | High-profit stock protection missing | Independent `if` with priority ordering |
| net_price missing SEC/FINRA | Undercounted ~0.2bp per sell | Include all fees in `net_price` |
| Entry price uses signal price | Delayed stop trigger, extra loss | `entry_price = net_price` |

### 10 High Priority Fixes

- `getattr` anti-pattern -> instance variable
- `emergency_liquidate` checks return value
- `trade_logger` raw JSON Lines format
- `do_rebalance` uses `Config.UNIVERSE` (not hardcoded)
- WalkForwardValidator with parameter optimization
- MacroTiming data length checks
- PortfolioConstructor removes unused parameter
- SecureConfig uses Fernet (AES-128-CBC + HMAC)
- `cancel_our_orders()` with prefix filter
- Benchmark calculation uses dynamic period

---

## Usage

### Setup API Keys

```bash
python tenbagger_v8_2_production.py --mode setup
# Enter: API Key, Secret Key, encryption password
```

Or use environment variables:

```bash
export ALPACA_API_KEY="PK..."
export ALPACA_SECRET_KEY="..."
```

### Paper Trading (Intraday Monitor)

```bash
python tenbagger_v8_2_production.py --mode paper
```

Features:
- 60-second cycle: data refresh -> risk check -> hedge check -> stop check -> report
- Weekly rebalancing (Fridays, when market is closed to avoid intraday disruption)
- Real-time conditional hedge (VIX-triggered)
- Automatic stop-loss execution
- Daily loss limit (-3%) and max drawdown circuit breaker (-10%)

### Backtest

```bash
python tenbagger_v8_2_production.py --mode backtest --start 2019-01-01 --end 2024-01-01 --plot
```

### Walk-Forward Validation

```bash
python tenbagger_v8_2_production.py --mode walkforward
```

### Signal Only

```bash
python tenbagger_v8_2_production.py --mode signal
```

---

## Configuration

Key parameters in `Config` dataclass:

```python
# Hedge
ENABLE_HEDGE = True
HEDGE_VIX_ACTIVATE = 25.0        # VIX >= 25: activate hedge
HEDGE_VIX_DEACTIVATE = 24.75     # VIX <= 24.75: deactivate (narrow hysteresis)
HEDGE_POSITION_PCT = 0.10        # 10% SQQQ allocation
HEDGE_MAX_SWITCHES_PER_DAY = 2   # Circuit breaker: max 2 switches/day

# Risk
DAILY_LOSS_LIMIT_PCT = -0.03     # Stop trading if -3% today
MAX_DRAWDOWN_LIMIT_PCT = -0.10   # Circuit breaker at -10%
HARD_STOP_LOSS_PCT = -0.08       # Individual stock -8% stop

# Position
MAX_POSITIONS = 6
MAX_SINGLE_POSITION_PCT = 0.30
REBALANCE_DAYS = 5                # Weekly

# Universe (520 stocks)
UNIVERSE = [...]  # S&P 500 + NASDAQ 100 + SPY
```

---

## File Structure

```
tenbagger-strategy/
|-- tenbagger_v8_2_production.py   # Main system (2616 lines)
|-- config.json                     # Optional: override Config
|-- state.json                      # Runtime state (positions, entry prices)
|-- data/                           # Cache directory
|   |-- .keys                       # Encrypted API keys
|   |-- fundamentals_v82.json       # Fundamentals cache
|-- logs/
|   |-- trading.log                 # Detailed debug log
|   |-- paper_trading.log           # Monitor output
|   |-- trades.jsonl                # Structured trade records
|   |-- errors.log                  # Errors and warnings
|-- README.md                       # This file
```

---

## License

MIT

---

## Disclaimer

This software is for educational and research purposes only. Past performance does not guarantee future results. Trading involves substantial risk of loss. The authors assume no liability for trading losses incurred using this system.
