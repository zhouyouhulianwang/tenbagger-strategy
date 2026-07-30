#!/usr/bin/env python3
"""Pre-rebalance report (rule-3 flow step 2-3): generate target portfolio
from the latest local data WITHOUT placing any orders. Mirrors the signal
half of IntradayMonitor.do_rebalance (v8.6 weights: growth=0)."""
import os, sys, json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tenbagger_v8_2_production import (Config, MomentumStrategy, GrowthStrategy,
                                       ValueStrategy, DefensiveStrategy, MacroTiming,
                                       PortfolioConstructor, PointInTimeFundamentals,
                                       VixProvider)

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
cfg = Config()

# --- load prices (same loader as --universe full) ---
price_files = {}
uni_dir = os.path.join(DATA, 'universe')
for sym in cfg.UNIVERSE:
    fp = os.path.join(uni_dir, f'{sym}.csv')
    if os.path.exists(fp):
        price_files[sym] = fp
price_files['SPY'] = os.path.join(DATA, 'spy_2021_2023_v2.csv')
price_files['SQQQ'] = os.path.join(DATA, 'sqqq.csv')
all_data = {}
for sym, fp in price_files.items():
    df = pd.read_csv(fp, index_col=0, parse_dates=True)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    all_data[sym] = df['Close'] if 'Close' in df.columns else df.iloc[:, 0]
prices = pd.DataFrame(all_data)
first_spy = prices['SPY'].first_valid_index()
late = [c for c in prices.columns if c not in ('SPY', 'SQQQ') and prices[c].first_valid_index() > first_spy]
prices = prices.drop(columns=late).ffill().dropna()
benchmark = prices['SPY']
t = len(prices) - 1
asof = prices.index[-1].date()

fundamentals = PointInTimeFundamentals(cfg, pit_file=os.path.join(DATA, 'pit_fundamentals_full.json'))
macro = MacroTiming(cfg)
constructor = PortfolioConstructor(cfg)

regime, msignal = macro.detect(prices, t)
weights = macro.get_weights(regime, cfg)
sel_prices = prices[[c for c in prices.columns if c not in ('SPY', 'SQQQ')]]

mom = MomentumStrategy(cfg).select(sel_prices, benchmark, t)
growth = GrowthStrategy(fundamentals, cfg).select(sel_prices, benchmark, t)
value = ValueStrategy(fundamentals, cfg).select(sel_prices, benchmark, t)
defensive = DefensiveStrategy(fundamentals, cfg).select(sel_prices, benchmark, t)
combined = constructor.combine(mom, {}, growth, value, defensive, weights)
combined = constructor.filter_21d_high(combined, prices, t)
combined = constructor.filter_by_volatility(combined, prices, t)
top = dict(list(combined.items())[:cfg.MAX_POSITIONS])

# position sizing (mirror BacktestEngine sizing)
pos_factor = msignal.get('position_factor', 1.0)
raw_w = {}
for sym, signal in top.items():
    vol = prices[sym].iloc[max(0, t-20):t+1].pct_change().std() * np.sqrt(252)
    if 'defensive' in signal.get('strategies', []):
        vol *= 0.8
    vol_factor = min(cfg.VOLATILITY_TARGET / vol, 2.0) if vol > 0 else 1.0
    score_weight = min(signal['total'] / 0.5, 1.0) if signal['total'] > 0 else 0.5
    raw_w[sym] = vol_factor * score_weight
wsum = sum(raw_w.values())

# VIX for hedge status
vdf = pd.read_csv(os.path.join(DATA, 'vix.csv'))
vdf.columns = [c.strip().upper() for c in vdf.columns]
vix_last = float(vdf['CLOSE'].iloc[-1])

print('=' * 72)
print(f'  预调仓报告 (PRE-REBALANCE REPORT)  数据截至 {asof}  [v8.6]')
print('=' * 72)
print(f'  Regime: {regime} | position_factor: {pos_factor:.2f} | '
      f'20d vol: {msignal.get("current_vol", 0):.1%} | SPY>200d: {msignal.get("above_200d")}')
print(f'  VIX (昨收): {vix_last:.1f} | 对冲阈值 {cfg.HEDGE_VIX_ACTIVATE} -> '
      f'{"应激活 SQQQ " + str(int(cfg.HEDGE_POSITION_PCT*100)) + "%" if vix_last >= cfg.HEDGE_VIX_ACTIVATE else "不激活对冲"}')
print(f'  策略权重: {weights}')
print('-' * 72)
print('  各策略选股 (score):')
for name, picks in (('momentum', mom), ('growth[w=0]', growth), ('value', value), ('defensive', defensive)):
    lst = ', '.join(f"{s}:{d['total']:.2f}" for s, d in picks.items()) or '(无)'
    print(f'    {name:<12} {lst}')
print('-' * 72)
print(f"  {'目标持仓':<8}{'目标权重':>9}{'现价':>10}  来源策略")
invested = 0.0
for sym, w in raw_w.items():
    wt = pos_factor * w / wsum
    invested += wt
    px = prices[sym].iloc[-1]
    print(f"  {sym:<8}{wt:>8.1%}  ${px:>9.2f}  {','.join(top[sym]['strategies'])}")
print('-' * 72)
print(f'  股票总仓位: {invested:.1%} | 现金: {1-invested:.1%} | 对冲: '
      f'{"SQQQ 10%(激活时)" if vix_last >= cfg.HEDGE_VIX_ACTIVATE else "无"}')
print('=' * 72)
print('说明: 信号基于本地 Nasdaq 历史数据(昨收)与 SEC PIT 基本面;')
print('      实盘 monitor 用 Alpaca bars(全复权)实时生成, 个股可能略有差异。')
