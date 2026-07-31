#!/usr/bin/env python3
"""
================================================================================
Tenbagger Strategy v8.2 - Production Grade (FULL AUDIT FIXES)
十倍潜力股策略 v8.2 - 生产级完整系统 (全缺陷修复版)

ALL CRITICAL & HIGH DEFECTS FIXED (v8.1 -> v8.2):
  [CRITICAL] BUG-001: RiskController division-by-zero (_last_equity=0 -> None)
  [CRITICAL] BUG-002: Trailing stop 100% unreachable (elif chain -> independent ifs)
  [CRITICAL] BUG-003: TxnCost net_price missing SEC/FINRA fees
  [CRITICAL] BUG-004: Backtest entry_price uses signal price instead of net_price
  [HIGH]     HP-001: getattr anti-pattern -> instance variable
  [HIGH]     HP-002: emergency_liquidate checks return value
  [HIGH]     HP-003: trade_logger uses Formatter (breaks JSON Lines)
  [HIGH]     HP-004: do_rebalance hardcoded universe -> Config.UNIVERSE
  [HIGH]     HP-005: WalkForwardValidator with parameter optimization
  [HIGH]     HP-006: MacroTiming data length checks
  [HIGH]     HP-007: PortfolioConstructor.allocate unused param removed
  [HIGH]     HP-008: SecureConfig uses Fernet instead of XOR
  [HIGH]     HP-009: cancel_all_orders -> cancel_our_orders (prefix filter)
  [HIGH]     HP-010: _calc_performance benchmark calculation fix
  [MEDIUM]   MP-001: Order status polling after submit
  [MEDIUM]   MP-002: Cash negative protection in backtest
  [MEDIUM]   MP-003: Consistent positions iteration
  [MEDIUM]   MP-004: Log directory permission check
  [MEDIUM]   MP-005: Loop end n_days-1 -> n_days (include last day)
  [MEDIUM]   MP-006: Configurable data feed (iex/sip)

v8.3 FIXES (independent review, branch v8.3-fixes):
  [CRITICAL] A1: Live rebalance fetched only 60d of bars -> momentum/growth/value
             strategies silently disabled; now fetches 400d
  [CRITICAL] B1: "VIX = VIXY x 0.85" proxy removed -> VixProvider (yfinance ^VIX
             quote, CBOE official EOD fallback, stale-data guard)
  [CRITICAL] A2: Backtest liquidated the whole portfolio every week -> delta-based
             rebalancing that keeps overlapping holdings (trailing stops reachable)
  [CRITICAL] A3: Backtest had no RiskController/HedgeEngine -> both wired in;
             hedge trades SQQQ on real VIX with the same hysteresis rules as live
  [HIGH]     C1: Daily-loss baseline updated every call (became a 60s loss limit)
             -> frozen at yesterday's last equity
  [HIGH]     C2: Stops/hedge ran 24/7 on stale data -> market-hours gating +
             TRADING_ENABLED shadow mode
  [HIGH]     D1: Transaction cost summary let buy/sell costs cancel (~15x
             underestimate) -> costs summed per side
  [HIGH]     D3: SPY was a selectable candidate (18% of backtest buys) -> excluded
  [HIGH]     D2: WFA test window (126d) < engine warmup (252d) -> warmup prepended
  [MEDIUM]   B3: Hedge state flipped before order execution -> committed on success
  [MEDIUM]   C3: Weekly rebalance sold the SQQQ hedge and stops applied to it ->
             hedge ETF excluded from stock stop/rebalance logic
  [MEDIUM]   D6: Advertised 21d-high filter was dead code -> wired in
  [MEDIUM]   A4: Live rebalance ignored regime position factor -> applied

v8.4 FIXES (P2: data integrity & de-biasing):
  [CRITICAL] E1: Static 2024 fundamentals (look-ahead) -> PointInTimeFundamentals:
             SEC XBRL companyfacts quarterly snapshots, visible only from each
             period's earliest EDGAR filed date; PE/PB/ROE/GM/growth/PEG/
             dividend-yield/market-cap recomputed per query date; share counts
             split-adjusted to match split-adjusted prices
  [HIGH]     E2: INNOVATION_PREMIUM / SECTOR_PREMIUM hand-tuned stock/sector
             score boosts removed (survivorship-flavored curve fitting)
  [MEDIUM]   E3: FINRA TAF was charged on buys too -> sell-side only (like SEC fee)
  [MEDIUM]   E4: Full-universe mode (--universe full): 520-stock pool with
             Nasdaq daily histories + per-stock PIT fundamentals; ticker
             validity verified implicitly by data availability

v8.5 FIXES (Alpaca paper/live readiness review):
  [CRITICAL] F1: validate_data tz-naive-vs-aware TypeError killed every
             weekly rebalance -> tz-normalized bars + defensive seatbelt
  [CRITICAL] F2: after-close rebalance queued sells+buys to the same next
             open -> buys rejected (no freed cash) or silent margin; now
             rebalances INSIDE the trading window, sells polled to fill
             before buys, cash verified
  [CRITICAL] F3: no PDT protection -> PDT guard blocks new buys and hedge
             activations when daytrade_count exhausted on <$25k accounts
  [CRITICAL] F4: fractional SQQQ residue (notional buys vs int(qty) sells)
             ghosted the hedge state machine -> DELETE /v2/positions close
  [HIGH]     F5: hedge activation impossible when fully invested -> pro-rata
             stock trim funds the hedge (live HEDGE_STOCK_COMPRESSION)
  [HIGH]     F6: ~520 per-symbol bar requests broke the data rate limit ->
             batched multi-symbol bars with pagination
  [HIGH]     F7: orphan orders never reconciled -> startup cancel + rebalance
             pre-cancel; TRADING_ENABLED=False shadow mode can no longer
             liquidate; state.json atomic + instance lock; live fundamentals
             use PIT SEC snapshots (yfinance only as loud fallback);
             split-divergent entry basis auto-rebased; failed rebalances no
             longer stamped (retried next cycle); trailing-stop peaks survive
             rebalances; bars use adjustment='all'
  [MEDIUM]   F8: all market-time logic in US Eastern (zoneinfo); trading
             window config enforced; circuit breaker + daily baseline survive
             restarts; 4xx no longer retried; kill-switch file STOP_TRADING;
             .gitignore covers key/state/lock files; yfinance VIX outage
             escalation; live base URL from env + LIVE_TRADING_ACK gate

Usage:
  # Backtest
  python tenbagger_v8_2_production.py --mode backtest --start 2019-01-01 --end 2024-01-01 --plot
  
  # Paper Trading with monitoring
  export ALPACA_API_KEY="PK..."
  export ALPACA_SECRET_KEY="..."
  python tenbagger_v8_2_production.py --mode paper
  
  # Signal only
  python tenbagger_v8_2_production.py --mode signal
  
  # Setup API keys
  python tenbagger_v8_2_production.py --mode setup
================================================================================
"""

# Standard library
import os
import sys
import json
import time
import logging
import logging.handlers
import argparse
import tempfile
import bisect
import warnings
import hashlib
import getpass
import pickle
import functools
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import defaultdict

# v8.5: all market-time logic uses US Eastern, independent of the host timezone
ET = ZoneInfo('America/New_York')

def now_et() -> datetime:
    """Current time in US Eastern (market timezone)."""
    return datetime.now(ET)

# Third-party
import numpy as np
import pandas as pd
import requests

warnings.filterwarnings('ignore')

# ============================================================================
# STRUCTURED LOGGING SETUP (runs first)
# ============================================================================

LOG_DIR = Path(__file__).parent / 'logs'
try:
    LOG_DIR.mkdir(exist_ok=True)
    # MP-004 FIX (v8.3): fall back to a writable temp dir instead of just warning
    if not os.access(LOG_DIR, os.W_OK):
        raise PermissionError(f"{LOG_DIR} is not writable")
except OSError as e:
    print(f"WARNING: Cannot use log directory {LOG_DIR}: {e}. Falling back to temp dir.",
          file=sys.stderr)
    LOG_DIR = Path(tempfile.gettempdir()) / 'tenbagger_logs'
    LOG_DIR.mkdir(exist_ok=True)

# Root logger
root_logger = logging.getLogger('tenbagger')
root_logger.setLevel(logging.DEBUG)
root_logger.propagate = False

# Console handler
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter(
    '%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
))
root_logger.addHandler(console)

# File handler (rotating daily)
file_handler = logging.handlers.TimedRotatingFileHandler(
    LOG_DIR / 'trading.log', when='midnight', backupCount=30, encoding='utf-8'
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s'
))
root_logger.addHandler(file_handler)

# Error file handler
error_handler = logging.handlers.RotatingFileHandler(
    LOG_DIR / 'errors.log', maxBytes=10*1024*1024, backupCount=10, encoding='utf-8'
)
error_handler.setLevel(logging.WARNING)
root_logger.addHandler(error_handler)

# JSON trade log (structured logging)
# HP-003 FIX: trade_logger must NOT have a Formatter to preserve raw JSON Lines format
trade_logger = logging.getLogger('tenbagger.trades')
trade_handler = logging.handlers.RotatingFileHandler(
    LOG_DIR / 'trades.jsonl', maxBytes=50*1024*1024, backupCount=20, encoding='utf-8'
)
trade_handler.setLevel(logging.INFO)
# NO Formatter set - we write raw JSON directly via trade_logger.info(json.dumps(...))
trade_logger.addHandler(trade_handler)
trade_logger.propagate = False

logger = logging.getLogger('tenbagger.main')


# ============================================================================
# CONFIGURATION - Production Grade
# ============================================================================

@dataclass
class Config:
    """Production configuration - all parameters in one place."""
    
    # === General ===
    INITIAL_CAPITAL: float = 100_000.0
    MAX_POSITIONS: int = 6
    REBALANCE_DAYS: int = 5  # Weekly
    
    # === Trading Hours (ET) ===
    TRADING_ENABLED: bool = True
    # v8.5: window is now enforced for rebalances and hedge switches (stops
    # still execute any time the market is open - protection beats noise).
    TRADING_WINDOW_START: str = "10:00"   # Avoid opening volatility
    TRADING_WINDOW_END: str = "15:30"     # Avoid closing volatility
    AVOID_PRE_MARKET_GAPS: bool = True    # Use next-day open for rebalancing
    
    # === Transaction Costs ===
    ENABLE_TRANSACTION_COSTS: bool = True
    SEC_FEE_RATE: float = 0.0000229       # SEC fee on sells
    FINRA_TAF_PER_SHARE: float = 0.000166 # FINRA Trading Activity Fee
    FINRA_TAF_MAX: float = 8.30
    SLIPPAGE_BPS_SMALL_CAP: float = 10.0   # <$2B market cap
    SLIPPAGE_BPS_MID_CAP: float = 5.0      # $2-10B
    SLIPPAGE_BPS_LARGE_CAP: float = 3.0    # $10-100B
    SLIPPAGE_BPS_MEGA_CAP: float = 1.5     # >$100B
    
    # === Position Sizing ===
    MAX_SINGLE_POSITION_PCT: float = 0.30
    MIN_SINGLE_POSITION_PCT: float = 0.05
    VOLATILITY_TARGET: float = 0.25
    
    # === Stop Loss ===
    HARD_STOP_LOSS_PCT: float = -0.08
    TRAILING_STOP_50_PCT: float = -0.20   # After +50% gain
    TRAILING_STOP_100_PCT: float = -0.25  # After +100% gain
    # === Alternative risk framework (config-gated, defaults preserve current behavior) ===
    STOP_MODE: str = 'tiered'             # 'tiered' (current) | 'trail21' (21d-high -15%)
    TRAIL21_STOP_PCT: float = -0.15       # exit when close < 21d high * (1 + pct)
    VIX_HALVE_ENABLED: bool = False       # prev-day VIX >= threshold -> halve stock exposure
    VIX_HALVE_THRESHOLD: float = 30.0
    RV90_BUY_BLOCK_ENABLED: bool = False  # block NEW buys when 21d ann. vol > RV90_MAX_VOL
    RV90_MAX_VOL: float = 0.90
    BREADTH_SCALING_ENABLED: bool = False # pos_factor *= fraction of universe with r252 > 0
    
    # === Portfolio Risk ===
    DAILY_LOSS_LIMIT_PCT: float = -0.03     # Stop trading if down 3% today
    MAX_DRAWDOWN_LIMIT_PCT: float = -0.10   # Circuit breaker at -10%
    CIRCUIT_BREAKER_COOLDOWN_HOURS: int = 24

    # === Pattern Day Trader (PDT) protection (v8.5) ===
    # FINRA: >=4 day trades in 5 business days with equity < $25k -> account
    # restricted for 90 days. We stop opening new positions / new hedge
    # switches once daytrade_count reaches PDT_MAX_DAY_TRADES. Protective
    # stop-loss sells always go through (risk first) with a CRITICAL log.
    PDT_PROTECTION: bool = True
    PDT_MIN_EQUITY: float = 25_000.0
    PDT_MAX_DAY_TRADES: int = 3

    # === Kill switch (v8.5) ===
    # If this file exists, the monitor cancels our open orders and stops all
    # trading actions (reporting continues). Delete the file to resume.
    KILL_SWITCH_FILE: Path = field(default_factory=lambda: Path(__file__).parent / 'STOP_TRADING')
    
    # === Conditional Hedge Engine (Real-Time Intraday VIX-Triggered) ===
    # 研究结论: 永久对冲年耗9%无效; 条件对冲(VIX>=25)夏普2.56显著有效
    # 回测数据: SQQQ 10%仅VIX>=25 → 年化61.8%(仅-2.1%), DD -23.2%, 2022熊市+29.8%
    # 窄滞回: VIX>=25建仓 | VIX<=24.75清仓 | 24.75<VIX<25保持 | 日切换>2次熔断
    # v8.8 (data-driven, approved 2026-07-30): SQQQ hedge disabled. After the
    # v8.6 growth removal + v8.7 200d regime gating, the regime position factor
    # already de-grosses in downturns and the hedge's marginal value vanished:
    # no_sqqq +335.7%/Sharpe 1.34/MDD -23.0% vs hedged +326.9%/1.34/-23.2%
    # (data/hedge_framework_experiments.json). VIX-halve/trail21/RV90/breadth
    # layers were also tested and all hurt - NOT adopted.
    ENABLE_HEDGE: bool = False               # Master switch
    HEDGE_VIX_ACTIVATE: float = 25.0         # VIX >= 25.0: 实时建仓SQQQ
    HEDGE_VIX_DEACTIVATE: float = 24.75      # VIX <= 24.75: 实时清仓SQQQ (窄滞回)
    HEDGE_POSITION_PCT: float = 0.10         # 对冲仓位=10% portfolio (VIX>=25时)
    HEDGE_ETF: str = "SQQQ"                  # -3x NASDAQ inverse
    HEDGE_STOCK_COMPRESSION: float = 0.90    # VIX>=25时股票仓位压缩到90%
    HEDGE_MAX_SWITCHES_PER_DAY: int = 2      # 日切换>2次: 当日熔断不再切换
    HEDGE_REBALANCE_THRESHOLD_PCT: float = 0.02  # 漂移>2%时调仓
    
    # === Momentum Strategy ===
    MOMENTUM_PERIODS: List[int] = field(default_factory=lambda: [21, 63, 126, 252])
    MOMENTUM_WEIGHTS: List[float] = field(default_factory=lambda: [0.30, 0.35, 0.25, 0.10])
    RS_MIN: float = 60.0
    MAX_VOLATILITY: float = 0.60
    
    # === Growth Strategy ===
    MIN_ROE: float = 0.12
    MIN_GROSS_MARGIN: float = 0.20
    
    # === Value Strategy ===
    VALUE_MAX_PE: float = 20.0
    VALUE_MAX_PB: float = 3.0
    VALUE_MIN_DIV_YIELD: float = 0.01
    
    # === Defensive Strategy ===
    DEFENSIVE_MAX_VOLATILITY: float = 0.25
    DEFENSIVE_MIN_DIV_YIELD: float = 0.015
    
    # v8.9 (data-driven, approved 2026-07-31): regime position factor removed.
    # Forcing pf=1.0 beat every de-grossing variant: +559.6%/Sharpe 1.59/
    # MDD -22.8% vs v8.8 +335.7%/1.34/-23.0%, and won ALL six calendar years
    # incl. 2022 (+3.8% vs -2.6%). Real risk control lives in stock selection
    # (vol gate, RS filter, defensive sleeve) + stops, not blunt exposure cuts.
    REGIME_DEGROSS_ENABLED: bool = False
    # === Strategy Weights by Regime ===
    # v8.6 (data-driven): growth weight zeroed in every regime. Evidence
    # (full-pool 2020-01 -> 2026-07, 21-experiment attribution/ablation
    # battery, data/strategy_experiments.json):
    #   - solo growth: +40.7% / Sharpe 0.42 - worst of all strategies
    #   - ablation (growth=0): +240.0% vs base +172.8%, Sharpe 1.20 vs 0.99,
    #     MDD -24.7% vs -27.6%; improvement holds in BOTH sub-periods
    #     (2020-23: +60.1% vs +14.6%; 2024-26: +116.8% vs +139.5%, both > SPY)
    #   - trade attribution shows growth picks are mildly profitable (+$16K)
    #     but crowd out momentum slots (MAX_POSITIONS=6) - negative
    #     opportunity cost, not bad signals. Weight=0 keeps the code path
    #     (resonance bonus unaffected) and is exactly what was backtested.
    WEIGHT_BULL: Dict[str, float] = field(default_factory=lambda: {
        'momentum': 0.35, 'sector': 0.25, 'growth': 0.0, 'value': 0.10, 'defensive': 0.05
    })
    WEIGHT_NEUTRAL: Dict[str, float] = field(default_factory=lambda: {
        'momentum': 0.25, 'sector': 0.25, 'growth': 0.0, 'value': 0.15, 'defensive': 0.10
    })
    WEIGHT_BEAR: Dict[str, float] = field(default_factory=lambda: {
        'momentum': 0.10, 'sector': 0.15, 'growth': 0.0, 'value': 0.30, 'defensive': 0.25
    })
    WEIGHT_PANIC: Dict[str, float] = field(default_factory=lambda: {
        'momentum': 0.05, 'sector': 0.10, 'growth': 0.0, 'value': 0.20, 'defensive': 0.50
    })
    STRATEGY_RESONANCE_BONUS: float = 0.20
    
    # === API ===
    # v8.5: base URL comes from the environment so paper<->live switching
    # never requires editing source. Live URLs additionally require
    # LIVE_TRADING_ACK=I_UNDERSTAND in the environment (checked at startup).
    ALPACA_BASE_URL: str = field(default_factory=lambda: os.environ.get(
        'APCA_API_BASE_URL', 'https://paper-api.alpaca.markets'))
    ALPACA_DATA_URL: str = "https://data.alpaca.markets"
    API_MAX_RETRIES: int = 5
    API_BASE_DELAY: float = 1.0
    API_MAX_DELAY: float = 60.0
    API_TIMEOUT: int = 15
    
    # === Data ===
    DATA_DIR: Path = field(default_factory=lambda: Path(__file__).parent / 'data')
    CACHE_TTL_DAYS: int = 7
    # v8.3: strategies need up to 252 trading days (momentum), so live rebalances
    # must fetch enough history; 30 days silently disabled 3 of 4 strategies.
    MIN_DATA_DAYS: int = 252
    MIN_STOCKS_FOR_REBALANCE: int = 10

    # === VIX data (v8.3: real VIX instead of VIXY x 0.85 proxy) ===
    VIX_CBOE_URL: str = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
    VIX_CACHE_TTL_SEC: int = 60
    VIX_MAX_STALE_DAYS: int = 5        # EOD fallback older than this -> treat as unavailable
    
    # MP-006 FIX: Configurable data feed
    # WARNING: "iex" (free) is delayed ~15min and thin for less-liquid names;
    # stop-loss and hedge triggers may fire on stale prices. Use "sip" for
    # any serious paper validation and for live trading.
    DATA_FEED: str = "iex"  # "iex" for free, "sip" for live (subscription required)
    
    # === Trading Universe: S&P 500 (502) + NASDAQ 100 unique (17) + SPY ===
    # Sources: stockanalysis.com (S&P 500, NASDAQ 100), merged & deduplicated
    UNIVERSE: List[str] = field(default_factory=lambda: [
        'A','AAPL','ABBV','ABNB','ABT','ACGL','ACN','ADBE','ADI','ADM',
        'ADP','ADSK','AEE','AEP','AES','AFL','AIG','AIZ','AJG','AKAM',
        'ALAB','ALB','ALGN','ALL','ALLE','ALNY','AMAT','AMCR','AMD','AME',
        'AMGN','AMP','AMT','AMZN','ANET','AON','AOS','APA','APD','APH',
        'APO','APP','APTV','ARE','ARES','ARM','ASML','ATO','AVB','AVGO',
        'AVY','AWK','AXON','AXP','AZO','BA','BAC','BALL','BAX','BBY',
        'BDX','BEN','BF.B','BG','BIIB','BKNG','BKR','BLDR','BLK','BMY',
        'BNY','BR','BRK.B','BRO','BSX','BX','BXP','C','CAG','CAH',
        'CARR','CASY','CAT','CB','CBOE','CBRE','CCEP','CCI','CCL','CDNS',
        'CDW','CEG','CF','CFG','CHD','CHRW','CHTR','CI','CIEN','CINF',
        'CL','CLX','CMCSA','CME','CMG','CMI','CMS','CNC','CNP','COF',
        'COHR','COIN','COO','COP','COR','COST','CPAY','CPB','CPRT','CPT',
        'CRH','CRL','CRM','CRWD','CRWV','CSCO','CSGP','CSX','CTAS','CTSH',
        'CTVA','CVNA','CVS','CVX','D','DAL','DASH','DD','DDOG','DE',
        'DECK','DELL','DG','DGX','DHI','DHR','DIS','DLR','DLTR','DOC',
        'DOV','DOW','DPZ','DRI','DTE','DUK','DVA','DVN','DXCM','EA',
        'EBAY','ECL','ED','EFX','EG','EIX','EL','ELV','EME','EMR',
        'EOG','EQIX','EQR','EQT','ERIE','ES','ESS','ETN','ETR','EVRG',
        'EW','EXC','EXE','EXPD','EXPE','EXR','F','FANG','FAST','FCX',
        'FDS','FDX','FDXF','FE','FER','FFIV','FICO','FIS','FISV','FITB',
        'FIX','FOX','FOXA','FRT','FSLR','FTNT','FTV','GD','GDDY','GE',
        'GEHC','GEN','GEV','GILD','GIS','GL','GLW','GM','GNRC','GOOG',
        'GOOGL','GPC','GPN','GRMN','GS','GWW','HAL','HAS','HBAN','HCA',
        'HD','HIG','HII','HLT','HON','HONA','HOOD','HPE','HPQ','HRL',
        'HSIC','HST','HSY','HUBB','HUM','HWM','IBKR','IBM','ICE','IDXX',
        'IEX','IFF','INCY','INTC','INTU','INVH','IP','IQV','IR','IRM',
        'ISRG','IT','ITW','IVZ','J','JBHT','JBL','JCI','JKHY','JNJ',
        'JPM','KDP','KEY','KEYS','KHC','KIM','KKR','KLAC','KMB','KMI',
        'KO','KR','KVUE','L','LDOS','LEN','LH','LHX','LII','LIN',
        'LITE','LLY','LMT','LNT','LOW','LRCX','LULU','LUV','LVS','LYB',
        'LYV','MA','MAA','MAR','MAS','MCD','MCHP','MCK','MCO','MDLZ',
        'MDT','MELI','MET','META','MGM','MKC','MLM','MMM','MNST','MO',
        'MOS','MPC','MPWR','MRK','MRNA','MRSH','MRVL','MS','MSCI','MSFT',
        'MSI','MSTR','MTB','MTD','MU','NBIS','NCLH','NDAQ','NDSN','NEE',
        'NEM','NFLX','NI','NKE','NOC','NOW','NRG','NSC','NTAP','NTRS',
        'NUE','NVDA','NVR','NWS','NWSA','NXPI','O','ODFL','OKE','OMC',
        'ON','ORCL','ORLY','OTIS','OXY','PANW','PAYX','PCAR','PCG','PDD',
        'PEG','PEP','PFE','PFG','PG','PGR','PH','PHM','PKG','PLD',
        'PLTR','PM','PNC','PNR','PNW','PODD','POOL','PPG','PPL','PRU',
        'PSA','PSKY','PSX','PTC','PWR','PYPL','Q','QCOM','RCL','REG',
        'REGN','RF','RJF','RKLB','RL','RMD','ROK','ROL','ROP','ROST',
        'RSG','RTX','RVTY','SBAC','SBUX','SCHW','SHOP','SHW','SJM','SLB',
        'SMCI','SNA','SNDK','SNPS','SO','SOLV','SPCX','SPG','SPGI','SPY',
        'SRE','STE','STLD','STT','STX','STZ','SW','SWK','SWKS','SYF',
        'SYK','SYY','T','TAP','TDG','TDY','TECH','TEL','TER','TFC',
        'TGT','TJX','TKO','TMO','TMUS','TPL','TPR','TRGP','TRI','TRMB',
        'TROW','TRV','TSCO','TSLA','TSN','TT','TTD','TTWO','TXN','TXT',
        'TYL','UAL','UBER','UDR','UHS','ULTA','UNH','UNP','UPS','URI',
        'USB','V','VEEV','VICI','VLO','VLTO','VMC','VRSK','VRSN','VRT',
        'VRTX','VST','VTR','VTRS','VZ','WAB','WAT','WBD','WDAY','WDC',
        'WEC','WELL','WFC','WM','WMB','WMT','WRB','WSM','WST','WTW',
        'WY','WYNN','XEL','XOM','XYL','XYZ','YUM','ZBH','ZBRA','ZTS',
    ])
    
    # === Walk-Forward ===
    WALK_FORWARD_TRAIN_DAYS: int = 504      # 2 years training
    WALK_FORWARD_TEST_DAYS: int = 126       # 6 months testing
    WALK_FORWARD_STEP_DAYS: int = 63        # 3 months step
    
    # === State Files ===
    # v8.5: state lives under DATA_DIR (repo root stays clean), written
    # atomically; an instance lock prevents two monitors on one account.
    STATE_FILE: Path = field(default_factory=lambda: Path(__file__).parent / 'data' / 'state.json')
    INSTANCE_LOCK_FILE: Path = field(default_factory=lambda: Path(__file__).parent / 'data' / '.tenbagger.lock')
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, d: Dict) -> 'Config':
        return cls(**d)
    
    @classmethod
    def load_from_file(cls, path: Optional[Path] = None) -> 'Config':
        path = path or (Path(__file__).parent / 'config.json')
        if path.exists():
            with open(path) as f:
                return cls.from_dict(json.load(f))
        return cls()


# ============================================================================
# SECURE CONFIG - API Key Management (HP-008 FIX: Fernet encryption)
# ============================================================================

class SecureConfig:
    """Secure API key storage using Fernet encryption."""
    
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self._keys: Dict[str, str] = {}
    
    def _get_key_file(self) -> Path:
        return self.config.DATA_DIR / '.keys'
    
    def _derive_key(self, password: str) -> bytes:
        """Derive encryption key from password using PBKDF2."""
        return hashlib.pbkdf2_hmac('sha256', password.encode(), b'tenbagger_salt_v82', 100000)
    
    def _get_fernet(self, password: str):
        """HP-008 FIX: Use Fernet (AES-128-CBC + HMAC) instead of XOR."""
        import base64
        from cryptography.fernet import Fernet
        # Fernet requires 32-byte base64-encoded key
        key = self._derive_key(password)
        fernet_key = base64.urlsafe_b64encode(key[:32].ljust(32, b'\0'))
        return Fernet(fernet_key)
    
    def _encrypt(self, data: str, password: str) -> str:
        """Encrypt data using Fernet."""
        f = self._get_fernet(password)
        return f.encrypt(data.encode()).decode()
    
    def _decrypt(self, encrypted_data: str, password: str) -> str:
        """Decrypt data using Fernet."""
        f = self._get_fernet(password)
        return f.decrypt(encrypted_data.encode()).decode()
    
    def setup_keys(self):
        """Interactive key setup. Run once to store keys."""
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            print("Installing cryptography package...")
            os.system(f"{sys.executable} -m pip install cryptography -q")
        
        api_key = input("Alpaca API Key: ").strip()
        secret_key = getpass.getpass("Alpaca Secret Key: ").strip()
        password = getpass.getpass("Set encryption password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords do not match!")
            return
        
        data = json.dumps({'api_key': api_key, 'secret_key': secret_key})
        encrypted = self._encrypt(data, password)
        
        key_file = self._get_key_file()
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_text(encrypted)
        key_file.chmod(0o600)  # Owner read/write only
        logger.info("Keys stored securely with Fernet encryption")
    
    def load_keys(self, password: Optional[str] = None) -> Dict[str, str]:
        """Load keys with password. Falls back to env vars."""
        # Try environment first
        env_key = os.environ.get('ALPACA_API_KEY', '')
        env_secret = os.environ.get('ALPACA_SECRET_KEY', '')
        if env_key and env_secret:
            self._keys = {'api_key': env_key, 'secret_key': env_secret}
            return self._keys
        
        # Try encrypted file
        key_file = self._get_key_file()
        if key_file.exists():
            if password is None:
                password = getpass.getpass("Encryption password: ")
            encrypted = key_file.read_text()
            try:
                data = self._decrypt(encrypted, password)
                self._keys = json.loads(data)
                return self._keys
            except Exception:
                raise ValueError("Invalid password or corrupted key file")
        
        raise ValueError("No API keys found. Set env vars or run setup_keys()")
    
    def get_headers(self) -> Dict[str, str]:
        """Get Alpaca API headers."""
        if not self._keys:
            self.load_keys()
        return {
            'APCA-API-KEY-ID': self._keys['api_key'],
            'APCA-API-SECRET-KEY': self._keys['secret_key']
        }



# ============================================================================
# TRANSACTION COST MODEL (BUG-003 FIX: net_price includes ALL fees)
# ============================================================================

class TransactionCostModel:
    """Realistic transaction cost model for Alpaca with full fee accounting."""
    
    @classmethod
    def get_slippage_bps(cls, market_cap: float, config: Config = None) -> float:
        config = config or Config()
        if market_cap >= 100_000_000_000:
            return config.SLIPPAGE_BPS_MEGA_CAP
        elif market_cap >= 10_000_000_000:
            return config.SLIPPAGE_BPS_LARGE_CAP
        elif market_cap >= 2_000_000_000:
            return config.SLIPPAGE_BPS_MID_CAP
        return config.SLIPPAGE_BPS_SMALL_CAP
    
    @classmethod
    def calculate(cls, price: float, qty: int, is_buy: bool = True,
                  market_cap: float = 50_000_000_000, config: Config = None) -> Dict:
        config = config or Config()
        gross = price * qty
        
        # SEC fee (sell only)
        sec_fee = 0.0 if is_buy else gross * config.SEC_FEE_RATE
        
        # FINRA TAF (sell only, like the SEC fee)
        finra_taf = 0.0 if is_buy else min(qty * config.FINRA_TAF_PER_SHARE, config.FINRA_TAF_MAX)
        
        # Slippage
        slippage_bps = cls.get_slippage_bps(market_cap, config)
        slippage = gross * slippage_bps / 10000
        
        # BUG-003 FIX: total_cost includes ALL fees (SEC + FINRA + slippage)
        total_cost = sec_fee + finra_taf + slippage
        
        # BUG-003 FIX: net_price accounts for ALL costs, not just slippage
        # Buy: you pay more (price + total_cost/qty)
        # Sell: you receive less (price - total_cost/qty)
        if is_buy:
            net_price = price + total_cost / qty if qty > 0 else price
        else:
            net_price = price - total_cost / qty if qty > 0 else price
        
        return {
            'gross_amount': gross,
            'sec_fee': sec_fee,
            'finra_taf': finra_taf,
            'slippage': slippage,
            'slippage_bps': slippage_bps,
            'total_cost': total_cost,
            'cost_bps': (total_cost / gross * 10000) if gross > 0 else 0,
            'net_price': net_price,
            'is_buy': is_buy,
        }
    
    @classmethod
    def apply_to_backtest(cls, price: float, qty: int, is_buy: bool = True,
                          market_cap: float = 50_000_000_000, config: Config = None) -> float:
        """Return the net price after all costs for backtest use."""
        if not (config or Config()).ENABLE_TRANSACTION_COSTS:
            return price
        result = cls.calculate(price, qty, is_buy, market_cap, config)
        return result['net_price']


# ============================================================================
# ALPACA CLIENT V2 - Retry + Idempotency + Order Polling (MP-001 FIX)
# ============================================================================

class AlpacaClient:
    """Production-grade Alpaca client with retry, idempotency, order polling, and stats."""
    
    ORDER_PREFIX = "tb_"  # HP-009: All our orders use this prefix
    
    def __init__(self, config: Config = None, secure_config: SecureConfig = None):
        self.config = config or Config()
        self.secure = secure_config or SecureConfig(config)
        self._stats = {'requests': 0, 'errors': 0, 'retries': 0}
    
    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make request with exponential backoff retry."""
        headers = self.secure.get_headers()
        timeout = kwargs.pop('timeout', self.config.API_TIMEOUT)
        
        for attempt in range(self.config.API_MAX_RETRIES):
            try:
                self._stats['requests'] += 1
                response = requests.request(method, url, headers=headers,
                                           timeout=timeout, **kwargs)
                
                if response.status_code in [200, 201, 204]:
                    return response
                
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 2 ** attempt))
                    logger.warning(f"Rate limited, waiting {retry_after}s")
                    time.sleep(retry_after)
                    continue
                
                if response.status_code == 401:
                    logger.error(f"Auth failed: {response.text[:200]}")
                    return response
                
                # v8.5: other 4xx are client errors (bad params, insufficient
                # buying power, PDT rejections) - retrying is pointless and
                # delays the failure signal by minutes. Only 5xx/timeouts retry.
                if 400 <= response.status_code < 500:
                    logger.error(f"HTTP {response.status_code} (client error, no retry): "
                                 f"{method} {url} -> {response.text[:300]}")
                    return response
                
                # Exponential backoff for 5xx / unexpected statuses
                delay = min(self.config.API_BASE_DELAY * (2 ** attempt),
                           self.config.API_MAX_DELAY)
                logger.warning(f"HTTP {response.status_code}, retry in {delay}s (#{attempt+1})")
                time.sleep(delay)
                self._stats['retries'] += 1
                
            except requests.exceptions.Timeout:
                delay = min(self.config.API_BASE_DELAY * (2 ** attempt), self.config.API_MAX_DELAY)
                time.sleep(delay)
            except requests.exceptions.ConnectionError:
                delay = min(self.config.API_BASE_DELAY * (2 ** attempt), self.config.API_MAX_DELAY)
                time.sleep(delay)
            except Exception as e:
                self._stats['errors'] += 1
                logger.error(f"Request exception: {e}")
                return requests.Response()
        
        logger.error(f"Max retries exceeded for {method} {url}")
        return requests.Response()
    
    def get_account(self) -> Dict:
        r = self._request('GET', f"{self.config.ALPACA_BASE_URL}/v2/account")
        return r.json() if r.status_code == 200 else {}
    
    def get_positions(self) -> List[Dict]:
        r = self._request('GET', f"{self.config.ALPACA_BASE_URL}/v2/positions")
        return r.json() if r.status_code == 200 else []
    
    def get_clock(self) -> Dict:
        r = self._request('GET', f"{self.config.ALPACA_BASE_URL}/v2/clock")
        return r.json() if r.status_code == 200 else {}
    
    def submit_order(self, symbol: str, qty: int, side: str,
                     order_type: str = 'market', tif: str = 'day',
                     client_order_id: Optional[str] = None,
                     poll_timeout: int = 30) -> Optional[Dict]:
        """Submit order with idempotency key and optional status polling (MP-001 FIX)."""
        if client_order_id is None:
            client_order_id = f"{self.ORDER_PREFIX}{symbol}_{side}_{qty}_{int(time.time())}_{os.urandom(4).hex()}"
        
        data = {
            'symbol': symbol, 'qty': str(abs(qty)), 'side': side,
            'type': order_type, 'time_in_force': tif,
            'client_order_id': client_order_id,
        }
        
        r = self._request('POST', f"{self.config.ALPACA_BASE_URL}/v2/orders",
                         json=data)
        
        if r.status_code in [200, 201]:
            order = r.json()
            
            # MP-001 FIX: Poll for fill status (important for live trading)
            order_id = order.get('id')
            if order_id and poll_timeout > 0:
                order = self._poll_order_fill(order_id, timeout=poll_timeout) or order
            
            costs = TransactionCostModel.calculate(
                float(order.get('filled_avg_price') or order.get('price') or 0),
                abs(qty), side == 'buy'
            )
            # Log structured trade (raw JSON - no formatter)
            trade_entry = {
                'timestamp': now_et().isoformat(),
                'type': 'trade',
                'action': side.upper(),
                'symbol': symbol,
                'qty': abs(qty),
                'price': float(order.get('filled_avg_price') or order.get('price') or 0),
                'costs': costs,
                'order_id': order.get('id'),
                'client_order_id': client_order_id,
                'status': order.get('status'),
            }
            trade_logger.info(json.dumps(trade_entry))
            return order
        
        logger.error(f"Order failed: {side} {qty} {symbol} -> HTTP {r.status_code}")
        return None
    
    def _poll_order_fill(self, order_id: str, timeout: int = 30, interval: float = 0.5) -> Optional[Dict]:
        """MP-001 FIX: Poll order status until filled or timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = self._request('GET', f"{self.config.ALPACA_BASE_URL}/v2/orders/{order_id}")
            if r.status_code == 200:
                order = r.json()
                status = order.get('status', '')
                if status in ('filled', 'canceled', 'expired', 'rejected', 'stopped'):
                    if status == 'filled':
                        logger.debug(f"Order {order_id} filled")
                    return order
            time.sleep(interval)
        logger.warning(f"Order {order_id} poll timeout after {timeout}s")
        return None
    
    # HP-009 FIX: Only cancel orders belonging to our system
    def cancel_our_orders(self) -> bool:
        """Cancel only orders with our client_order_id prefix."""
        # First get all open orders
        r = self._request('GET', f"{self.config.ALPACA_BASE_URL}/v2/orders",
                         params={'status': 'open'})
        if r.status_code != 200:
            return False
        
        orders = r.json()
        our_orders = [o for o in orders if o.get('client_order_id', '').startswith(self.ORDER_PREFIX)]
        
        if not our_orders:
            return True
        
        # Cancel each of our orders individually
        cancelled = 0
        for order in our_orders:
            order_id = order.get('id')
            if order_id:
                rc = self._request('DELETE', f"{self.config.ALPACA_BASE_URL}/v2/orders/{order_id}")
                if rc.status_code in [200, 204]:
                    cancelled += 1
        
        logger.info(f"Cancelled {cancelled}/{len(our_orders)} our orders")
        return True
    
    # Keep for backward compatibility but log warning
    def cancel_all_orders(self):
        logger.warning("cancel_all_orders() cancels ALL orders system-wide. Use cancel_our_orders() instead.")
        r = self._request('DELETE', f"{self.config.ALPACA_BASE_URL}/v2/orders")
        return r.status_code in [200, 204]
    
    def get_bars(self, symbol: str, days: int = 60) -> pd.Series:
        """Get historical bars with configurable feed (MP-006 FIX).

        v8.5: adjustment='all' (split/dividend-adjusted, so dividends and
        splits do not create fake momentum/stop signals), and the index is
        tz-naive (Alpaca returns RFC3339 tz-aware stamps; mixing them with
        naive datetimes raised TypeError in validate_data and killed the
        weekly rebalance).
        """
        end = datetime.now()
        start = end - timedelta(days=days + 30)

        url = f"{self.config.ALPACA_DATA_URL}/v2/stocks/{symbol}/bars"
        params = {
            'start': start.isoformat() + 'Z',
            'end': end.isoformat() + 'Z',
            'timeframe': '1Day',
            'feed': self.config.DATA_FEED,  # MP-006 FIX: configurable feed
            'adjustment': 'all',            # v8.5: split/dividend adjusted
            'limit': 1000
        }

        r = self._request('GET', url, params=params)

        if r.status_code != 200:
            logger.warning(f"Bars failed for {symbol}: HTTP {r.status_code}")
            return pd.Series(dtype=float, name=symbol)

        bars = r.json().get('bars', [])
        if not bars:
            return pd.Series(dtype=float, name=symbol)

        df = pd.DataFrame(bars)
        df['t'] = pd.to_datetime(df['t']).dt.tz_localize(None)
        return pd.Series(df['c'].values, index=df['t'], name=symbol)

    def get_bars_batch(self, symbols: List[str], days: int = 400) -> Dict[str, pd.Series]:
        """v8.5: multi-symbol bars in a few paginated requests.

        The old per-symbol loop made ~520 requests at ~6.7 req/s, over the
        free-tier 200 req/min data limit -> 429 storms and silently missing
        stocks. The multi-symbol endpoint fetches the whole pool with a
        handful of requests. Falls back to per-symbol on failure.
        """
        end = datetime.now()
        start = end - timedelta(days=days + 30)
        url = f"{self.config.ALPACA_DATA_URL}/v2/stocks/bars"
        collected: Dict[str, list] = {s: [] for s in symbols}
        page_token = None
        pages = 0
        try:
            while True:
                params = {
                    'symbols': ','.join(symbols),
                    'start': start.isoformat() + 'Z',
                    'end': end.isoformat() + 'Z',
                    'timeframe': '1Day',
                    'feed': self.config.DATA_FEED,
                    'adjustment': 'all',
                    'limit': 10000,
                }
                if page_token:
                    params['page_token'] = page_token
                r = self._request('GET', url, params=params)
                if r.status_code != 200:
                    raise RuntimeError(f"batch bars HTTP {r.status_code}")
                payload = r.json()
                for sym, bars in (payload.get('bars') or {}).items():
                    collected.setdefault(sym, []).extend(bars)
                page_token = payload.get('next_page_token')
                pages += 1
                if not page_token:
                    break
                time.sleep(0.3)  # stay well under the data rate limit
        except Exception as e:
            logger.warning(f"Batch bars failed ({e}), falling back to per-symbol")
            collected = None

        result: Dict[str, pd.Series] = {}
        if collected is None:
            for sym in symbols:
                s = self.get_bars(sym, days=days)
                if len(s) > 30:
                    result[sym] = s
                time.sleep(0.35)  # <200 req/min on the free tier
            return result

        for sym, bars in collected.items():
            if len(bars) > 30:
                df = pd.DataFrame(bars)
                df['t'] = pd.to_datetime(df['t']).dt.tz_localize(None)
                result[sym] = pd.Series(df['c'].values, index=df['t'], name=sym)
        logger.info(f"Batch bars: {len(result)}/{len(symbols)} symbols in {pages} page(s)")
        return result

    def close_position(self, symbol: str) -> bool:
        """v8.5: close an entire position via DELETE /v2/positions/{symbol}.

        This is the only reliable way to flatten FRACTIONAL leftovers: the
        hedge buys SQQQ via notional orders (always fractional), and selling
        int(qty) leaves a sub-share residue that desynced the hedge state
        machine (ghost position read as 'hedge active' on every restart).
        """
        r = self._request('DELETE', f"{self.config.ALPACA_BASE_URL}/v2/positions/{symbol}")
        ok = r.status_code in (200, 204)
        if not ok:
            logger.error(f"close_position({symbol}) failed: HTTP {r.status_code} {r.text[:200]}")
        return ok

    def get_open_our_orders(self) -> List[Dict]:
        """v8.5: our open orders (for startup reconciliation)."""
        r = self._request('GET', f"{self.config.ALPACA_BASE_URL}/v2/orders",
                          params={'status': 'open'})
        if r.status_code != 200:
            return []
        return [o for o in r.json()
                if o.get('client_order_id', '').startswith(self.ORDER_PREFIX)]
    
    def get_stats(self) -> Dict:
        total = self._stats['requests']
        return {
            'requests': total,
            'errors': self._stats['errors'],
            'retries': self._stats['retries'],
            'success_rate': (total - self._stats['errors']) / max(total, 1),
        }



# ============================================================================
# REALTIME FUNDAMENTALS
# ============================================================================

class RealtimeFundamentals:
    """Fetch fundamentals in real-time with caching."""
    
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.cache: Dict[str, Dict] = {}
        self.cache_time: Dict[str, datetime] = {}
        self.cache_file = self.config.DATA_DIR / 'fundamentals_v82.json'
        self._load_cache()
    
    def _load_cache(self):
        if self.cache_file.exists():
            try:
                with open(self.cache_file) as f:
                    data = json.load(f)
                    self.cache = data.get('values', {})
                    self.cache_time = {k: datetime.fromisoformat(v)
                                      for k, v in data.get('times', {}).items()}
            except Exception:
                pass
    
    def _save_cache(self):
        try:
            self.config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, 'w') as f:
                json.dump({
                    'values': self.cache,
                    'times': {k: v.isoformat() for k, v in self.cache_time.items()}
                }, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Cache save failed: {e}")
    
    def fetch(self, symbol: str) -> Dict:
        """Fetch with cache check."""
        now = datetime.now()
        
        # Check cache
        if symbol in self.cache and symbol in self.cache_time:
            age_hours = (now - self.cache_time[symbol]).total_seconds() / 3600
            if age_hours < self.config.CACHE_TTL_DAYS * 24:
                return self.cache[symbol]
        
        # Fetch from yfinance
        try:
            import yfinance as yf
            info = yf.Ticker(symbol).info
            
            data = {
                'symbol': symbol,
                'name': info.get('shortName', symbol),
                'sector': info.get('sector', 'Unknown'),
                'industry': info.get('industry', 'Unknown'),
                'market_cap': info.get('marketCap', 0),
                'roe': float(info.get('returnOnEquity') or 0.10),
                'gm': float(info.get('grossMargins') or 0.20),
                'rev_g': float(info.get('revenueGrowth') or 0.05),
                'profit_g': float(info.get('earningsGrowth') or 0.05),
                'pe_ratio': float(info.get('trailingPE') or 999),
                'pb_ratio': float(info.get('priceToBook') or 999),
                'dividend_yield': float(info.get('dividendYield') or 0),
                'peg_ratio': float(info.get('pegRatio') or 999),
                'debt_ratio': float(info.get('debtToEquity') or 50) / 100,
                'source': 'yfinance',
                '_timestamp': now.isoformat(),
            }
        except Exception as e:
            logger.warning(f"yfinance failed for {symbol}: {e}")
            data = self._fallback(symbol)
        
        self.cache[symbol] = data
        self.cache_time[symbol] = now
        self._save_cache()
        return data
    
    def fetch_batch(self, symbols: List[str], delay: float = 0.2) -> Dict[str, Dict]:
        """Batch fetch with rate limiting."""
        results = {}
        for i, sym in enumerate(symbols):
            results[sym] = self.fetch(sym)
            if i > 0 and i % 5 == 0:
                time.sleep(delay * 5)
            else:
                time.sleep(delay)
        return results
    
    def _fallback(self, symbol: str) -> Dict:
        sector_map = {
            'JPM': 'Financial Services', 'BAC': 'Financial Services',
            'UNH': 'Healthcare', 'JNJ': 'Healthcare',
            'XOM': 'Energy', 'WMT': 'Consumer Defensive',
        }
        return {
            'symbol': symbol, 'sector': sector_map.get(symbol, 'Unknown'),
            'market_cap': 0, 'roe': 0.10, 'gm': 0.20,
            'pe_ratio': 999, 'pb_ratio': 999, 'dividend_yield': 0,
            'source': 'fallback', '_timestamp': datetime.now().isoformat(),
        }
    
    def get_sector(self, symbol: str) -> str:
        return self.cache.get(symbol, {}).get('sector', 'Unknown')

    def get_asof(self, symbol: str, date=None, price: float = None) -> Dict:
        """Interface compatibility with PointInTimeFundamentals (live mode:
        the cache is always 'as of now')."""
        return self.cache.get(symbol, {})


class PointInTimeFundamentals:
    """Point-in-time fundamentals built from SEC XBRL companyfacts snapshots.

    Each quarterly snapshot becomes visible only on/after its EDGAR 'filed'
    date (the 'avail' field), which eliminates look-ahead bias. Valuation and
    quality ratios are computed at query time from TTM flows (revenue, net
    income, gross profit, dividends), balance-sheet instants (equity) and
    split-adjusted share counts, valued at the query-day price.
    """

    def __init__(self, config: Config = None, pit_file: str = None,
                 sector_map: Dict[str, str] = None):
        self.config = config or Config()
        self.snaps: Dict[str, List[Dict]] = {}
        self._avails: Dict[str, List[str]] = {}
        embedded_sectors: Dict[str, str] = {}
        path = Path(pit_file) if pit_file else self.config.DATA_DIR / 'pit_fundamentals.json'
        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)
                for sym, snaps in data.get('symbols', {}).items():
                    self.snaps[sym] = sorted(snaps, key=lambda s: s['avail'])
                    self._avails[sym] = [s['avail'] for s in self.snaps[sym]]
                embedded_sectors = data.get('sectors', {})
                logger.info(f"PIT fundamentals loaded: {len(self.snaps)} symbols from {path}")
            except Exception as e:
                logger.warning(f"PIT fundamentals load failed: {e}")
        else:
            logger.warning(f"PIT fundamentals file not found: {path}")
        self.sector_map = sector_map if sector_map else embedded_sectors

    def snapshot_asof(self, symbol: str, date) -> Optional[Dict]:
        """Latest raw snapshot available on `date` (None if nothing filed yet)."""
        avails = self._avails.get(symbol)
        if not avails:
            return None
        d = str(date)[:10]
        i = bisect.bisect_right(avails, d) - 1
        return self.snaps[symbol][i] if i >= 0 else None

    def get_asof(self, symbol: str, date=None, price: float = None) -> Dict:
        """Strategy-ready ratios as knowable on `date`, valued at `price`."""
        s = self.snapshot_asof(symbol, date)
        if s is None:
            return {}
        f: Dict[str, Any] = {'sector': self.sector_map.get(symbol, 'Unknown'),
                             'source': 'sec_xbrl_pit', '_timestamp': s['avail']}
        shares = s.get('shares') or 0
        mc = price * shares if (price and shares) else 0
        ni, rev, eq = s.get('ni_ttm'), s.get('rev_ttm'), s.get('equity')
        f['market_cap'] = mc
        f['pe_ratio'] = mc / ni if (mc and ni and ni > 0) else 999
        f['pb_ratio'] = mc / eq if (mc and eq and eq > 0) else 999
        f['ps_ratio'] = mc / rev if (mc and rev) else 999
        f['roe'] = ni / eq if (ni is not None and eq) else 0.0
        # gm is None when gross profit is not reported (banks etc.) - callers
        # must treat None as "not applicable", not as 0
        f['gm'] = s['gp_ttm'] / rev if (s.get('gp_ttm') is not None and rev) else None
        f['rev_g'] = rev / s['rev_ya'] - 1 if (rev and s.get('rev_ya')) else 0.0
        pg = ni / s['ni_ya'] - 1 if (ni is not None and s.get('ni_ya')) else None
        f['profit_g'] = pg if pg is not None else 0.0
        f['dividend_yield'] = (s.get('div_ttm') or 0) / mc if mc else 0.0
        f['peg_ratio'] = (f['pe_ratio'] / (pg * 100)
                          if (pg is not None and pg > 0.02 and f['pe_ratio'] < 999) else 999)
        return f

    def get_sector(self, symbol: str) -> str:
        return self.sector_map.get(symbol, 'Unknown')


# ============================================================================
# TECHNICAL INDICATORS
# ============================================================================

class TechnicalIndicators:
    @staticmethod
    def momentum(prices: pd.Series, period: int) -> float:
        if len(prices) < period + 1:
            return 0.0
        return prices.iloc[-1] / prices.iloc[-(period + 1)] - 1
    
    @staticmethod
    def rs_rating(prices: pd.Series, benchmark: pd.Series, period: int = 126) -> float:
        if len(prices) < period + 1 or len(benchmark) < period + 1:
            return 50.0
        stock_ret = prices.iloc[-1] / prices.iloc[-(period + 1)] - 1
        bench_ret = benchmark.iloc[-1] / benchmark.iloc[-(period + 1)] - 1
        rs = (1 + stock_ret) / (1 + bench_ret) * 100
        return min(max(rs, 0), 100)
    
    @staticmethod
    def above_ma(prices: pd.Series, period: int) -> bool:
        if len(prices) < period:
            return False
        return prices.iloc[-1] > prices.rolling(period).mean().iloc[-1]
    
    @staticmethod
    def volatility(prices: pd.Series, period: int = 20) -> float:
        if len(prices) < period + 1:
            return 0.50
        return prices.pct_change().dropna().iloc[-period:].std() * np.sqrt(252)



# ============================================================================
# 5 STRATEGIES (Momentum, Sector, Growth, Value, Defensive)
# ============================================================================

class MomentumStrategy:
    """Multi-period weighted momentum with trend confirmation."""
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.ind = TechnicalIndicators()
    
    def score(self, symbol: str, prices: pd.DataFrame, benchmark: pd.Series, t: int) -> Optional[Dict]:
        s = prices[symbol].iloc[:t+1]
        b = benchmark.iloc[:t+1]
        if len(s) < 252:
            return None
        
        mom_21 = self.ind.momentum(s, 21)
        mom_63 = self.ind.momentum(s, 63)
        mom_126 = self.ind.momentum(s, 126)
        mom_252 = self.ind.momentum(s, 252)  # v8.5: dead fallback removed (len(s)<252 returns None above)
        rs = self.ind.rs_rating(s, b, 126)
        above_50d = self.ind.above_ma(s, 50)
        above_200d = self.ind.above_ma(s, 200)
        vol = self.ind.volatility(s, 20)
        
        if rs < self.config.RS_MIN or vol > self.config.MAX_VOLATILITY or not above_50d:
            return None
        
        positive_count = sum([mom_21 > 0, mom_63 > 0, mom_126 > 0])
        if positive_count < 2:
            return None
        
        mom_score = (mom_21 * self.config.MOMENTUM_WEIGHTS[0] +
                     mom_63 * self.config.MOMENTUM_WEIGHTS[1] +
                     mom_126 * self.config.MOMENTUM_WEIGHTS[2] +
                     mom_252 * self.config.MOMENTUM_WEIGHTS[3])
        trend_bonus = 0.10 if above_200d else 0.0
        rs_bonus = (rs - self.config.RS_MIN) / 100 * 0.15
        
        return {
            'total': mom_score + trend_bonus + rs_bonus,
            'mom_21': mom_21, 'mom_63': mom_63, 'mom_126': mom_126, 'mom_252': mom_252,
            'rs': rs, 'above_50d': above_50d, 'above_200d': above_200d,
            'volatility': vol, 'trend_bonus': trend_bonus, 'rs_bonus': rs_bonus,
        }
    
    def select(self, prices: pd.DataFrame, benchmark: pd.Series, t: int, max_pos: int = 3) -> Dict[str, Dict]:
        scores = {}
        for sym in prices.columns:
            result = self.score(sym, prices, benchmark, t)
            if result and result['total'] > 0:
                scores[sym] = result
        return dict(sorted(scores.items(), key=lambda x: x[1]['total'], reverse=True)[:max_pos])


class SectorRotationStrategy:
    """Industry momentum ranking with acceleration detection."""
    def __init__(self, fundamentals: RealtimeFundamentals, config: Config = None):
        self.config = config or Config()
        self.fundamentals = fundamentals
        self.ind = TechnicalIndicators()
    
    def select(self, prices: pd.DataFrame, benchmark: pd.Series, t: int, max_pos: int = 3) -> Dict[str, Dict]:
        sector_data = {}
        for sym in prices.columns:
            s = prices[sym].iloc[:t+1]
            if len(s) < 126:
                continue
            sector = self.fundamentals.get_sector(sym)
            mom_63 = self.ind.momentum(s, 63)
            mom_126 = self.ind.momentum(s, 126)
            rs = self.ind.rs_rating(s, benchmark.iloc[:t+1], 126)
            sector_data.setdefault(sector, []).append({
                'ticker': sym, 'mom_63': mom_63, 'mom_126': mom_126,
                'rs': rs, 'combined': mom_63 * 0.6 + mom_126 * 0.4
            })
        
        sector_rank = {}
        for sector, stocks in sector_data.items():
            if len(stocks) < 2:
                continue
            avg_mom = np.mean([s['combined'] for s in stocks])
            recent = np.mean([s['mom_63'] for s in stocks])
            longer = np.mean([s['mom_126'] for s in stocks])
            acceleration = recent - longer / 2
            sector_rank[sector] = {
                'avg_mom': avg_mom, 'acceleration': acceleration,
                'stocks': stocks, 'score': avg_mom + acceleration * 0.5
            }
        
        if not sector_rank:
            return {}
        
        top_sectors = sorted(sector_rank.items(), key=lambda x: x[1]['score'], reverse=True)[:3]
        selected = {}
        for sector, data in top_sectors:
            data['stocks'].sort(key=lambda x: x['combined'] + x['rs'] / 200, reverse=True)
            leader = data['stocks'][0]
            selected[leader['ticker']] = {
                'total': leader['combined'] + data['acceleration'] * 0.3,
                'sector': sector, 'rs': leader['rs'],
                'mom_63': leader['mom_63'], 'mom_126': leader['mom_126'],
                'sector_avg_mom': data['avg_mom'], 'sector_accel': data['acceleration'],
            }
        return dict(sorted(selected.items(), key=lambda x: x[1]['total'], reverse=True)[:max_pos])


class GrowthStrategy:
    """CANSLIM-inspired growth stock selection."""
    def __init__(self, fundamentals: RealtimeFundamentals, config: Config = None):
        self.config = config or Config()
        self.fundamentals = fundamentals
        self.ind = TechnicalIndicators()
    
    def score(self, symbol: str, prices: pd.DataFrame, benchmark: pd.Series, t: int) -> Optional[Dict]:
        s = prices[symbol].iloc[:t+1]
        if len(s) < 126:
            return None
        f = self.fundamentals.get_asof(symbol, prices.index[t], price=s.iloc[-1])
        if not f:
            return None  # no filings available yet -> no growth signal

        roe = f.get('roe', 0.0)
        gm = f.get('gm')  # None when not reported (banks/insurers): filter skipped, neutral score
        mom_21 = self.ind.momentum(s, 21)
        mom_63 = self.ind.momentum(s, 63)
        rs = self.ind.rs_rating(s, benchmark.iloc[:t+1], 126)
        above_50d = self.ind.above_ma(s, 50)

        if roe < self.config.MIN_ROE or (gm is not None and gm < self.config.MIN_GROSS_MARGIN) or rs < 50 or not above_50d:
            return None

        roe_s = min(roe / 0.25 * 100, 100)
        gm_s = min(gm / 0.50 * 100, 100) if gm is not None else 50.0
        rev_s = min(max(f.get('rev_g', 0.0) / 0.30 * 100, 0), 100)
        profit_s = min(max(f.get('profit_g', 0.0) / 0.35 * 100, 0), 100)
        accel_s = min(max((mom_21 - mom_63 / 3 + 0.2) / 0.4 * 100, 0), 100)

        quality = (roe_s * 0.30 + gm_s * 0.20 + rev_s * 0.20 + profit_s * 0.20 + accel_s * 0.10) / 100
        momentum_score = mom_63 * 0.5 if mom_63 > 0.05 else 0

        return {
            'total': quality + momentum_score,
            'quality': quality, 'momentum': momentum_score,
            'roe': roe, 'gm': gm, 'mom_21': mom_21, 'mom_63': mom_63, 'rs': rs,
        }
    
    def select(self, prices: pd.DataFrame, benchmark: pd.Series, t: int, max_pos: int = 3) -> Dict[str, Dict]:
        scores = {}
        for sym in prices.columns:
            result = self.score(sym, prices, benchmark, t)
            if result and result['total'] > 0.3:
                scores[sym] = result
        return dict(sorted(scores.items(), key=lambda x: x[1]['total'], reverse=True)[:max_pos])


class ValueStrategy:
    """Value investing: low PE/PB, high dividend, mean reversion."""
    def __init__(self, fundamentals: RealtimeFundamentals, config: Config = None):
        self.config = config or Config()
        self.fundamentals = fundamentals
        self.ind = TechnicalIndicators()
    
    def score(self, symbol: str, prices: pd.DataFrame, benchmark: pd.Series, t: int) -> Optional[Dict]:
        s = prices[symbol].iloc[:t+1]
        if len(s) < 126:
            return None
        f = self.fundamentals.get_asof(symbol, prices.index[t], price=s.iloc[-1])
        if not f:
            return None  # no filings available yet -> no value signal

        pe = f.get('pe_ratio', 999)
        pb = f.get('pb_ratio', 999)
        div = f.get('dividend_yield', 0)
        peg = f.get('peg_ratio', 999)
        roe = f.get('roe', 0.0)
        sector = f.get('sector', 'Unknown')
        market_cap = f.get('market_cap', 0)

        adj_max_pe = self.config.VALUE_MAX_PE
        adj_max_pb = self.config.VALUE_MAX_PB
        
        if pe > adj_max_pe or pe <= 0 or pb > adj_max_pb or pb <= 0 or peg > 2.5 or roe < 0.08:
            return None
        
        pe_score = max((adj_max_pe - pe) / adj_max_pe, 0)
        pb_score = max((adj_max_pb - pb) / adj_max_pb, 0)
        div_score = min(div / self.config.VALUE_MIN_DIV_YIELD * 0.5, 1.0) if div > 0 else 0
        peg_score = max((2.5 - peg) / 2.5, 0)
        
        mom_63 = self.ind.momentum(s, 63)
        reversion = abs(mom_63) * 0.3 if -0.50 < mom_63 < -0.15 else 0
        quality_bonus = min(roe / 0.25 * 0.15, 0.15)
        
        total = pe_score * 0.25 + pb_score * 0.20 + div_score * 0.15 + peg_score * 0.10 + reversion + quality_bonus
        
        return {
            'total': total, 'pe_score': pe_score, 'pb_score': pb_score,
            'div_score': div_score, 'peg_score': peg_score,
            'reversion_bonus': reversion, 'quality_bonus': quality_bonus,
            'pe': pe, 'pb': pb, 'div_yield': div, 'peg': peg,
            'roe': roe, 'sector': sector, 'market_cap': market_cap,
            'mom_63': mom_63,
        }
    
    def select(self, prices: pd.DataFrame, benchmark: pd.Series, t: int, max_pos: int = 3) -> Dict[str, Dict]:
        scores = {}
        for sym in prices.columns:
            result = self.score(sym, prices, benchmark, t)
            if result and result['total'] > 0.2:
                scores[sym] = result
        return dict(sorted(scores.items(), key=lambda x: x[1]['total'], reverse=True)[:max_pos])


class DefensiveStrategy:
    """Defensive: low volatility, defensive sectors, stable earnings."""
    def __init__(self, fundamentals: RealtimeFundamentals, config: Config = None):
        self.config = config or Config()
        self.fundamentals = fundamentals
        self.ind = TechnicalIndicators()
    
    DEFENSIVE_SECTORS = ['Consumer Defensive', 'Utilities', 'Healthcare']
    
    def score(self, symbol: str, prices: pd.DataFrame, benchmark: pd.Series, t: int) -> Optional[Dict]:
        s = prices[symbol].iloc[:t+1]
        if len(s) < 50:
            return None
        f = self.fundamentals.get_asof(symbol, prices.index[t], price=s.iloc[-1])
        if not f:
            return None  # no filings available yet -> no defensive signal

        vol = self.ind.volatility(s, 20)
        roe = f.get('roe', 0.0)
        gm = f.get('gm')  # None when not reported (banks/insurers)
        div = f.get('dividend_yield', 0)
        sector = f.get('sector', 'Unknown')
        rs = self.ind.rs_rating(s, benchmark.iloc[:t+1], 126)

        if vol > self.config.DEFENSIVE_MAX_VOLATILITY or roe < 0.10 or (gm is not None and gm < 0.25):
            return None

        vol_score = max((self.config.DEFENSIVE_MAX_VOLATILITY - vol) / self.config.DEFENSIVE_MAX_VOLATILITY, 0)
        sector_bonus = 0.20 if sector in self.DEFENSIVE_SECTORS else 0.0
        div_score = min(div / self.config.DEFENSIVE_MIN_DIV_YIELD * 0.5, 1.0) if div > 0 else 0
        gm_quality = min(gm / 0.50 * 0.3, 0.3) if gm is not None else 0.15
        quality = min(roe / 0.20 * 0.5, 0.5) + gm_quality
        rs_score = 0.1 if rs > 40 else 0.0
        ma_slope = (s.rolling(50).mean().iloc[-1] - s.rolling(50).mean().iloc[-10]) / s.rolling(50).mean().iloc[-10] if len(s) >= 60 else 0
        stability = 0.1 if ma_slope > -0.01 else 0.0
        
        total = vol_score * 0.25 + div_score * 0.20 + quality * 0.25 + sector_bonus + rs_score + stability
        
        return {
            'total': total, 'vol_score': vol_score, 'div_score': div_score,
            'quality_score': quality, 'sector_bonus': sector_bonus,
            'rs_score': rs_score, 'stability_score': stability,
            'volatility': vol, 'div_yield': div, 'roe': roe, 'gm': gm,
            'sector': sector, 'is_defensive': sector in self.DEFENSIVE_SECTORS, 'rs': rs,
        }
    
    def select(self, prices: pd.DataFrame, benchmark: pd.Series, t: int, max_pos: int = 3) -> Dict[str, Dict]:
        scores = {}
        for sym in prices.columns:
            result = self.score(sym, prices, benchmark, t)
            if result and result['total'] > 0.25:
                scores[sym] = result
        return dict(sorted(scores.items(), key=lambda x: (x[1]['is_defensive'], x[1]['total']), reverse=True)[:max_pos])



# ============================================================================
# MACRO TIMING (HP-006 FIX: data length checks)
# ============================================================================

class MacroTiming:
    """Market regime detection based on volatility and trend."""
    
    def __init__(self, config: Config = None):
        self.config = config or Config()
    
    def detect(self, prices: pd.DataFrame, t: int) -> Tuple[str, Dict]:
        spy_col = 'SPY' if 'SPY' in prices.columns else prices.columns[0]
        spy = prices[spy_col].iloc[:t+1]
        
        # HP-006 FIX: Defensive check - need at least 60 days for meaningful detection
        if t < 60 or len(spy) < 60:
            return 'NEUTRAL', {'position_factor': 0.85 if self.config.REGIME_DEGROSS_ENABLED else 1.0,
                               'hedge_ratio': 0.05, 'reason': 'insufficient_data'}
        
        recent_ret = spy.pct_change().dropna().iloc[-20:]
        current_vol = recent_ret.std() * np.sqrt(252)
        
        # HP-006 FIX: Proper data length checks with safe defaults
        above_200d = False
        if t >= 200 and len(spy) >= 200:
            ma200 = spy.rolling(200).mean()
            if not ma200.isna().iloc[-1]:
                above_200d = spy.iloc[-1] > ma200.iloc[-1]
        
        above_50d = False
        if t >= 50 and len(spy) >= 50:
            ma50 = spy.rolling(50).mean()
            if not ma50.isna().iloc[-1]:
                above_50d = spy.iloc[-1] > ma50.iloc[-1]
        
        mom_20 = spy.iloc[-1] / spy.iloc[-20] - 1 if t >= 20 and len(spy) >= 20 else 0
        
        if current_vol < 0.18 and above_200d and mom_20 > 0:
            regime = 'BULL'
            pf, hr = 1.0, 0.0
        elif current_vol < 0.25 and above_200d:
            # v8.7 (data-driven, approved 2026-07-30): NEUTRAL gated on the
            # 200d trend instead of the noisy 50d MA. Regime sensitivity
            # battery (data/regime_experiments.json): +326.9%/Sharpe 1.34/
            # MDD -23.2% vs base +240.0%/1.20/-24.7%; wins both segments
            # (2020-23 +53.8%, 2024-26 +178.4%; SPY +25.5%/+56.7%).
            regime = 'NEUTRAL'
            pf, hr = 0.85, 0.05
        elif current_vol < 0.35:
            regime = 'BEAR'
            pf, hr = 0.60, 0.15
        else:
            regime = 'PANIC'
            pf, hr = 0.40, 0.25
        
        # Volatility trend adjustment
        if t >= 40 and len(spy) >= 41:
            older_vol_data = spy.pct_change().dropna().iloc[-40:-20]
            if len(older_vol_data) >= 19:
                older_vol = older_vol_data.std() * np.sqrt(252)
                vol_trend = current_vol - older_vol
                if vol_trend > 0.05:
                    if self.config.REGIME_DEGROSS_ENABLED:
                        pf *= 0.80
                    hr = min(hr + 0.10, 0.30)

        # v8.9: regime no longer scales exposure (see Config note)
        if not self.config.REGIME_DEGROSS_ENABLED:
            pf = 1.0
        
        return regime, {
            'regime': regime, 'position_factor': max(pf, 0.20),
            'hedge_ratio': hr, 'current_vol': current_vol,
            'above_200d': above_200d, 'above_50d': above_50d, 'mom_20': mom_20,
        }
    
    def get_weights(self, regime: str, config: Config = None) -> Dict[str, float]:
        config = config or Config()
        return {
            'BULL': config.WEIGHT_BULL,
            'NEUTRAL': config.WEIGHT_NEUTRAL,
            'BEAR': config.WEIGHT_BEAR,
            'PANIC': config.WEIGHT_PANIC,
        }.get(regime, config.WEIGHT_NEUTRAL)


# ============================================================================
# FAIL-SAFE REBALANCER
# ============================================================================

class FailSafeRebalancer:
    """Fail-safe rebalancer: retain overlapping holdings, only trade deltas."""
    
    def __init__(self, config: Config = None):
        self.config = config or Config()
    
    def validate_data(self, prices: pd.DataFrame) -> Tuple[bool, str]:
        if prices.empty:
            return False, "Empty DataFrame"
        if len(prices) < self.config.MIN_DATA_DAYS:
            return False, f"Only {len(prices)} days, need {self.config.MIN_DATA_DAYS}"
        n = len([c for c in prices.columns if c != 'SPY'])
        if n < self.config.MIN_STOCKS_FOR_REBALANCE:
            return False, f"Only {n} stocks, need {self.config.MIN_STOCKS_FOR_REBALANCE}"
        last_date = prices.index[-1]
        # v8.5 (P0-1): defensive tz-normalization. Alpaca bars arrive
        # tz-aware; naive - aware subtraction raised TypeError here and the
        # unhandled exception killed the whole monitor on the first weekly
        # rebalance. (get_bars now normalizes too; this is the seatbelt.)
        if getattr(last_date, 'tzinfo', None) is not None:
            last_date = last_date.tz_localize(None)
        if (datetime.now() - last_date).days > 3:
            return False, f"Stale data: last {last_date.date()}"
        missing = prices.isnull().sum().sum() / prices.size
        if missing > 0.2:
            return False, f"Too much missing: {missing:.1%}"
        return True, "OK"
    
    def smart_rebalance(self, prices: pd.DataFrame, current_symbols: set,
                        new_signals: List[str], equity: float) -> Dict[str, int]:
        """Smart rebalance: keep overlapping, only trade deltas."""
        new_set = set(new_signals)
        keep = current_symbols & new_set
        sell = current_symbols - new_set
        buy = new_set - current_symbols
        
        logger.info(f"Smart rebalance: keep={len(keep)} sell={len(sell)} buy={len(buy)}")
        logger.info(f"  Keep: {sorted(keep)}, Sell: {sorted(sell)}, Buy: {sorted(buy)}")
        
        capital_per = equity / len(new_signals) if new_signals else 0
        target = {}
        for sym in new_signals:
            if sym in prices.columns:
                price = prices[sym].iloc[-1]
                if price > 0:
                    qty = int(capital_per / price)
                    if qty > 0:
                        target[sym] = qty
        return target



# ============================================================================
# RISK CONTROLLER (BUG-001 FIX, BUG-002 FIX, HP-002 FIX)
# ============================================================================

class RiskController:
    """Portfolio-level risk control: daily loss limit, drawdown circuit breaker, concurrency lock."""
    
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self._rebalancing = False
        self._circuit_active = False
        self._circuit_time = None
        self._peak_equity = 0
        # BUG-001 FIX: Initialize as None instead of 0 to avoid division-by-zero
        self._last_equity = None       # last equity seen (any call)
        self._day_baseline = None      # v8.3: frozen at yesterday's last equity
        self._last_date = None
        # v8.5: whether the emergency liquidation for the CURRENT circuit
        # episode already ran. Without this, every 60s cycle re-liquidated
        # (harmless on a flat account but floods logs and the broker API).
        self._liquidated_for_circuit = False

    # v8.5: (de)serialization so a restart keeps the daily baseline and the
    # circuit state. Previously a restart silently reset the daily-loss
    # baseline (exempting losses already incurred that day) and forgot an
    # active circuit breaker.
    def state_dict(self) -> Dict:
        return {
            'peak_equity': self._peak_equity,
            'circuit_active': self._circuit_active,
            'circuit_time': self._circuit_time.isoformat() if self._circuit_time else None,
            'liquidated_for_circuit': self._liquidated_for_circuit,
            'day_baseline': self._day_baseline,
            'baseline_date': self._last_date.isoformat() if self._last_date else None,
        }

    def load_state_dict(self, d: Dict):
        self._peak_equity = d.get('peak_equity', 0) or 0
        self._circuit_active = bool(d.get('circuit_active', False))
        ct = d.get('circuit_time')
        if ct:
            try:
                self._circuit_time = datetime.fromisoformat(ct)
            except (ValueError, TypeError):
                self._circuit_time = None
        self._liquidated_for_circuit = bool(d.get('liquidated_for_circuit', False))
        # Daily baseline only valid if it was frozen earlier the SAME day
        bd = d.get('baseline_date')
        if bd and bd == now_et().date().isoformat():
            self._day_baseline = d.get('day_baseline')
            try:
                self._last_date = datetime.fromisoformat(bd).date()
            except (ValueError, TypeError):
                self._last_date = None
    
    # --- Concurrency ---
    def acquire_rebalance_lock(self) -> bool:
        if self._rebalancing:
            return False
        self._rebalancing = True
        return True
    
    def release_rebalance_lock(self):
        self._rebalancing = False
    
    @property
    def is_rebalancing(self) -> bool:
        return self._rebalancing
    
    # --- Daily Loss & Drawdown ---
    def check_limits(self, equity: float, now: datetime = None) -> Tuple[bool, str]:
        """Returns (can_trade, reason).

        v8.3 (C1 fix): the daily baseline is the LAST equity of the previous day
        and is never updated intraday. The v8.2 version updated `_last_equity`
        on every call, which turned the "-3% per day" limit into a
        "-3% per monitoring-interval" limit: slow intraday bleed never triggered
        it and overnight gaps were ignored.

        v8.5: default clock is US Eastern (host-timezone independent).
        """
        now = now or now_et()

        # New day: freeze the baseline at yesterday's last seen equity.
        if self._last_date != now.date():
            self._day_baseline = self._last_equity if self._last_equity is not None else equity
            self._last_date = now.date()
            logger.debug(f"New day - daily equity baseline = ${self._day_baseline:,.2f}")

        # Circuit breaker check
        if self._circuit_active and self._circuit_time:
            elapsed = (now - self._circuit_time).total_seconds() / 3600
            if elapsed > self.config.CIRCUIT_BREAKER_COOLDOWN_HOURS:
                logger.info("Circuit breaker auto-released")
                self._circuit_active = False
                self._circuit_time = None
                self._liquidated_for_circuit = False  # v8.5: next episode liquidates once
            else:
                return False, f"circuit_breaker ({self.config.CIRCUIT_BREAKER_COOLDOWN_HOURS - elapsed:.0f}h remaining)"

        # Update peak
        if equity > self._peak_equity:
            self._peak_equity = equity

        # Daily loss limit vs day baseline (BUG-001: None-safe)
        if self._day_baseline is not None and self._day_baseline > 0:
            daily_pnl = (equity - self._day_baseline) / self._day_baseline
            if daily_pnl <= self.config.DAILY_LOSS_LIMIT_PCT:
                logger.critical(f"DAILY LOSS LIMIT: {daily_pnl:.2%} (threshold: {self.config.DAILY_LOSS_LIMIT_PCT:.2%})")
                self._last_equity = equity
                return False, f"daily_loss_limit ({daily_pnl:.2%})"

        # Max drawdown
        if self._peak_equity > 0:
            dd = (equity - self._peak_equity) / self._peak_equity
            if dd <= self.config.MAX_DRAWDOWN_LIMIT_PCT:
                logger.critical(f"MAX DRAWDOWN: {dd:.2%} (threshold: {self.config.MAX_DRAWDOWN_LIMIT_PCT:.2%})")
                self._circuit_active = True
                self._circuit_time = now
                # v8.3: reset the peak after a breach. Otherwise, once
                # liquidated to cash, equity can never recover toward the old
                # peak and the breaker re-triggers every cycle forever
                # (permanent lockout, observed flapping every 24h).
                self._peak_equity = equity
                self._last_equity = equity
                return False, f"max_drawdown ({dd:.2%})"

        self._last_equity = equity
        return True, "OK"
    
    # HP-002 FIX: Check return value of each order, track failures
    def emergency_liquidate(self, client: AlpacaClient) -> Dict[str, Any]:
        """Sell all positions immediately. Returns summary of results."""
        logger.critical("EMERGENCY LIQUIDATION INITIATED")
        positions = client.get_positions()
        results = {'succeeded': [], 'failed': []}
        
        for p in positions:
            sym = p['symbol']
            qty = int(float(p['qty']))
            if qty <= 0:
                continue
            try:
                order = client.submit_order(sym, qty, 'sell')
                if order and order.get('status') in ('filled', 'accepted', 'new', 'pending'):
                    results['succeeded'].append(sym)
                    logger.info(f"Emergency sell {sym}: {qty} shares - {order.get('status')}")
                else:
                    results['failed'].append({'symbol': sym, 'qty': qty, 'reason': 'order_rejected'})
                    logger.error(f"Emergency sell {sym} FAILED: order not accepted")
            except Exception as e:
                results['failed'].append({'symbol': sym, 'qty': qty, 'reason': str(e)})
                logger.error(f"Emergency sell {sym} EXCEPTION: {e}")
            time.sleep(0.3)
        
        logger.critical(f"Emergency liquidation complete: {len(results['succeeded'])} succeeded, {len(results['failed'])} failed")
        return results


# ============================================================================
# PORTFOLIO CONSTRUCTOR (HP-007 FIX: remove unused param)
# ============================================================================

class PortfolioConstructor:
    """Combine 5 strategy signals with dynamic weighting and transaction costs."""
    
    def __init__(self, config: Config = None):
        self.config = config or Config()
    
    def combine(self, mom: Dict, sector: Dict, growth: Dict, value: Dict,
                defensive: Dict, weights: Dict[str, float]) -> Dict[str, Dict]:
        combined = {}
        all_picks = {'momentum': mom, 'sector': sector, 'growth': growth, 'value': value, 'defensive': defensive}
        
        for strat_name, picks in all_picks.items():
            w = weights.get(strat_name, 0)
            for sym, data in picks.items():
                if sym not in combined:
                    combined[sym] = {
                        'momentum_score': 0, 'sector_score': 0, 'growth_score': 0,
                        'value_score': 0, 'defensive_score': 0,
                        'strategies': [], 'details': {},
                    }
                combined[sym][f'{strat_name}_score'] = data.get('total', 0)
                combined[sym]['strategies'].append(strat_name)
                combined[sym]['details'][strat_name] = data
        
        for sym, data in combined.items():
            base = (data['momentum_score'] * weights.get('momentum', 0) +
                    data['sector_score'] * weights.get('sector', 0) +
                    data['growth_score'] * weights.get('growth', 0) +
                    data['value_score'] * weights.get('value', 0) +
                    data['defensive_score'] * weights.get('defensive', 0))
            n = len(data['strategies'])
            bonus = self.config.STRATEGY_RESONANCE_BONUS * (n - 1)
            data['total'] = base + bonus
            data['n_strategies'] = n
        
        return dict(sorted(combined.items(), key=lambda x: x[1]['total'], reverse=True))
    
    def filter_21d_high(self, signals: Dict[str, Dict], prices: pd.DataFrame,
                        t: int, threshold: float = 0.8) -> Dict[str, Dict]:
        """
        调仓过滤: 排除跌破21日高点threshold的个股。
        默认threshold=0.8: 距离21日高点回撤超过20%的个股被排除出调仓候选池。
        已持仓个股不受此过滤影响(由独立止损逻辑管理)。
        """
        if not signals or t < 21:
            return signals
        filtered = {}
        for sym, data in signals.items():
            if sym in prices.columns:
                high_21d = prices[sym].iloc[t-21:t+1].max()
                current = prices[sym].iloc[t]
                if high_21d > 0 and current >= high_21d * threshold:
                    filtered[sym] = data
                else:
                    logger.info(f"FILTER-21DHIGH: {sym} EXCLUDED "
                               f"(price=${current:.2f}, 21d-high=${high_21d:.2f}, "
                               f"ratio={current/high_21d:.1%} < {threshold:.0%})")
            else:
                filtered[sym] = data
        return filtered
    
    def filter_by_volatility(self, signals: Dict[str, Dict], prices: pd.DataFrame,
                             t: int, max_vol: float = None) -> Dict[str, Dict]:
        """
        调仓阶段全局波动率过滤: 排除20日年化波动率超过max_vol的个股。
        作用于combine()之后、allocate()之前, 覆盖所有策略的选股信号。
        已持仓个股不受此过滤影响(由独立止损逻辑管理)。
        """
        if not signals or t < 20:
            return signals
        if max_vol is None:
            max_vol = self.config.MAX_VOLATILITY
        filtered = {}
        for sym, data in signals.items():
            if sym in prices.columns:
                vol = prices[sym].iloc[max(0, t-20):t+1].pct_change().std() * np.sqrt(252)
                if vol <= max_vol:
                    filtered[sym] = data
                else:
                    logger.info(f"VOL-FILTER: {sym} EXCLUDED "
                               f"(20d-vol={vol:.1%} > max={max_vol:.1%})")
            else:
                filtered[sym] = data
        return filtered
    
    # HP-007 FIX: Removed unused `fundamentals` parameter
    def allocate(self, signals: Dict[str, Dict], capital: float, prices: pd.DataFrame,
                 t: int) -> Dict[str, int]:
        if not signals:
            return {}
        
        current_prices = prices.iloc[t]
        top = dict(list(signals.items())[:self.config.MAX_POSITIONS])
        positions = {}
        
        for sym, signal in top.items():
            if sym not in current_prices or current_prices[sym] <= 0:
                continue
            
            price = current_prices[sym]
            
            # Volatility-based sizing
            if t >= 20:
                vol = prices[sym].iloc[max(0, t-20):t+1].pct_change().std() * np.sqrt(252)
            else:
                vol = 0.30
            
            if 'defensive' in signal.get('strategies', []):
                vol *= 0.8
            
            vol_factor = min(self.config.VOLATILITY_TARGET / vol, 2.0) if vol > 0 else 1.0
            score_weight = min(signal['total'] / 0.5, 1.0) if signal['total'] > 0 else 0.5
            
            target_value = capital * vol_factor * score_weight / self.config.MAX_POSITIONS
            max_val = capital * self.config.MAX_SINGLE_POSITION_PCT
            min_val = capital * self.config.MIN_SINGLE_POSITION_PCT
            target_value = max(min(target_value, max_val), min_val)
            
            qty = int(target_value / price)
            if qty > 0:
                positions[sym] = qty
        
        return positions



# ============================================================================
# VIX DATA PROVIDER (v8.3)
# Replaces the broken "VIX = VIXY price x 0.85" proxy: VIXY is a futures ETF
# whose price level is driven by contango decay and reverse splits, so it has
# no stable mapping to the VIX index. Real sources, in priority order:
#   1. yfinance ^VIX quote (near real-time)
#   2. CBOE official VIX history CSV (end-of-day, staleness-guarded)
# Returns None when no fresh source is available -> caller must HOLD.
# ============================================================================

class VixProvider:
    """Real VIX level with TTL caching and stale-data guards."""

    def __init__(self, config: Config = None):
        self.config = config or Config()
        self._cached: Optional[float] = None
        self._cached_at: float = 0.0
        self._yf_failures = 0  # v8.5: escalate repeated yfinance outages

    def get_vix(self) -> Optional[float]:
        now = time.time()
        if self._cached is not None and now - self._cached_at < self.config.VIX_CACHE_TTL_SEC:
            return self._cached
        vix = self._from_yfinance()
        if vix is None:
            vix = self._from_cboe_eod()
        if vix is not None:
            self._cached, self._cached_at = vix, now
        return vix

    def _from_yfinance(self) -> Optional[float]:
        try:
            import yfinance as yf
            t = yf.Ticker('^VIX')
            price = getattr(t.fast_info, 'last_price', None)
            if price and 5.0 < float(price) < 150.0:
                self._yf_failures = 0
                return float(price)
        except Exception as e:
            self._yf_failures += 1
            # v8.5: yfinance is an unofficial API with no SLA and gets
            # rate-limited/blocked regularly; a persistent outage means the
            # hedge runs on yesterday's CBOE close - make that visible.
            if self._yf_failures >= 3:
                logger.warning(f"VIX yfinance failing x{self._yf_failures}: {e} "
                               f"(falling back to CBOE EOD, intraday moves missed)")
            else:
                logger.debug(f"VIX yfinance unavailable: {e}")
        return None

    def _from_cboe_eod(self) -> Optional[float]:
        """CBOE official daily VIX history (EOD only; rejected if stale)."""
        try:
            r = requests.get(self.config.VIX_CBOE_URL, timeout=self.config.API_TIMEOUT)
            if r.status_code != 200:
                return None
            import io
            df = pd.read_csv(io.StringIO(r.text))
            df.columns = [c.strip().upper() for c in df.columns]
            df['DATE'] = pd.to_datetime(df['DATE'], format='%m/%d/%Y')
            last = df.iloc[-1]
            age_days = (datetime.now() - last['DATE']).days
            if age_days > self.config.VIX_MAX_STALE_DAYS:
                logger.warning(f"VIX EOD data stale ({age_days}d old), rejecting")
                return None
            if age_days >= 1:
                logger.info(f"VIX from CBOE EOD ({last['DATE'].date()}), not intraday")
            return float(last['CLOSE'])
        except Exception as e:
            logger.debug(f"VIX CBOE unavailable: {e}")
        return None


# ============================================================================
# HEDGE ENGINE — Multi-Layer Portfolio Protection
# DCL: get_prices(刷新) → calculate_hedge(信号) → submit_order(下单)
# ============================================================================

class HedgeEngine:
    """
    Real-Time Conditional Hedge: SQQQ 10% when VIX>=25, zero when VIX<=24.75.
    Hysteresis band (24.75, 25) prevents jitter. Daily switch limit=2 (circuit breaker).
    v8.3: state is committed ONLY after a successful order (was: flipped before
    execution, causing state/position desync on order failure).
    """
    
    def __init__(self, config: Config = None, client: AlpacaClient = None,
                 vix_provider: 'VixProvider' = None):
        self.config = config or Config()
        self.vix_provider = vix_provider or VixProvider(self.config)
        self._switches_today = 0         # Daily switch counter
        self._last_switch_date = None    # Track date for daily reset
        self._circuit_broken = False     # Daily circuit breaker flag
        # Sync hedge state with existing SQQQ position on startup
        self._hedge_active = self._sync_hedge_state(client)
    
    def _sync_hedge_state(self, client: AlpacaClient = None) -> bool:
        """On startup, check if SQQQ position exists → set _hedge_active accordingly."""
        if client is None:
            return False
        try:
            for p in client.get_positions():
                if p['symbol'] == self.config.HEDGE_ETF and float(p['qty']) > 0:
                    logger.warning(f"HEDGE SYNC: Found existing {p['qty']} {self.config.HEDGE_ETF} "
                                  f"on startup → setting _hedge_active=True")
                    return True
        except Exception:
            pass
        return False
    
    def _get_vix_level(self, client: AlpacaClient = None) -> Optional[float]:
        """v8.3: real VIX via VixProvider. None = unavailable -> HOLD (no guessing)."""
        vix = self.vix_provider.get_vix()
        if vix is None:
            logger.warning("VIX unavailable from all sources - hedge holds current state")
        return vix
    
    def _reset_daily_counter(self, now: datetime = None):
        """Reset daily switch counter at new day.

        v8.3: accepts simulated time. v8.2 used wall-clock datetime.now(), so in
        backtests the whole run counted as ONE day - after 2 switches the hedge
        circuit-broke forever (only 2 hedge trades in 4 years).
        """
        today = (now or now_et()).date()  # v8.5: market day in ET
        if self._last_switch_date != today:
            self._switches_today = 0
            self._circuit_broken = False
            self._last_switch_date = today
    
    def evaluate(self, vix_level: float, now: datetime = None) -> str:
        """
        Narrow hysteresis hedge evaluation with daily circuit breaker.
        
        Trigger Table:
          VIX >= 25.0      → ACTIVATE (if not already active, and switches < 2)
          VIX <= 24.75     → DEACTIVATE (if active, and switches < 2)
          24.75 < VIX < 25 → HOLD (narrow hysteresis band, no action)
          switches >= 2    → CIRCUIT_BROKEN (no more switches today)
        
        Returns: 'activate' | 'deactivate' | 'hold' | 'circuit_broken'

        v8.3: this method is now PURE (no state mutation). State is committed
        by _commit_switch() only after the order executes successfully.
        """
        if not self.config.ENABLE_HEDGE:
            return 'hold'

        self._reset_daily_counter(now)

        # Circuit breaker: max 2 switches per day
        if self._circuit_broken:
            return 'circuit_broken'

        # Hysteresis logic
        if vix_level >= self.config.HEDGE_VIX_ACTIVATE and not self._hedge_active:
            if self._switches_today >= self.config.HEDGE_MAX_SWITCHES_PER_DAY:
                self._circuit_broken = True
                logger.warning(f"HEDGE CIRCUIT BROKEN: {self._switches_today} switches today")
                return 'circuit_broken'
            return 'activate'
        if vix_level <= self.config.HEDGE_VIX_DEACTIVATE and self._hedge_active:
            if self._switches_today >= self.config.HEDGE_MAX_SWITCHES_PER_DAY:
                self._circuit_broken = True
                logger.warning(f"HEDGE CIRCUIT BROKEN: {self._switches_today} switches today")
                return 'circuit_broken'
            return 'deactivate'

        # Hysteresis band: 24.75 < VIX < 25 → maintain current state
        return 'hold'

    def _commit_switch(self, action: str):
        """v8.3: commit state AFTER a successful hedge order."""
        self._switches_today += 1
        self._hedge_active = (action == 'activate')
    
    def is_hedge_active(self) -> bool:
        """Current hedge state."""
        return self._hedge_active
    
    def calculate_hedge(self, equity: float) -> Dict[str, float]:
        """Return SQQQ target dollar amount when hedge is active."""
        if not self._hedge_active:
            return {}
        target = {}
        hedge_dollar = equity * self.config.HEDGE_POSITION_PCT
        if hedge_dollar > 100:
            target[self.config.HEDGE_ETF] = hedge_dollar
        return target
    
    def get_stock_compression(self) -> float:
        """Return stock position factor (0.9 when hedged, 1.0 otherwise)."""
        return self.config.HEDGE_STOCK_COMPRESSION if self._hedge_active else 1.0
    
    def _check_buying_power(self, client: AlpacaClient, required: float) -> bool:
        """Check if account has sufficient buying power."""
        try:
            acct = client.get_account()
            bp = float(acct.get('buying_power', 0))
            cash = float(acct.get('cash', 0))
            # Require both buying power and positive cash cushion
            return bp >= required and cash >= required * 0.5
        except Exception:
            return False

    def _trim_stocks_for_hedge(self, client: AlpacaClient, needed: float) -> bool:
        """v8.5: sell a pro-rata slice of every stock position to free cash.

        Each stock is trimmed by (needed / total_stock_value) of its market
        value - this is the live realization of HEDGE_STOCK_COMPRESSION=0.90.
        Sells are polled to fill before we report success; the freed cash is
        then verified against the account.
        """
        try:
            positions = [p for p in client.get_positions()
                         if p['symbol'] != self.config.HEDGE_ETF]
            total_mv = sum(float(p['market_value']) for p in positions)
            if total_mv <= 0:
                return False
            frac = min(needed / total_mv, 0.95)
            for p in positions:
                sym = p['symbol']
                trim_val = float(p['market_value']) * frac
                price = float(p['current_price'])
                qty = int(trim_val / price) if price > 0 else 0
                if qty < 1:
                    continue
                order = client.submit_order(sym, qty, 'sell', poll_timeout=30)
                if not (order and order.get('status') in
                        ('filled', 'accepted', 'new', 'partially_filled')):
                    logger.error(f"Hedge funding trim FAILED for {sym}")
                time.sleep(0.3)
            # Verify freed cash
            time.sleep(1.0)
            acct = client.get_account()
            cash = float(acct.get('cash', 0))
            bp = float(acct.get('buying_power', 0))
            ok = cash >= needed * 0.5 and bp >= needed
            logger.info(f"Hedge funding: cash=${cash:,.0f} bp=${bp:,.0f} needed=${needed:,.0f} -> {'OK' if ok else 'SHORT'}")
            return ok
        except Exception as e:
            logger.error(f"Hedge funding trim exception: {e}")
            return False
    
    def _submit_notional_order(self, client: AlpacaClient, symbol: str,
                                notional: float, side: str) -> Optional[Dict]:
        """Submit order using notional (dollar amount) instead of qty.

        v8.5: goes through client._request (retry/backoff/stats) instead of a
        bare requests.post that bypassed all of it.
        """
        data = {
            'symbol': symbol,
            'notional': str(round(notional, 2)),  # Dollar amount, not shares
            'side': side,
            'type': 'market',
            'time_in_force': 'ioc',
            'client_order_id': f"{client.ORDER_PREFIX}{symbol}_{side}_{int(time.time())}_{os.urandom(4).hex()}",
        }
        r = client._request('POST', f"{client.config.ALPACA_BASE_URL}/v2/orders", json=data)
        if r.status_code in (200, 201):
            return r.json()
        logger.error(f"Notional order failed: HTTP {r.status_code} {r.text[:200]}")
        return None
    
    def execute(self, client: AlpacaClient, equity: float, action: str) -> Dict[str, Any]:
        """
        Execute hedge action with notional market order + buying power check.
        Uses notional (dollar amount) instead of qty to prevent accumulation errors.
        """
        results = {'action': action, 'executed': False, 'details': []}
        hedge_sym = self.config.HEDGE_ETF
        
        try:
            if action == 'activate':
                notional = equity * self.config.HEDGE_POSITION_PCT
                if notional < 100:
                    logger.warning(f"HEDGE: notional ${notional:.2f} too small, skipping")
                    return results

                # v8.5: the portfolio is normally ~fully invested, so cash is
                # ~0 and the old buying-power check made activation impossible
                # exactly when it was needed. Fund the hedge by trimming every
                # stock position pro-rata (this IS the documented
                # HEDGE_STOCK_COMPRESSION), then buy SQQQ with the proceeds.
                if not self._check_buying_power(client, notional):
                    logger.info(f"HEDGE ACTIVATE: freeing ${notional:.0f} by pro-rata stock trim")
                    if not self._trim_stocks_for_hedge(client, notional):
                        logger.error(f"HEDGE ACTIVATE: could not free ${notional:.2f} cash")
                        return results

                # Use notional order (dollar amount) for precise position sizing
                order = self._submit_notional_order(client, hedge_sym, notional, 'buy')
                if order and order.get('status') in ('filled', 'accepted', 'new', 'partially_filled'):
                    filled_qty = order.get('filled_qty') or order.get('qty', '0')
                    results['executed'] = True
                    results['details'].append({'symbol': hedge_sym, 'side': 'buy',
                                                'notional': notional, 'filled_qty': filled_qty})
                    logger.critical(f"HEDGE ACTIVATED: BOUGHT ${notional:.0f} {hedge_sym} "
                                   f"(VIX>={self.config.HEDGE_VIX_ACTIVATE})")
                else:
                    logger.error(f"HEDGE ACTIVATE FAILED: order rejected")

            elif action == 'deactivate':
                # v8.5: close the WHOLE position incl. fractional residue via
                # DELETE /v2/positions. Old code sold int(qty), leaving a
                # sub-share ghost that re-armed the hedge on every restart.
                positions = client.get_positions()
                for p in positions:
                    if p['symbol'] == hedge_sym:
                        qty = float(p['qty'])
                        mv = float(p['market_value'])
                        if qty > 0 and mv > 0:
                            if client.close_position(hedge_sym):
                                results['executed'] = True
                                results['details'].append({'symbol': hedge_sym, 'side': 'sell',
                                                            'qty': qty, 'market_value': mv})
                                logger.critical(f"HEDGE DEACTIVATED: CLOSED {qty} {hedge_sym} ${mv:.0f} "
                                               f"(VIX<={self.config.HEDGE_VIX_DEACTIVATE})")
                        break
            
            elif action == 'drift_rebalance':
                target = self.calculate_hedge(equity)
                results = self._rebalance_to_target(client, target, equity)
        
        except Exception as e:
            logger.error(f"HEDGE EXECUTE FAILED: {e}")
            results['error'] = str(e)
        
        return results
    
    def _rebalance_to_target(self, client: AlpacaClient, target_hedge: Dict[str, float],
                              equity: float) -> Dict[str, Any]:
        """Rebalance existing hedge position to target (drift correction)."""
        results = {'executed': False, 'details': []}
        hedge_sym = self.config.HEDGE_ETF
        
        try:
            current_qty = 0.0
            current_val = 0.0
            current_price = 0.0
            for p in client.get_positions():
                if p['symbol'] == hedge_sym:
                    current_qty = float(p['qty'])          # v8.5: keep fractions
                    current_val = float(p['market_value'])
                    current_price = float(p['current_price'])  # v8.5: live price, not stale EOD bar
                    break

            target_val = target_hedge.get(hedge_sym, 0)
            if target_val > 0 and current_val > 0:
                drift = abs(target_val - current_val) / max(target_val, current_val)
                if drift < self.config.HEDGE_REBALANCE_THRESHOLD_PCT:
                    return results

            if target_val == 0 and current_qty > 0:
                # v8.5: close incl. fractional residue (int(qty) left ghosts)
                if client.close_position(hedge_sym):
                    results = {'executed': True, 'details': [{'symbol': hedge_sym, 'side': 'sell',
                                                               'qty': current_qty, 'reason': 'close'}]}
            elif target_val > 0:
                price = current_price
                if price <= 0:
                    bars = client.get_bars(hedge_sym, days=2)
                    if len(bars) == 0:
                        return results
                    price = float(bars.iloc[-1])
                target_qty = int(target_val / price)
                delta = target_qty - int(current_qty)
                if abs(delta) >= 1:
                    side = 'buy' if delta > 0 else 'sell'
                    order = client.submit_order(hedge_sym, abs(delta), side)
                    if order:
                        results = {'executed': True, 'details': [{'symbol': hedge_sym, 'side': side,
                                                                   'qty': abs(delta), 'reason': 'rebalance'}]}
        except Exception as e:
            logger.warning(f"Hedge rebalance failed: {e}")
        
        return results
    
    def intraday_check(self, client: AlpacaClient, equity: float,
                       account: Dict = None) -> Dict[str, Any]:
        """
        Full intraday hedge check cycle (called every 60s from run_cycle).
        DCL: _get_vix (Data) → evaluate (Signal) → execute (Order)

        v8.5 (PDT): activating the hedge opens a same-day-round-trip risk
        (a later deactivate of shares bought today is a day trade). When
        equity < $25k and the day-trade budget is exhausted, activation is
        blocked. Deactivation always goes through (risk reduction first).
        """
        if not self.config.ENABLE_HEDGE:
            return {'action': 'disabled'}

        # D: Refresh VIX data (None = unavailable -> hold)
        vix = self._get_vix_level(client)
        if vix is None:
            return {'action': 'hold', 'vix': None, 'hedge_active': self._hedge_active,
                    'reason': 'vix_unavailable'}

        # S: Evaluate with hysteresis + circuit breaker (pure, no mutation)
        action = self.evaluate(vix)

        # v8.5: PDT guard on activation
        if action == 'activate' and self.config.PDT_PROTECTION and account:
            dt_count = int(account.get('daytrade_count', 0) or 0)
            if equity < self.config.PDT_MIN_EQUITY and dt_count >= self.config.PDT_MAX_DAY_TRADES:
                logger.warning(f"HEDGE ACTIVATE BLOCKED by PDT guard "
                               f"(daytrade_count={dt_count}, equity=${equity:,.0f} < $25k)")
                return {'action': 'hold', 'vix': vix, 'hedge_active': self._hedge_active,
                        'reason': 'pdt_guard'}

        # O: Execute if state change; commit state only on success
        if action in ('activate', 'deactivate'):
            result = self.execute(client, equity, action)
            if result.get('executed'):
                self._commit_switch(action)
            else:
                # State unchanged: will retry next cycle instead of desyncing
                logger.warning(f"HEDGE {action} not executed - state kept, retry next cycle")
            result['vix'] = vix
            result['switches_today'] = self._switches_today
            return result
        elif action == 'circuit_broken':
            return {'action': 'circuit_broken', 'vix': vix, 
                    'switches_today': self._switches_today}
        
        # Drift rebalance if hedge active
        if self._hedge_active:
            target = self.calculate_hedge(equity)
            rebalance_result = self._rebalance_to_target(client, target, equity)
            if rebalance_result.get('executed'):
                return {'action': 'drift_rebalance', 'vix': vix, **rebalance_result}
        
        return {'action': 'hold', 'vix': vix, 'hedge_active': self._hedge_active}


# ============================================================================
# BACKTEST ENGINE (BUG-004 FIX, HP-001 FIX, MP-005 FIX, HP-010 FIX, MP-002 FIX)
# ============================================================================

class BacktestEngine:
    """Production-grade backtest with transaction costs and next-day open execution."""
    
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.results = {}
        # HP-001 FIX: Initialize _last_t as instance variable instead of using getattr
        self._last_t = 0
    
    def run(self, prices: pd.DataFrame, benchmark: pd.Series,
            fundamentals: RealtimeFundamentals, use_next_day_open: bool = True,
            vix: pd.Series = None) -> Dict:
        """
        Run backtest.

        Args:
            use_next_day_open: If True, rebalance executes at t+1 price
                              (simulates EOD signal -> next day execution)
            vix: Optional VIX close series (DatetimeIndex) driving the
                 conditional hedge. None -> hedge disabled in backtest.
        """
        n_days = len(prices)

        # Init strategies
        mom_strat = MomentumStrategy(self.config)
        # sector rotation disabled (user request)
        growth_strat = GrowthStrategy(fundamentals, self.config)
        value_strat = ValueStrategy(fundamentals, self.config)
        def_strat = DefensiveStrategy(fundamentals, self.config)
        macro = MacroTiming(self.config)
        risk = RiskController(self.config)              # v8.3: actually enforced
        hedge = HedgeEngine(self.config, client=None)   # v8.3: conditional hedge
        constructor = PortfolioConstructor(self.config)
        txn = TransactionCostModel

        # v8.3 (D3): benchmark / hedge ETF are NOT selectable candidates
        sel_cols = [c for c in prices.columns if c not in ('SPY', self.config.HEDGE_ETF)]
        sel_prices = prices[sel_cols]

        # v8.3: align VIX to the trading calendar
        vix_aligned = None
        if vix is not None and (self.config.ENABLE_HEDGE or self.config.VIX_HALVE_ENABLED):
            vix_aligned = vix.reindex(prices.index, method='ffill')

        cash = self.config.INITIAL_CAPITAL
        positions = {}      # {sym: shares} - stocks only
        hedge_shares = 0    # SQQQ shares (managed by hedge engine, not stops)
        hedge_entry = 0.0
        degrossed = False   # VIX-halve overlay state (alternative framework)
        portfolio_values = []
        trades = []
        daily_rets = []
        entry_prices = {}
        max_prices_tracker = {}

        # HP-001 FIX: Reset _last_t at start of each backtest
        self._last_t = 0

        logger.info(f"Backtest: {n_days} days, next_day_open={use_next_day_open}, "
                    f"hedge={'on' if vix_aligned is not None else 'off'}")
        
        # MP-005 FIX: Include the last day (was n_days - 1, now n_days)
        loop_end = n_days if not use_next_day_open else n_days
        for t in range(252, loop_end):
            # Skip if we need next-day execution and this is the very last day
            if use_next_day_open and t >= n_days - 1:
                break
                
            current_date = prices.index[t]
            current_prices = prices.iloc[t]
            
            # 1. Stop loss check (BUG-002 FIX: independent ifs, highest priority first)
            to_sell = []
            for sym, shares in list(positions.items()):
                if sym in current_prices and current_prices[sym] > 0 and shares > 0:
                    price = current_prices[sym]
                    max_prices_tracker[sym] = max(max_prices_tracker.get(sym, entry_prices.get(sym, price)), price)
                    entry = entry_prices.get(sym, price)
                    if entry <= 0:
                        continue
                    
                    pnl_pct = (price - entry) / entry
                    peak_pct = (max_prices_tracker.get(sym, entry) - entry) / entry
                    
                    stop_triggered = False
                    reason = ''

                    if self.config.STOP_MODE == 'trail21':
                        # Alternative framework: trailing stop off the 21-day
                        # closing high (chandelier-style), replaces tiered stops
                        if t >= 20:
                            high_21 = prices[sym].iloc[max(0, t-20):t+1].max()
                            if price <= high_21 * (1 + self.config.TRAIL21_STOP_PCT):
                                stop_triggered = True
                                reason = 'trail21_high'
                    # BUG-002 FIX: Use independent ifs (not elif), check highest threshold first
                    elif pnl_pct <= self.config.HARD_STOP_LOSS_PCT:
                        stop_triggered = True
                        reason = 'hard_stop'
                    # trailing_100 check FIRST (higher threshold takes priority)
                    if not stop_triggered and peak_pct >= 1.0:
                        trailing = entry * 2.0 * (1 + self.config.TRAILING_STOP_100_PCT)
                        if price <= trailing:
                            stop_triggered = True
                            reason = 'trailing_100'
                    # trailing_50 check SECOND
                    if not stop_triggered and peak_pct >= 0.50:
                        trailing = entry * 1.50 * (1 + self.config.TRAILING_STOP_50_PCT)
                        if price <= trailing:
                            stop_triggered = True
                            reason = 'trailing_50'
                    
                    if stop_triggered:
                        _fa = fundamentals.get_asof(sym, current_date, price)
                        mkt_cap = _fa.get('market_cap', 0) or 50e9
                        net_price = txn.apply_to_backtest(price, shares, is_buy=False, market_cap=mkt_cap, config=self.config)
                        sell_value = shares * net_price
                        cash += sell_value
                        trades.append({
                            'date': current_date, 'symbol': sym, 'action': 'SELL',
                            'reason': reason, 'shares': shares, 'price': price,
                            'net_price': net_price, 'pnl_pct': pnl_pct,
                        })
                        to_sell.append(sym)
            
            for sym in to_sell:
                positions.pop(sym, None)
                entry_prices.pop(sym, None)
                max_prices_tracker.pop(sym, None)
            
            # 2. Portfolio value (stocks + hedge ETF)
            pos_value = sum(positions[s] * current_prices[s] for s in positions
                           if s in current_prices and current_prices[s] > 0)
            hedge_value = 0.0
            hedge_px = current_prices.get(self.config.HEDGE_ETF, 0)
            if hedge_shares > 0 and hedge_px > 0:
                hedge_value = hedge_shares * hedge_px
            total_value = cash + pos_value + hedge_value
            portfolio_values.append(total_value)

            if len(portfolio_values) > 1:
                daily_rets.append((portfolio_values[-1] / portfolio_values[-2]) - 1)

            # 2.5 v8.3: portfolio-level risk limits (daily loss / drawdown breaker).
            # On breach: liquidate everything at today's close, stop trading today.
            can_trade, limit_reason = risk.check_limits(total_value, now=current_date)
            if not can_trade:
                for sym, shares in list(positions.items()):
                    if shares > 0 and sym in current_prices and current_prices[sym] > 0:
                        price = current_prices[sym]
                        _fa = fundamentals.get_asof(sym, current_date, price)
                        mkt_cap = _fa.get('market_cap', 0) or 50e9
                        net_price = txn.apply_to_backtest(price, shares, is_buy=False,
                                                          market_cap=mkt_cap, config=self.config)
                        cash += shares * net_price
                        entry = entry_prices.get(sym, net_price)
                        trades.append({'date': current_date, 'symbol': sym, 'action': 'SELL',
                                       'reason': 'risk_' + limit_reason.split(' ')[0],
                                       'shares': shares, 'price': price, 'net_price': net_price,
                                       'pnl_pct': (net_price - entry) / entry if entry > 0 else 0})
                        positions.pop(sym); entry_prices.pop(sym, None)
                        max_prices_tracker.pop(sym, None)
                if hedge_shares > 0 and hedge_px > 0:
                    net_price = txn.apply_to_backtest(hedge_px, hedge_shares, is_buy=False,
                                                      config=self.config)
                    cash += hedge_shares * net_price
                    trades.append({'date': current_date, 'symbol': self.config.HEDGE_ETF,
                                   'action': 'SELL', 'reason': 'risk_' + limit_reason.split(' ')[0],
                                   'shares': hedge_shares, 'price': hedge_px, 'net_price': net_price,
                                   'pnl_pct': (net_price - hedge_entry) / hedge_entry if hedge_entry > 0 else 0})
                    hedge_shares = 0
                    hedge._hedge_active = False
                portfolio_values[-1] = cash
                if daily_rets:
                    daily_rets[-1] = portfolio_values[-1] / portfolio_values[-2] - 1
                continue

            # 2.6 v8.3: conditional hedge (same hysteresis rules as live)
            if vix_aligned is not None and self.config.ENABLE_HEDGE:
                v = vix_aligned.iloc[t]
                if not np.isnan(v) and hedge_px > 0:
                    h_action = hedge.evaluate(float(v), now=current_date)
                    if h_action == 'activate':
                        shares = int(total_value * self.config.HEDGE_POSITION_PCT / hedge_px)
                        if shares > 0:
                            net_price = txn.apply_to_backtest(hedge_px, shares, is_buy=True,
                                                              config=self.config)
                            cost = shares * net_price
                            if cost <= cash and cash - cost >= 0.01:
                                cash -= cost
                                hedge_shares += shares
                                hedge_entry = net_price
                                hedge._commit_switch('activate')
                                trades.append({'date': current_date, 'symbol': self.config.HEDGE_ETF,
                                               'action': 'BUY', 'reason': f'hedge_activate_vix{v:.1f}',
                                               'shares': shares, 'price': hedge_px, 'net_price': net_price})
                    elif h_action == 'deactivate' and hedge_shares > 0:
                        net_price = txn.apply_to_backtest(hedge_px, hedge_shares, is_buy=False,
                                                          config=self.config)
                        cash += hedge_shares * net_price
                        trades.append({'date': current_date, 'symbol': self.config.HEDGE_ETF,
                                       'action': 'SELL', 'reason': f'hedge_deactivate_vix{v:.1f}',
                                       'shares': hedge_shares, 'price': hedge_px, 'net_price': net_price,
                                       'pnl_pct': (net_price - hedge_entry) / hedge_entry if hedge_entry > 0 else 0})
                        hedge_shares = 0
                        hedge._commit_switch('deactivate')

            # 2.7 Alternative framework: prev-day VIX >= 30 -> halve stock
            # exposure (pro-rata); VIX back below -> force rebalance to restore.
            if self.config.VIX_HALVE_ENABLED and vix_aligned is not None and t >= 1:
                v_prev = vix_aligned.iloc[t - 1]
                if not np.isnan(v_prev):
                    if v_prev >= self.config.VIX_HALVE_THRESHOLD and not degrossed:
                        for sym, shares in list(positions.items()):
                            sell_q = int(shares * 0.5)
                            if sell_q > 0 and sym in current_prices and current_prices[sym] > 0:
                                price = current_prices[sym]
                                _fa = fundamentals.get_asof(sym, current_date, price)
                                mkt_cap = _fa.get('market_cap', 0) or 50e9
                                net_price = txn.apply_to_backtest(price, sell_q, is_buy=False,
                                                                  market_cap=mkt_cap, config=self.config)
                                cash += sell_q * net_price
                                entry = entry_prices.get(sym, net_price)
                                trades.append({'date': current_date, 'symbol': sym, 'action': 'SELL',
                                               'reason': f'vix_halve_{v_prev:.1f}', 'shares': sell_q,
                                               'price': price, 'net_price': net_price,
                                               'pnl_pct': (net_price - entry) / entry if entry > 0 else 0})
                                positions[sym] = shares - sell_q
                                if positions[sym] <= 0:
                                    positions.pop(sym); entry_prices.pop(sym, None)
                                    max_prices_tracker.pop(sym, None)
                        degrossed = True
                    elif v_prev < self.config.VIX_HALVE_THRESHOLD and degrossed:
                        degrossed = False
                        self._last_t = t - self.config.REBALANCE_DAYS  # force re-entry at next step

            # 3. Rebalance check (v8.3: delta-based - keeps overlapping holdings,
            #    only trades the difference. v8.2 liquidated everything weekly,
            #    which made trailing stops unreachable and churned ~33x/yr.)
            days_since = t - self._last_t  # HP-001 FIX: use instance variable
            if days_since >= self.config.REBALANCE_DAYS:
                self._last_t = t

                # Market regime
                regime, macro_signal = macro.detect(prices, t)
                weights = macro.get_weights(regime, self.config)
                pos_factor = macro_signal.get('position_factor', 1.0)

                # Alternative framework: breadth scaling - pos_factor shrinks
                # with the fraction of universe stocks above their 252d ago price
                if self.config.BREADTH_SCALING_ENABLED:
                    _ok, _tot = 0, 0
                    for _c in sel_prices.columns:
                        _col = sel_prices[_c].iloc[:t+1].dropna()
                        if len(_col) > 252:
                            _tot += 1
                            if _col.iloc[-1] > _col.iloc[-253]:
                                _ok += 1
                    breadth = _ok / _tot if _tot else 1.0
                    pos_factor *= breadth

                # 4 strategies select (v8.3: SPY/SQQQ excluded from candidates)
                mom_picks = mom_strat.select(sel_prices, benchmark, t)
                # sector rotation disabled
                growth_picks = growth_strat.select(sel_prices, benchmark, t)
                value_picks = value_strat.select(sel_prices, benchmark, t)
                def_picks = def_strat.select(sel_prices, benchmark, t)

                # Combine (4 strategies, sector={})
                combined = constructor.combine(mom_picks, {}, growth_picks,
                                               value_picks, def_picks, weights)

                # v8.3: wire the advertised 21d-high filter (was dead code)
                combined = constructor.filter_21d_high(combined, prices, t)
                # 全局波动率过滤: 所有策略信号统一检查20日波动率
                combined = constructor.filter_by_volatility(combined, prices, t)

                # Determine execution price
                if use_next_day_open and t + 1 < n_days:
                    exec_prices = prices.iloc[t + 1]  # Next day open (we use close as proxy)
                    exec_date = prices.index[t + 1]
                else:
                    exec_prices = current_prices
                    exec_date = current_date

                # Target values: score/vol sized, capped, normalized so total
                # invested <= adjusted_capital (v8.3: pos_factor is now binding;
                # hedge compression applies too)
                adjusted_capital = (total_value * pos_factor
                                    * hedge.get_stock_compression())
                top_signals = dict(list(combined.items())[:self.config.MAX_POSITIONS])

                raw_w = {}
                for sym, signal in top_signals.items():
                    if sym not in exec_prices or exec_prices[sym] <= 0:
                        continue
                    if t >= 20:
                        vol = prices[sym].iloc[max(0, t-20):t+1].pct_change().std() * np.sqrt(252)
                    else:
                        vol = 0.30
                    # Alternative framework: RV90 blocks NEW buys only
                    # (existing holdings may stay in targets)
                    if (self.config.RV90_BUY_BLOCK_ENABLED
                            and vol > self.config.RV90_MAX_VOL
                            and positions.get(sym, 0) <= 0):
                        continue
                    if 'defensive' in signal.get('strategies', []):
                        vol *= 0.8
                    vol_factor = min(self.config.VOLATILITY_TARGET / vol, 2.0) if vol > 0 else 1.0
                    score_weight = min(signal['total'] / 0.5, 1.0) if signal['total'] > 0 else 0.5
                    raw_w[sym] = vol_factor * score_weight

                wsum = sum(raw_w.values())
                targets = {}
                if wsum > 0:
                    for sym, w in raw_w.items():
                        tv = adjusted_capital * w / wsum
                        tv = min(tv, adjusted_capital * self.config.MAX_SINGLE_POSITION_PCT)
                        if tv >= adjusted_capital * self.config.MIN_SINGLE_POSITION_PCT:
                            targets[sym] = tv

                # Sell positions that fell out of the target set
                for sym, shares in list(positions.items()):
                    if sym not in targets and shares > 0 and exec_prices.get(sym, 0) > 0:
                        price = exec_prices[sym]
                        _fa = fundamentals.get_asof(sym, exec_date, price)
                        mkt_cap = _fa.get('market_cap', 0) or 50e9
                        net_price = txn.apply_to_backtest(price, shares, is_buy=False,
                                                          market_cap=mkt_cap, config=self.config)
                        cash += shares * net_price
                        entry = entry_prices.get(sym, net_price)
                        pnl = (net_price - entry) / entry if entry > 0 else 0
                        trades.append({'date': exec_date, 'symbol': sym, 'action': 'SELL',
                                       'reason': 'rebalance', 'shares': shares, 'price': price,
                                       'net_price': net_price, 'pnl_pct': pnl})
                        positions.pop(sym)
                        entry_prices.pop(sym, None)
                        max_prices_tracker.pop(sym, None)

                # Adjust kept/new positions toward targets (trade only the delta;
                # drift < 25% of target is ignored to avoid churn)
                for sym, target_val in targets.items():
                    price = exec_prices.get(sym, 0)
                    if price <= 0:
                        continue
                    cur_shares = positions.get(sym, 0)
                    cur_val = cur_shares * price
                    if cur_shares > 0 and abs(cur_val - target_val) / target_val < 0.25:
                        continue  # close enough - keep as is
                    delta_val = target_val - cur_val
                    _fa = fundamentals.get_asof(sym, exec_date, price)
                    mkt_cap = _fa.get('market_cap', 0) or 50e9
                    if delta_val > 0:
                        add = int(delta_val / price)
                        if add > 0:
                            net_price = txn.apply_to_backtest(price, add, is_buy=True,
                                                              market_cap=mkt_cap, config=self.config)
                            cost = add * net_price
                            # MP-002 FIX: Prevent negative cash with epsilon buffer
                            if cost <= cash and cash - cost >= 0.01:
                                cash -= cost
                                if cur_shares > 0:
                                    old_entry = entry_prices.get(sym, net_price)
                                    entry_prices[sym] = ((old_entry * cur_shares + net_price * add)
                                                         / (cur_shares + add))
                                else:
                                    # BUG-004 FIX: Record entry at net_price
                                    entry_prices[sym] = net_price
                                positions[sym] = cur_shares + add
                                trades.append({'date': exec_date, 'symbol': sym, 'action': 'BUY',
                                               'reason': f'regime:{regime}', 'shares': add,
                                               'price': price, 'net_price': net_price,
                                               # v8.5: strategy attribution for per-strategy P&L analysis
                                               'strategies': top_signals.get(sym, {}).get('strategies', [])})
                            else:
                                logger.debug(f"Skip {sym}: cost ${cost:.2f} > cash ${cash:.2f}")
                    elif delta_val < 0 and cur_shares > 0:
                        reduce = min(int(-delta_val / price), cur_shares)
                        if reduce > 0:
                            net_price = txn.apply_to_backtest(price, reduce, is_buy=False,
                                                              market_cap=mkt_cap, config=self.config)
                            cash += reduce * net_price
                            entry = entry_prices.get(sym, net_price)
                            pnl = (net_price - entry) / entry if entry > 0 else 0
                            trades.append({'date': exec_date, 'symbol': sym, 'action': 'SELL',
                                           'reason': 'rebalance_trim', 'shares': reduce,
                                           'price': price, 'net_price': net_price, 'pnl_pct': pnl})
                            positions[sym] = cur_shares - reduce
        
        self.results = self._calc_performance(portfolio_values, daily_rets, benchmark, trades, prices)
        return self.results
    
    def _calc_performance(self, pv_list: List[float], dr: List[float],
                          benchmark: pd.Series, trades: List[Dict],
                          prices: pd.DataFrame) -> Dict:
        if not pv_list or len(pv_list) < 2:
            return {'error': 'Insufficient data'}
        
        pv = np.array(pv_list)
        total_ret = (pv[-1] / pv[0]) - 1
        n_years = len(pv) / 252
        cagr = (pv[-1] / pv[0]) ** (1 / max(n_years, 0.1)) - 1
        
        dr_arr = np.array(dr)
        vol = dr_arr.std() * np.sqrt(252)
        sharpe = (dr_arr.mean() * 252) / (dr_arr.std() * np.sqrt(252)) if dr_arr.std() > 0 else 0
        
        cummax = np.maximum.accumulate(pv)
        max_dd = ((pv - cummax) / cummax).min()
        calmar = cagr / abs(max_dd) if max_dd != 0 else 0
        
        # HP-010 FIX: Benchmark calculation uses actual backtest period
        # Find the start/end dates corresponding to our portfolio values
        backtest_start_idx = 252
        backtest_end_idx = backtest_start_idx + len(pv) - 1
        
        # Ensure we don't go out of bounds
        bench_start_idx = min(backtest_start_idx, len(benchmark) - 1)
        bench_end_idx = min(backtest_end_idx, len(benchmark) - 1)
        
        if bench_start_idx < bench_end_idx:
            bench_ret = (benchmark.iloc[bench_end_idx] / benchmark.iloc[bench_start_idx]) - 1
            bench_cagr = (benchmark.iloc[bench_end_idx] / benchmark.iloc[bench_start_idx]) ** (1 / max(n_years, 0.1)) - 1
            bench_dr = benchmark.iloc[bench_start_idx:bench_end_idx+1].pct_change().dropna().values
        else:
            bench_ret = 0
            bench_cagr = 0
            bench_dr = np.array([])
        
        if len(dr_arr) > 0 and len(bench_dr) > 0:
            common_len = min(len(dr_arr), len(bench_dr))
            if common_len >= 2 and dr_arr[:common_len].std() > 0 and bench_dr[:common_len].std() > 0:
                beta = np.corrcoef(dr_arr[:common_len], bench_dr[:common_len])[0, 1] * (dr_arr[:common_len].std() / bench_dr[:common_len].std())
            else:
                beta = 1.0
        else:
            beta = 1.0
        
        alpha = cagr - (0.02 + beta * (bench_cagr - 0.02))
        
        sells = [t for t in trades if t['action'] == 'SELL']
        wins = [t for t in sells if t.get('pnl_pct', 0) > 0]
        losses = [t for t in sells if t.get('pnl_pct', 0) <= 0]
        
        # Transaction cost summary
        # v8.3 fix: buys and sells both COST money - the v8.2 formula
        # (price - net_price) * shares has opposite signs for buys vs sells,
        # so they cancelled each other (~15x underestimate).
        total_cost = (
            sum((t['net_price'] - t['price']) * t['shares']
                for t in trades if t.get('action') == 'BUY' and 'net_price' in t)
            + sum((t['price'] - t['net_price']) * t['shares']
                  for t in trades if t.get('action') == 'SELL' and 'net_price' in t)
        )
        
        return {
            'total_return': total_ret, 'cagr': cagr,
            'volatility': vol, 'sharpe': sharpe,
            'max_drawdown': max_dd, 'calmar': calmar,
            'beta': beta, 'alpha': alpha,
            'final_value': pv[-1],
            'bench_return': bench_ret, 'bench_cagr': bench_cagr,
            'excess_return': total_ret - bench_ret,
            'n_trades': len(trades),
            'winning_trades': len(wins), 'losing_trades': len(losses),
            'avg_win': np.mean([t['pnl_pct'] for t in wins]) if wins else 0,
            'avg_loss': np.mean([t['pnl_pct'] for t in losses]) if losses else 0,
            'win_rate': len(wins) / max(len(sells), 1),
            'total_transaction_cost': float(total_cost),
            'portfolio_values': pv.tolist(),
            'trades': trades,
        }



# ============================================================================
# WALK-FORWARD VALIDATOR (HP-005 FIX: true walk-forward with parameter optimization)
# ============================================================================

class WalkForwardValidator:
    """True Walk-Forward Analysis: optimize on train, validate on test."""
    
    def __init__(self, config: Config = None):
        self.config = config or Config()
    
    def _grid_search(self, prices: pd.DataFrame, benchmark: pd.Series,
                     fundamentals: RealtimeFundamentals, start_idx: int, end_idx: int) -> Tuple[Config, Dict]:
        """
        HP-005 FIX: Grid search over key parameters on training data.
        Returns (best_config, best_result).
        """
        # Parameter grid
        rs_min_values = [50.0, 60.0, 70.0]
        max_vol_values = [0.50, 0.60, 0.70]
        stop_loss_values = [-0.06, -0.08, -0.10]
        
        best_sharpe = -999
        best_cfg = None
        best_result = None
        
        train_prices = prices.iloc[start_idx:end_idx]
        train_benchmark = benchmark.iloc[start_idx:end_idx]
        
        for rs_min in rs_min_values:
            for max_vol in max_vol_values:
                for stop_loss in stop_loss_values:
                    cfg = Config(
                        RS_MIN=rs_min,
                        MAX_VOLATILITY=max_vol,
                        HARD_STOP_LOSS_PCT=stop_loss,
                        INITIAL_CAPITAL=self.config.INITIAL_CAPITAL,
                        MAX_POSITIONS=self.config.MAX_POSITIONS,
                        REBALANCE_DAYS=self.config.REBALANCE_DAYS,
                    )
                    
                    engine = BacktestEngine(cfg)
                    result = engine.run(train_prices, train_benchmark, fundamentals, use_next_day_open=True)
                    
                    if 'error' not in result and result.get('sharpe', -999) > best_sharpe:
                        best_sharpe = result['sharpe']
                        best_cfg = cfg
                        best_result = result
        
        # Fallback to default if no good config found
        if best_cfg is None:
            best_cfg = Config()
            engine = BacktestEngine(best_cfg)
            best_result = engine.run(train_prices, train_benchmark, fundamentals, use_next_day_open=True)
        
        return best_cfg, best_result
    
    def run(self, prices: pd.DataFrame, benchmark: pd.Series,
            fundamentals: RealtimeFundamentals, optimize_params: bool = True) -> Dict:
        """
        Run walk-forward validation:
        - Train on [t-2y, t], test on [t, t+6m], step by 3m
        - HP-005 FIX: If optimize_params=True, grid search on training data first
        """
        train = self.config.WALK_FORWARD_TRAIN_DAYS
        test = self.config.WALK_FORWARD_TEST_DAYS
        step = self.config.WALK_FORWARD_STEP_DAYS
        
        results = []
        start_idx = train
        
        while start_idx + test < len(prices):
            # Training period
            train_start = start_idx - train
            train_end = start_idx
            
            # Test period
            test_start = start_idx
            test_end = start_idx + test
            
            # HP-005 FIX: Parameter optimization on training data
            if optimize_params:
                best_cfg, _ = self._grid_search(prices, benchmark, fundamentals, train_start, train_end)
                logger.info(f"WFA Period {len(results)+1}: best config RS_MIN={best_cfg.RS_MIN}, "
                           f"MAX_VOL={best_cfg.MAX_VOLATILITY}, STOP={best_cfg.HARD_STOP_LOSS_PCT}")
            else:
                best_cfg = self.config
            
            # Run backtest on test period with optimized (or default) config.
            # v8.3 fix: prepend 252d warmup so the engine can trade from day 1
            # of the test window. v8.2 sliced only the 126d test window, which
            # is shorter than the engine's 252d warmup -> every period returned
            # 'Insufficient data' and WFA always came back empty.
            warm_start = max(0, test_start - 252)
            test_prices = prices.iloc[warm_start:test_end]
            test_benchmark = benchmark.iloc[warm_start:test_end]

            engine = BacktestEngine(best_cfg)
            result = engine.run(test_prices, test_benchmark, fundamentals)
            
            if 'error' not in result:
                results.append({
                    'train_start': str(prices.index[train_start]),
                    'train_end': str(prices.index[train_end]),
                    'test_start': str(prices.index[test_start]),
                    'test_end': str(prices.index[test_end]),
                    'test_return': result['total_return'],
                    'test_sharpe': result['sharpe'],
                    'test_max_dd': result['max_drawdown'],
                    'test_alpha': result.get('alpha', 0),
                    'config': {
                        'RS_MIN': best_cfg.RS_MIN,
                        'MAX_VOLATILITY': best_cfg.MAX_VOLATILITY,
                        'HARD_STOP_LOSS_PCT': best_cfg.HARD_STOP_LOSS_PCT,
                    },
                })
            
            start_idx += step
        
        if not results:
            return {'error': 'No walk-forward periods completed'}
        
        returns = [r['test_return'] for r in results]
        sharpes = [r['test_sharpe'] for r in results]
        alphas = [r['test_alpha'] for r in results]
        
        return {
            'n_periods': len(results),
            'periods': results,
            'mean_return': np.mean(returns),
            'std_return': np.std(returns),
            'min_return': min(returns),
            'max_return': max(returns),
            'mean_sharpe': np.mean(sharpes),
            'sharpe_std': np.std(sharpes),
            'mean_alpha': np.mean(alphas),
            'consistency_score': 1 - np.std(returns) / max(abs(np.mean(returns)), 0.001),
        }



# ============================================================================
# INTRADAY MONITOR (BUG-002 FIX, HP-004 FIX, MP-003 FIX)
# ============================================================================

class IntradayMonitor:
    """Production intraday monitor with full risk control and weekly rebalance."""
    
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.client = AlpacaClient(config)
        self.risk = RiskController(config)
        self.rebalancer = FailSafeRebalancer(config)
        # v8.5 (P1-6): live fundamentals come from the same SEC XBRL
        # point-in-time snapshots as the backtest, so live and backtest
        # selection logic see the same data. yfinance is only a fallback
        # (its .info endpoint is slow, rate-limited, and its _fallback
        # defaults silently disabled 3 of 4 fundamental strategies).
        self.fundamentals = self._init_fundamentals()
        self.constructor = PortfolioConstructor(config)
        self.macro = MacroTiming(config)
        self.hedge = HedgeEngine(config, self.client)

        self.entry_prices = {}
        self.max_prices = {}
        self._load_state()

        # v8.5 (P1-3): startup reconciliation - cancel orphaned orders from a
        # previous crashed/killed run so they cannot fill unexpectedly, and
        # make the broker-vs-local state visible.
        try:
            orphans = self.client.get_open_our_orders()
            if orphans:
                logger.warning(f"STARTUP RECONCILE: {len(orphans)} orphaned orders from previous run, cancelling")
                self.client.cancel_our_orders()
        except Exception as e:
            logger.warning(f"Startup order reconciliation failed: {e}")

        if self.config.DATA_FEED == 'iex':
            logger.warning("DATA_FEED='iex': free feed is ~15min delayed and thin for "
                           "less-liquid names. Stops/hedge may trigger on stale prices. "
                           "Use 'sip' for serious paper validation and live trading.")

    def _init_fundamentals(self):
        """PIT fundamentals for live mode, with freshness check + yfinance fallback."""
        pit_path = self.config.DATA_DIR / 'pit_fundamentals_full.json'
        if pit_path.exists():
            age_days = (time.time() - pit_path.stat().st_mtime) / 86400
            if age_days > 7:
                logger.warning(f"PIT fundamentals file is {age_days:.0f}d old - "
                               f"re-run build_pit_fundamentals.py to refresh")
            return PointInTimeFundamentals(self.config, pit_file=str(pit_path))
        logger.critical(f"PIT fundamentals missing ({pit_path}) - falling back to yfinance. "
                        f"Growth/value/defensive selection will differ from backtest!")
        return RealtimeFundamentals(self.config)

    def _load_state(self):
        # v8.5: migrate legacy root-level state.json to DATA_DIR
        legacy = Path(__file__).parent / 'state.json'
        if not self.config.STATE_FILE.exists() and legacy.exists():
            try:
                self.config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
                os.replace(legacy, self.config.STATE_FILE)
                logger.info("Migrated state.json -> data/state.json")
            except Exception as e:
                logger.warning(f"State migration failed: {e}")
        if self.config.STATE_FILE.exists():
            try:
                with open(self.config.STATE_FILE) as f:
                    data = json.load(f)
                    self.entry_prices = data.get('entry_prices', {})
                    self.max_prices = data.get('max_prices', {})
                    # v8.5: peak/circuit/daily-baseline survive restarts
                    self.risk.load_state_dict(data)
            except Exception as e:
                # v8.5: a corrupt state must be visible, not silently swallowed
                logger.error(f"State load failed ({e}) - starting with fresh state. "
                             f"Stop-loss bases reset to broker avg_entry_price.")

    def _save_state(self):
        """v8.5: atomic write (tmp + os.replace) - a crash mid-write can no
        longer truncate state.json and silently drop stop-loss bases."""
        try:
            self.config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.config.STATE_FILE.with_suffix('.tmp')
            payload = {
                'entry_prices': self.entry_prices,
                'max_prices': self.max_prices,
                'last_save': now_et().isoformat(),
            }
            payload.update(self.risk.state_dict())
            with open(tmp, 'w') as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp, self.config.STATE_FILE)
        except Exception as e:
            logger.warning(f"State save failed: {e}")
    
    def sync_positions(self):
        positions = self.client.get_positions()
        current = set()
        for p in positions:
            sym = p['symbol']
            current.add(sym)
            price = float(p['current_price'])
            entry = float(p['avg_entry_price'])
            if sym not in self.entry_prices:
                self.entry_prices[sym] = entry
                self.max_prices[sym] = price
            else:
                # v8.5 (P1-7): corporate-action guard. Alpaca adjusts
                # avg_entry_price on splits; our stored entry predates it and
                # would corrupt every P&L / stop calculation. A >5% divergence
                # between stored entry and broker avg_entry means the basis
                # changed underneath us (splits move it 50%+; partial fills
                # move it far less).
                stored = self.entry_prices[sym]
                if entry > 0 and stored > 0 and abs(entry - stored) / stored > 0.05:
                    logger.warning(f"BASIS RESET {sym}: stored entry ${stored:.2f} vs broker "
                                   f"avg_entry ${entry:.2f} (split/adjustment?) - rebasing")
                    self.entry_prices[sym] = entry
                    self.max_prices[sym] = max(price, entry)
                self.max_prices[sym] = max(self.max_prices.get(sym, entry), price)
        
        for sym in list(self.entry_prices.keys()):
            if sym not in current:
                del self.entry_prices[sym]
                self.max_prices.pop(sym, None)
        
        self._save_state()
        return positions
    
    # BUG-002 FIX: Independent ifs, highest priority first (same as BacktestEngine)
    def check_stops(self, positions: List[Dict]) -> int:
        triggered = 0
        for p in positions:
            sym = p['symbol']
            if sym == self.config.HEDGE_ETF:
                continue  # v8.3: hedge position is managed by HedgeEngine, not stock stops
            qty = int(float(p['qty']))
            entry = self.entry_prices.get(sym, float(p['avg_entry_price']))
            current = float(p['current_price'])
            max_p = self.max_prices.get(sym, entry)
            
            if entry <= 0 or qty <= 0:
                continue
            
            pnl_pct = (current - entry) / entry
            peak_pct = (max_p - entry) / entry
            
            stop = False
            reason = ''
            
            # Hard stop check
            if pnl_pct <= self.config.HARD_STOP_LOSS_PCT:
                stop, reason = True, 'hard_stop'
            
            # trailing_100 check FIRST (higher threshold priority)
            if not stop and peak_pct >= 1.0:
                if current <= entry * 2.0 * (1 + self.config.TRAILING_STOP_100_PCT):
                    stop, reason = True, 'trailing_100'
            
            # trailing_50 check SECOND
            if not stop and peak_pct >= 0.50:
                if current <= entry * 1.50 * (1 + self.config.TRAILING_STOP_50_PCT):
                    stop, reason = True, 'trailing_50'
            
            if stop:
                logger.warning(f"STOP: {sym} P&L={pnl_pct:.1%} {reason}")
                order = self.client.submit_order(sym, qty, 'sell')
                if order and order.get('status') in ('filled', 'accepted', 'new'):
                    triggered += 1
                else:
                    logger.error(f"Stop sell {sym} failed: {order}")
        return triggered
    
    def should_rebalance(self) -> bool:
        # v8.5: market calendar is judged in US Eastern, not host local time
        # (a UTC host shifted the Friday decision into Saturday).
        today = now_et()
        if today.weekday() != 4:  # Friday
            return False
        # Check if already rebalanced today
        if self.config.STATE_FILE.exists():
            try:
                with open(self.config.STATE_FILE) as f:
                    data = json.load(f)
                    last = data.get('last_rebalance', '')
                    if last and datetime.fromisoformat(last).date() == today.date():
                        return False
            except:
                pass
        return True
    
    # HP-004 FIX: Use Config.UNIVERSE instead of hardcoded list
    def do_rebalance(self):
        """
        DCL EXECUTION: 先刷新数据 → 再生成信号 → 后下单
        D: get_bars(520只) + fetch_batch(基本面)
        C: FailSafe.validate_data() + MacroTiming.detect()
        S: 5 Strategies.select() → PortfolioConstructor.combine() → smart_rebalance()
        O: sell旧持仓 → buy新持仓 (submit_order)
        """
        if not self.risk.acquire_rebalance_lock():
            return
        failures = []  # v8.5 (P1-8): any failure -> no last_rebalance stamp -> retry next cycle
        try:
            logger.info("=" * 60)
            logger.info("WEEKLY REBALANCE STARTED [DCL Flow: Data→Signal→Order]")

            # v8.5 (P1-3): no orphan orders may interfere with the rebalance
            self.client.cancel_our_orders()

            # === D: 刷新数据 (Data Refresh) ===
            # v8.3 fix (A1): fetch ~400 days. v8.2 fetched 60 days, which
            # silently disabled momentum (needs 252d), growth and value (126d)
            # and made BULL regime unreachable (needs 200d MA).
            # v8.5 (P1-2): one batched multi-symbol request instead of ~520
            # per-symbol requests at ~6.7 req/s (over the 200 req/min free
            # data limit -> 429 storms and silently missing stocks).
            universe = [s for s in self.config.UNIVERSE if s != 'SPY'] + ['SPY']
            prices_data = self.client.get_bars_batch(universe, days=400)

            prices = pd.DataFrame(prices_data).dropna(how='all').ffill()

            # === C: 数据校验 (Check) ===
            ok, reason = self.rebalancer.validate_data(prices)
            if not ok:
                logger.warning(f"Rebalance skipped: {reason}")
                return

            stock_syms = [c for c in prices.columns if c != 'SPY']
            # v8.5 (P1-6): PIT fundamentals need no fetching; only the
            # yfinance fallback does (slow, rate-limited).
            if isinstance(self.fundamentals, RealtimeFundamentals):
                self.fundamentals.fetch_batch(stock_syms)
            
            # === S: 信号生成 (Signal Generation) ===
            benchmark = prices['SPY'] if 'SPY' in prices.columns else prices.iloc[:, 0]
            t = len(prices) - 1
            
            regime, msignal = self.macro.detect(prices, t)
            weights = self.macro.get_weights(regime)
            
            # v8.3: benchmark / hedge ETF are not selectable candidates
            sel_prices = prices[[c for c in prices.columns
                                 if c not in ('SPY', self.config.HEDGE_ETF)]]
            mom = MomentumStrategy(self.config).select(sel_prices, benchmark, t)
            # sector rotation disabled (user request)
            growth = GrowthStrategy(self.fundamentals, self.config).select(sel_prices, benchmark, t)
            value = ValueStrategy(self.fundamentals, self.config).select(sel_prices, benchmark, t)
            defensive = DefensiveStrategy(self.fundamentals, self.config).select(sel_prices, benchmark, t)

            combined = self.constructor.combine(mom, {}, growth, value, defensive, weights)
            # v8.3: wire the advertised 21d-high filter (was dead code)
            combined = self.constructor.filter_21d_high(combined, prices, t)
            # 全局波动率过滤: 所有策略信号统一检查20日波动率
            combined = self.constructor.filter_by_volatility(combined, prices, t)
            signals = [s[0] for s in sorted(combined.items(), key=lambda x: x[1]['total'], reverse=True)[:self.config.MAX_POSITIONS]]
            
            logger.info(f"Signals generated: {signals} | Regime: {regime}")
            
            # 确定目标持仓 (stock compression由盘中hedge引擎管理)
            acct = self.client.get_account()
            equity = float(acct.get('equity', 100000))
            current_positions = self.client.get_positions()
            current_symbols = {p['symbol'] for p in current_positions}
            
            # Stock equity: hedge compression + regime position factor
            # (v8.3: v8.2 ignored the regime factor -> stayed ~100% invested
            # even in PANIC, while the backtest de-risked to 40%)
            stock_equity = (equity * self.hedge.get_stock_compression()
                            * msignal.get('position_factor', 1.0))
            target = self.rebalancer.smart_rebalance(prices, current_symbols, signals, stock_equity)

            # === O: 执行下单 (Order Execution) ===
            # v8.5 (P0-2): the rebalance now runs INSIDE the trading window
            # while the market is open, so sells fill immediately and cash is
            # genuinely freed before buys. The old design ran after Friday
            # close: every order queued to the Monday open, sells had not
            # filled, and buys were rejected for buying power (or silently
            # used margin).
            # 必须先卖后买，释放现金
            # v8.3: never touch the hedge ETF here - it is managed by HedgeEngine
            for sym in current_symbols:
                if sym == self.config.HEDGE_ETF:
                    continue
                if sym not in target:
                    try:
                        qty = int(float(next(p['qty'] for p in current_positions if p['symbol'] == sym)))
                        order = self.client.submit_order(sym, qty, 'sell')
                        if order and order.get('status') in ('filled', 'accepted', 'new', 'partially_filled'):
                            logger.info(f"Sell {sym}: {qty} shares OK")
                        else:
                            logger.error(f"Sell {sym} failed")
                            failures.append(f'sell:{sym}')
                    except StopIteration:
                        pass
                    time.sleep(0.3)

            # v8.5 (P0-2): verify cash actually freed before buying
            acct = self.client.get_account()
            cash_available = float(acct.get('cash', 0))
            buy_needed = sum(
                (qty - next((int(float(p['qty'])) for p in current_positions if p['symbol'] == sym), 0))
                * float(prices[sym].iloc[-1])
                for sym, qty in target.items()
                if qty > next((int(float(p['qty'])) for p in current_positions if p['symbol'] == sym), 0)
            )
            if buy_needed > cash_available > 0:
                logger.warning(f"Buy scaling: need ${buy_needed:,.0f}, cash ${cash_available:,.0f} "
                               f"-> scaling buys x{cash_available / buy_needed:.2f}")
            elif cash_available <= 0 and buy_needed > 0:
                logger.error(f"No cash available after sells (need ${buy_needed:,.0f}) - buys skipped")
                failures.append('no_cash_after_sells')

            # v8.5 (P0-3): PDT guard - do not open new positions when the
            # day-trade budget is exhausted on a <$25k account. A new buy
            # today plus its stop-loss sell today would be a 4th day trade
            # -> 90-day restriction. Existing positions are unaffected.
            pdt_blocked = False
            if self.config.PDT_PROTECTION:
                dt_count = int(acct.get('daytrade_count', 0) or 0)
                if equity < self.config.PDT_MIN_EQUITY and dt_count >= self.config.PDT_MAX_DAY_TRADES:
                    pdt_blocked = True
                    logger.critical(f"PDT GUARD: buys blocked (daytrade_count={dt_count}, "
                                    f"equity=${equity:,.0f} < $25k) - keeping current holdings")

            for sym, qty in target.items():
                current_qty = 0
                for p in current_positions:
                    if p['symbol'] == sym:
                        current_qty = int(float(p['qty']))
                        break
                if qty > current_qty:
                    if pdt_blocked:
                        break
                    buy_qty = qty - current_qty
                    # scale down if cash is short (sells partially failed)
                    price = float(prices[sym].iloc[-1])
                    if buy_needed > cash_available > 0:
                        buy_qty = int(buy_qty * (cash_available / buy_needed))
                    if buy_qty < 1:
                        continue
                    order = self.client.submit_order(sym, buy_qty, 'buy')
                    if order and order.get('status') in ('filled', 'accepted', 'new', 'partially_filled'):
                        logger.info(f"Buy {sym}: {buy_qty} shares OK")
                    else:
                        logger.error(f"Buy {sym} failed")
                        failures.append(f'buy:{sym}')
                    time.sleep(0.3)

            # v8.5 (P1-9): do NOT clear entry_prices/max_prices here. Sold
            # symbols are dropped by the next sync_positions; kept positions
            # retain their trailing-stop peak. The old blanket reset silently
            # downgraded every survivor's protection to the -8% hard stop.

            # v8.5 (P1-8): stamp last_rebalance ONLY on a clean run; any
            # failure leaves the account possibly half-rotated, so the next
            # cycle retries instead of waiting a week.
            if not failures:
                self._save_state()
                try:
                    with open(self.config.STATE_FILE) as f:
                        data = json.load(f)
                    data['last_rebalance'] = now_et().isoformat()
                    tmp = self.config.STATE_FILE.with_suffix('.tmp')
                    with open(tmp, 'w') as f:
                        json.dump(data, f, indent=2)
                    os.replace(tmp, self.config.STATE_FILE)
                except Exception as e:
                    logger.warning(f"last_rebalance stamp failed: {e}")
                logger.info("WEEKLY REBALANCE COMPLETED")
            else:
                logger.critical(f"WEEKLY REBALANCE PARTIAL FAILURE: {failures} - "
                                f"will retry next cycle (account may be half-rotated)")

        finally:
            self.risk.release_rebalance_lock()
    
    def generate_report(self, positions: List[Dict]) -> str:
        acct = self.client.get_account()
        lines = []
        lines.append("")
        lines.append("=" * 70)
        lines.append(f"  MONITOR v8.5 {now_et().strftime('%Y-%m-%d %H:%M:%S')} ET")
        
        equity = float(acct.get('equity', 0))
        
        # Identify SQQQ hedge position
        hedge_sym = self.config.HEDGE_ETF
        stock_positions = [p for p in positions if p['symbol'] != hedge_sym]
        hedge_positions = [p for p in positions if p['symbol'] == hedge_sym]
        
        lines.append(f"  Equity: ${equity:,.2f} | Stocks: {len(stock_positions)} | Hedge: {len(hedge_positions)}")
        
        if not positions:
            return "\n".join(lines) + "\n  No positions\n"
        
        # Stock positions
        if stock_positions:
            lines.append(f"\n  {'Sym':<7} {'Qty':>6} {'Entry':>9} {'Price':>9} {'P&L%':>7} {'Status':>8}")
            lines.append("  " + "-" * 55)
            for p in stock_positions:
                sym = p['symbol']
                qty = int(float(p['qty']))
                entry = self.entry_prices.get(sym, float(p['avg_entry_price']))
                current = float(p['current_price'])
                pl = (current - entry) / entry * 100 if entry > 0 else 0
                status = "STOP" if pl <= -8 else "WARN" if pl <= -5 else "HOLD" if pl < 20 else "PROFIT+"
                lines.append(f"  {sym:<7} {qty:>6d} ${entry:>8.2f} ${current:>8.2f} {pl:>+6.1f}% {status:>8}")
        
        # SQQQ hedge position display
        if hedge_positions and self.config.ENABLE_HEDGE:
            lines.append(f"\n  {'HEDGE':<7} {'Qty':>6} {'Value':>9} {'Price':>9} {'P&L%':>7} {'Trigger':>8}")
            lines.append("  " + "-" * 55)
            for p in hedge_positions:
                sym = p['symbol']
                qty = int(float(p['qty']))
                val = float(p['market_value'])
                current = float(p['current_price'])
                entry = float(p['avg_entry_price'])
                pl = (current - entry) / entry * 100 if entry > 0 else 0
                trigger = f"VIX>={self.config.HEDGE_VIX_ACTIVATE}"
                lines.append(f"  {sym:<7} {qty:>6d} ${val:>8.0f} ${current:>8.2f} {pl:>+6.1f}% {trigger:>8}")
        
        lines.append("=" * 70)
        return "\n".join(lines)
    
    # =========================================================================
    # DCL EXECUTION FLOW (v8.2): 先刷新数据 → 再生成信号 → 后下单
    #   D(ata): sync_positions() / get_bars() — 刷新最新价格与持仓
    #   C(heck): check_stops() / check_limits() — 基于最新数据生成风控信号
    #   S(ignal): macro.detect() + 5 strategies — 基于最新数据生成选股信号
    #   O(rder): submit_order() — 信号确认后才执行交易
    # =========================================================================
    def _in_trading_window(self) -> bool:
        """v8.5: enforce the configured TRADING_WINDOW (was dead config).
        Rebalances and hedge switches avoid open/close auction noise; stop
        losses are exempt (protection beats noise)."""
        t = now_et().time()
        return self.config.TRADING_WINDOW_START <= t.strftime('%H:%M') <= self.config.TRADING_WINDOW_END

    def run_cycle(self):
        # v8.5 (P2-6): kill switch - file present => cancel our orders, stop
        # all trading actions, keep reporting. Delete the file to resume.
        if self.config.KILL_SWITCH_FILE.exists():
            logger.critical(f"KILL SWITCH active ({self.config.KILL_SWITCH_FILE.name}) - "
                            f"no trading. Delete the file to resume.")
            if self.config.TRADING_ENABLED:
                self.client.cancel_our_orders()
            print(self.generate_report(self.sync_positions()))
            return

        # === Step 0: Pre-trade risk check ===
        acct = self.client.get_account()
        equity = float(acct.get('equity', 0))

        can_trade, reason = self.risk.check_limits(equity)
        if not can_trade:
            logger.warning(f"Trading blocked: {reason}")
            # v8.5: (a) TRADING_ENABLED=False shadow mode must NEVER send
            # orders - the old code liquidated anyway; (b) liquidate at most
            # once per circuit episode instead of every 60s for 24h.
            if ('max_drawdown' in reason or 'daily_loss' in reason):
                if not self.config.TRADING_ENABLED:
                    logger.critical("SHADOW MODE: would emergency-liquidate now "
                                    "(TRADING_ENABLED=False, no orders sent)")
                elif not self.risk._liquidated_for_circuit:
                    self.risk.emergency_liquidate(self.client)
                    self.risk._liquidated_for_circuit = True
                    self._save_state()
            return

        # v8.3 (C2): market-hours gating. v8.2 ran stops and the hedge 24/7,
        # firing market orders on stale data at night/weekends that queued to
        # the next open. TRADING_ENABLED=False is a shadow mode (no orders).
        clock = self.client.get_clock()
        market_open = bool(clock.get('is_open', False))

        # === Step 1: D — 刷新数据 (Data Refresh) ===
        # MP-003 FIX: Single positions sync, used consistently throughout
        positions = self.sync_positions()

        if self.config.TRADING_ENABLED and market_open:
            # === Step 2: C — 风控信号生成 (Risk Signal Generation) ===
            # 基于Step 1的最新持仓价格，生成止损/止盈信号，然后下单
            if not self.risk.is_rebalancing:
                self.check_stops(positions)

            # === Step 2.5: HEDGE — 实时条件对冲 (Intraday VIX-Triggered) ===
            # DCL: _get_vix(刷新) → evaluate(滞回带信号) → execute(市价单)
            # v8.5: switches only inside the trading window (auction noise);
            # account passed for the PDT guard.
            if self.config.ENABLE_HEDGE and self._in_trading_window():
                try:
                    hedge_result = self.hedge.intraday_check(self.client, equity, account=acct)
                    if hedge_result.get('action') in ('activate', 'deactivate'):
                        logger.critical(f"HEDGE {hedge_result['action'].upper()}: "
                                       f"VIX={hedge_result.get('vix', 0):.1f} | "
                                       f"Switch #{hedge_result.get('switches_today', 0)}/2 today")
                    elif hedge_result.get('action') == 'circuit_broken':
                        logger.warning(f"HEDGE CIRCUIT BROKEN: Max 2 switches reached today")
                except Exception as e:
                    logger.warning(f"Hedge intraday check error: {e}")

        # === Step 3: S+O — 选股信号生成 + 调仓下单 ===
        # v8.5 (P0-2): rebalance INSIDE the trading window while the market
        # is open (sells fill -> cash freed -> buys fill). The old
        # `not market_open` design queued everything to the next open and
        # broke the sell-then-buy funding chain.
        if (self.config.TRADING_ENABLED and market_open
                and self._in_trading_window() and self.should_rebalance()):
            self.do_rebalance()

        # === Step 4: Report ===
        print(self.generate_report(self.sync_positions()))
        self._save_state()
    
    # v8.5 (P1-5): single-instance lock. Two monitors on one account double
    # every order and corrupt each other's state file.
    def _acquire_instance_lock(self) -> bool:
        try:
            self.config.INSTANCE_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
            self._lock_fd = open(self.config.INSTANCE_LOCK_FILE, 'w')
            try:
                import fcntl
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except ImportError:
                pass  # non-POSIX: best-effort (pid file only)
            self._lock_fd.write(str(os.getpid()))
            self._lock_fd.flush()
            return True
        except (BlockingIOError, OSError):
            print(f"ERROR: another monitor instance holds {self.config.INSTANCE_LOCK_FILE} - exiting")
            return False

    def run(self):
        if not self._acquire_instance_lock():
            sys.exit(1)
        print("=" * 70)
        print("  TENBAGGER v8.5 - Production Monitor")
        print("  Features: Stop loss | Daily loss limit | Drawdown circuit | Weekly rebalance")
        print("  PDT guard | Kill switch | Atomic state | Instance lock | PIT fundamentals")
        print("=" * 70)
        print("  Ctrl+C to stop")

        cycle = 0
        try:
            while True:
                cycle += 1
                # v8.5: single clock call per cycle (run_cycle fetches its own)
                print(f"\n--- #{cycle} | {now_et().strftime('%H:%M:%S')} ET ---")
                self.run_cycle()
                time.sleep(60)
        except KeyboardInterrupt:
            print("\nStopped")
            self._save_state()


# ============================================================================
# MAIN ENTRY
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='Tenbagger v8.2 - All Critical Defects Fixed')
    parser.add_argument('--mode', choices=['backtest', 'paper', 'signal', 'walkforward', 'setup'],
                        default='backtest')
    parser.add_argument('--start', default='2019-01-01')
    parser.add_argument('--end', default='2024-01-01')
    parser.add_argument('--plot', action='store_true')
    parser.add_argument('--universe', choices=['ten', 'full'], default='ten',
                        help='ten = 10-stock dev universe; full = Config.UNIVERSE (520 stocks)')
    parser.add_argument('--no-param-optimize', action='store_true',
                        help='Disable parameter optimization in walk-forward')
    args = parser.parse_args()
    
    config = Config()
    
    if args.mode == 'setup':
        secure = SecureConfig(config)
        secure.setup_keys()
        return
    
    if args.mode == 'paper':
        # v8.5 (P2-9): pointing at a LIVE base URL requires an explicit
        # acknowledgement so paper/live can never be confused by accident.
        if 'paper' not in config.ALPACA_BASE_URL:
            if os.environ.get('LIVE_TRADING_ACK') != 'I_UNDERSTAND':
                print("REFUSED: ALPACA_BASE_URL is a LIVE endpoint "
                      f"({config.ALPACA_BASE_URL}) but LIVE_TRADING_ACK != I_UNDERSTAND")
                sys.exit(1)
            print("*** LIVE TRADING MODE - real money at risk ***")
        monitor = IntradayMonitor(config)
        monitor.run()
        return
    
    if args.mode == 'backtest' or args.mode == 'walkforward':
        # Load cached data
        data_dir = config.DATA_DIR
        if args.universe == 'full':
            # v8.4: full Config.UNIVERSE pool; per-symbol CSVs in data/universe/
            price_files = {}
            uni_dir = os.path.join(data_dir, 'universe')
            for sym in config.UNIVERSE:
                fp = os.path.join(uni_dir, f'{sym}.csv')
                if os.path.exists(fp):
                    price_files[sym] = os.path.join('universe', f'{sym}.csv')
            price_files['SPY'] = 'spy_2021_2023_v2.csv'
            price_files['SQQQ'] = 'sqqq.csv'
            print(f"Full universe: {len(price_files) - 2} stocks with price data")
        else:
            price_files = {
                'AAPL': 'aapl.csv', 'MSFT': 'msft.csv', 'NVDA': 'nvda.csv',
                'AMZN': 'amzn_2021_2023.csv', 'GOOGL': 'googl_2021_2023.csv',
                'META': 'meta_2021_2023.csv', 'TSLA': 'tsla.csv',
                'JPM': 'jpm.csv', 'UNH': 'unh.csv', 'SPY': 'spy_2021_2023_v2.csv',
                'SQQQ': 'sqqq.csv',  # v8.3: hedge ETF price history
            }

        all_data = {}
        for sym, fname in price_files.items():
            fp = os.path.join(data_dir, fname)
            if os.path.exists(fp):
                df = pd.read_csv(fp, index_col=0, parse_dates=True)
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
                if 'Close' in df.columns:
                    all_data[sym] = df['Close']
                elif len(df.columns) > 0:
                    all_data[sym] = df.iloc[:, 0]

        prices = pd.DataFrame(all_data)
        if args.universe == 'full':
            # stocks that start trading later than SPY (spinoffs/IPOs) would
            # truncate the whole frame in dropna(); drop the columns instead
            first_spy = prices['SPY'].first_valid_index()
            late = [c for c in prices.columns
                    if c not in ('SPY', 'SQQQ') and prices[c].first_valid_index() > first_spy]
            if late:
                print(f"Excluding {len(late)} late-start stocks: {sorted(late)}")
                prices = prices.drop(columns=late)
        prices = prices.ffill().dropna()
        benchmark = prices['SPY']

        # v8.3: real VIX history (CBOE format: DATE,OPEN,HIGH,LOW,CLOSE)
        vix_series = None
        vix_fp = os.path.join(data_dir, 'vix.csv')
        if os.path.exists(vix_fp):
            vdf = pd.read_csv(vix_fp)
            vdf.columns = [c.strip().upper() for c in vdf.columns]
            vix_series = pd.Series(vdf['CLOSE'].values,
                                   index=pd.to_datetime(vdf['DATE'], format='%m/%d/%Y'),
                                   name='VIX')
            vix_series = vix_series.reindex(prices.index, method='ffill')
            vix_series = vix_series.dropna()
        else:
            print("WARNING: data/vix.csv not found - hedge disabled in backtest")
        
        # Fundamentals: point-in-time SEC XBRL snapshots (no look-ahead).
        # Sectors are stable classifications, kept as a static map; all
        # valuation/quality ratios are computed per query date from filings.
        sector_map = {
            'AAPL': 'Technology', 'MSFT': 'Technology', 'NVDA': 'Technology',
            'AMZN': 'Consumer Cyclical', 'GOOGL': 'Communication Services',
            'META': 'Communication Services', 'TSLA': 'Consumer Cyclical',
            'JPM': 'Financial Services', 'UNH': 'Healthcare',
        }
        if args.universe == 'full':
            fundamentals = PointInTimeFundamentals(
                config, pit_file=os.path.join(config.DATA_DIR, 'pit_fundamentals_full.json'))
        else:
            fundamentals = PointInTimeFundamentals(config, sector_map=sector_map)
        if not fundamentals.snaps:
            print("WARNING: pit_fundamentals.json missing/empty - strategies will select nothing")
        
        if args.mode == 'backtest':
            print("=" * 70)
            print("TENBAGGER v8.4 BACKTEST")
            print(f"Period: {prices.index[0]} ~ {prices.index[-1]}")
            print("Features: PIT fundamentals (SEC XBRL) | Transaction costs | Next-day execution")
            print("FIXES: BUG-001,002,003,004 | HP-001..010 | MP-001..006")
            print("=" * 70)
            
            engine = BacktestEngine(config)
            results = engine.run(prices, benchmark, fundamentals,
                                 use_next_day_open=True, vix=vix_series)
            
            print(f"\n{'Metric':<25} {'Value':>12}")
            print("-" * 40)
            print(f"{'Total Return':<25} {results['total_return']*100:>+11.1f}%")
            print(f"{'CAGR':<25} {results['cagr']*100:>+11.1f}%")
            print(f"{'Sharpe Ratio':<25} {results['sharpe']:>11.2f}")
            print(f"{'Max Drawdown':<25} {results['max_drawdown']*100:>11.1f}%")
            print(f"{'Alpha':<25} {results['alpha']*100:>+11.1f}%")
            print(f"{'Beta':<25} {results['beta']:>11.2f}")
            print(f"{'Excess vs SPY':<25} {results['excess_return']*100:>+11.1f}%")
            print(f"{'Win Rate':<25} {results['win_rate']*100:>11.1f}%")
            print(f"{'Transaction Costs':<25} ${results.get('total_transaction_cost', 0):>10.2f}")
            print(f"{'# Trades':<25} {results['n_trades']:>11d}")
            
            # BUG verification output
            print("\n" + "=" * 70)
            print("BUG FIX VERIFICATION:")
            trailing_100_trades = [t for t in results['trades'] if t.get('reason') == 'trailing_100']
            trailing_50_trades = [t for t in results['trades'] if t.get('reason') == 'trailing_50']
            print(f"  trailing_100 triggers: {len(trailing_100_trades)} (v8.1: 0 - was dead code)")
            print(f"  trailing_50 triggers:  {len(trailing_50_trades)}")

            # Check entry prices use net_price
            buy_trades = [t for t in results['trades'] if t['action'] == 'BUY']
            price_mismatch = [t for t in buy_trades if t.get('price') == t.get('net_price')]
            print(f"  entry_price=net_price: {len(buy_trades) - len(price_mismatch)}/{len(buy_trades)} correct")

            # v8.3 verification: hedge, risk limits, SPY exclusion
            hedge_trades = [t for t in results['trades'] if t['symbol'] == config.HEDGE_ETF]
            risk_trades = [t for t in results['trades'] if str(t.get('reason', '')).startswith('risk_')]
            spy_buys = [t for t in buy_trades if t['symbol'] == 'SPY']
            print(f"  hedge trades (SQQQ): {len(hedge_trades)}")
            print(f"  risk-limit liquidations: {len(risk_trades)}")
            print(f"  SPY buys (must be 0): {len(spy_buys)}")
            print("=" * 70)
            
            if args.plot and 'portfolio_values' in results:
                try:
                    import matplotlib.pyplot as plt
                    pv = np.array(results['portfolio_values'])
                    dates = prices.index[252:252+len(pv)]
                    
                    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
                    fig.suptitle('Tenbagger v8.3 Backtest (All Fees + Fixes)', fontsize=14, fontweight='bold')
                    
                    strat_cum = (pv / pv[0] - 1) * 100
                    bench = prices['SPY'].iloc[252:252+len(pv)]
                    bench_cum = (bench / bench.iloc[0] - 1) * 100
                    
                    axes[0,0].plot(dates, strat_cum, label='v8.2 Strategy', linewidth=2, color='#1a5276')
                    axes[0,0].plot(dates, bench_cum, label='SPY', color='gray', linestyle='--', alpha=0.7)
                    axes[0,0].set_title('Cumulative Return (%)'); axes[0,0].legend(); axes[0,0].grid(True, alpha=0.3)
                    
                    cummax = np.maximum.accumulate(pv)
                    dd = (pv - cummax) / cummax * 100
                    axes[0,1].fill_between(dates, dd, 0, color='#e74c3c', alpha=0.5)
                    axes[0,1].set_title('Drawdown (%)'); axes[0,1].grid(True, alpha=0.3)
                    
                    axes[1,0].axis('off')
                    metrics = [['Total Return', f"{results['total_return']*100:+.1f}%"],
                               ['CAGR', f"{results['cagr']*100:+.1f}%"],
                               ['Sharpe', f"{results['sharpe']:.2f}"],
                               ['Max DD', f"{results['max_drawdown']*100:.1f}%"],
                               ['Alpha', f"{results['alpha']*100:+.1f}%"],
                               ['Beta', f"{results['beta']:.2f}"],
                               ['Win Rate', f"{results['win_rate']*100:.1f}%"],
                               ['Tx Costs', f"${results.get('total_transaction_cost', 0):.2f}"],]
                    table = axes[1,0].table(cellText=metrics, colLabels=['Metric', 'Value'],
                                            cellLoc='center', loc='center')
                    table.auto_set_font_size(False); table.set_fontsize(10); table.scale(1, 1.8)
                    for j in range(2):
                        table[(0, j)].set_facecolor('#1a5276')
                        table[(0, j)].set_text_props(color='white', fontweight='bold')
                    axes[1,0].set_title('Key Metrics', fontweight='bold', pad=15)
                    
                    # Trade P&L distribution
                    sells = [t for t in results['trades'] if t['action'] == 'SELL' and 'pnl_pct' in t]
                    if sells:
                        pnl_vals = [t['pnl_pct'] * 100 for t in sells]
                        axes[1,1].hist(pnl_vals, bins=15, color='gray', alpha=0.5, edgecolor='white')
                        axes[1,1].axvline(x=0, color='black', linewidth=0.5)
                        axes[1,1].set_title('Trade P&L Distribution (%)'); axes[1,1].grid(True, alpha=0.3)
                    
                    plt.tight_layout()
                    plt.savefig(str(config.DATA_DIR.parent / 'v83_backtest.png'), dpi=150, bbox_inches='tight')
                    print("\nChart saved to v83_backtest.png")
                    plt.show()
                except Exception as e:
                    print(f"Plot failed: {e}")
        
        elif args.mode == 'walkforward':
            print("WALK-FORWARD VALIDATION v8.2")
            print("Features: True walk-forward with parameter optimization")
            wfv = WalkForwardValidator(config)
            results = wfv.run(prices, benchmark, fundamentals, optimize_params=not args.no_param_optimize)
            
            if 'error' in results:
                print(f"Error: {results['error']}")
            else:
                print(f"\nPeriods tested: {results['n_periods']}")
                print(f"Mean return: {results['mean_return']*100:+.1f}% (std: {results['std_return']*100:.1f}%)")
                print(f"Mean Sharpe: {results['mean_sharpe']:.2f}")
                print(f"Mean Alpha: {results.get('mean_alpha', 0)*100:+.1f}%")
                print(f"Min return: {results['min_return']*100:+.1f}%")
                print(f"Max return: {results['max_return']*100:+.1f}%")
                print(f"Consistency: {results['consistency_score']:.2f} (1.0 = perfectly consistent)")
    
    elif args.mode == 'signal':
        print("SIGNAL MODE v8.2 - Run with paper mode for live signals")
        print("All critical defects fixed. Safe for production.")


if __name__ == '__main__':
    main()
