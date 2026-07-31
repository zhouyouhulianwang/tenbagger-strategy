#!/usr/bin/env python3
"""Framework value WITHOUT regime de-grossing (v8.8 base, full pool).

Regime position factor forced to 1.0 (strategy weights still regime-based);
then the user's framework layers are added to see if they earn their keep
when the regime overlay is not doing the de-grossing:
  pf1            : position_factor = 1.0 always, nothing else
  pf1_vix        : pf1 + prev-day VIX>=30 -> halve exposure
  pf1_trail      : pf1 + 21d-high -15% trailing stop
  pf1_vix_trail  : pf1 + VIX-halve + trail21
  pf1_full       : pf1 + VIX-halve + trail21 + RV90 block + breadth
  pf1_full_rv90  : pf1_full with MAX_VOLATILITY=0.90 (RV90 replaces 60% gate)
Writes results to data/degross_experiments.json
"""
import os, sys, json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tenbagger_v8_2_production import Config, BacktestEngine, MacroTiming
from strategy_experiments import load_data, yearly, seg_return

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
OUT = os.path.join(DATA, 'degross_experiments.json')
ORIG_DETECT = MacroTiming.detect


def detect_pf1(self, prices, t):
    r, sig = ORIG_DETECT(self, prices, t)
    sig['position_factor'] = 1.0
    return r, sig


def mk(vix_halve=False, trail21=False, rv90_block=False, breadth=False,
       max_vol=None):
    c = Config()
    c.VIX_HALVE_ENABLED = vix_halve
    if trail21:
        c.STOP_MODE = 'trail21'
    c.RV90_BUY_BLOCK_ENABLED = rv90_block
    c.BREADTH_SCALING_ENABLED = breadth
    if max_vol:
        c.MAX_VOLATILITY = max_vol
    return c


VARIANTS = [
    ('pf1',           mk()),
    ('pf1_vix',       mk(vix_halve=True)),
    ('pf1_trail',     mk(trail21=True)),
    ('pf1_vix_trail', mk(vix_halve=True, trail21=True)),
    ('pf1_full',      mk(vix_halve=True, trail21=True, rv90_block=True,
                         breadth=True)),
    ('pf1_full_rv90', mk(vix_halve=True, trail21=True, rv90_block=True,
                         breadth=True, max_vol=0.90)),
]


def run_one(cfg, prices, benchmark, vix, fundamentals):
    MacroTiming.detect = detect_pf1
    try:
        eng = BacktestEngine(cfg)
        res = eng.run(prices, benchmark, fundamentals,
                      use_next_day_open=True, vix=vix)
    finally:
        MacroTiming.detect = ORIG_DETECT
    dates = prices.index[252:]
    pv = res['portfolio_values']
    spy = benchmark.iloc[252:252 + len(pv)]
    return {
        'total_return': round(res['total_return'] * 100, 1),
        'cagr': round(res['cagr'] * 100, 1),
        'sharpe': round(res['sharpe'], 2),
        'mdd': round(res['max_drawdown'] * 100, 1),
        'excess': round(res['excess_return'] * 100, 1),
        'n_trades': res['n_trades'],
        'yearly': yearly(pv, dates),
        'seg_2020_2023': seg_return(pv, dates, '2020-01-01', '2023-12-31'),
        'seg_2024_2026': seg_return(pv, dates, '2024-01-01', '2026-12-31'),
        'spy_seg_2020_2023': seg_return((spy / spy.iloc[0]).tolist(), spy.index,
                                        '2020-01-01', '2023-12-31'),
        'spy_seg_2024_2026': seg_return((spy / spy.iloc[0]).tolist(), spy.index,
                                        '2024-01-01', '2026-12-31'),
    }


def main():
    print('loading data...', flush=True)
    prices, benchmark, vix, fundamentals = load_data()
    print(f'data: {len(prices)} days x {len(prices.columns)} cols', flush=True)
    results = json.load(open(OUT)) if os.path.exists(OUT) else {}
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    for name, cfg in VARIANTS:
        if which != 'all' and name != which:
            continue
        print(f'running {name} ...', flush=True)
        results[name] = run_one(cfg, prices, benchmark, vix, fundamentals)
        r = results[name]
        print(f"  {name}: ret {r['total_return']}% sharpe {r['sharpe']} "
              f"mdd {r['mdd']}% segs {r['seg_2020_2023']}/{r['seg_2024_2026']}",
              flush=True)
        json.dump(results, open(OUT, 'w'), indent=1)
    print('done ->', OUT)


if __name__ == '__main__':
    main()
