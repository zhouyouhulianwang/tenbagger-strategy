#!/usr/bin/env python3
"""Alternative risk framework experiments (v8.7 base, full pool).

User-proposed 4-layer framework vs current SQQQ hedge, built up layer by layer:
  base          : current (SQQQ hedge + tiered stops + 60% vol gate)
  no_sqqq       : SQQQ hedge disabled, nothing added
  pkg_vix       : no_sqqq + prev-day VIX>=30 -> halve stock exposure
  pkg_vix_trail : pkg_vix + 21d-high -15% trailing stop (replaces tiered stops)
  pkg_full      : pkg_vix_trail + RV90 buy-block + breadth scaling
Writes results to data/hedge_framework_experiments.json
"""
import os, sys, json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tenbagger_v8_2_production import Config, BacktestEngine
from strategy_experiments import load_data, yearly, seg_return

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
OUT = os.path.join(DATA, 'hedge_framework_experiments.json')


def cfg_base():
    return Config()


def cfg_no_sqqq():
    c = Config(); c.ENABLE_HEDGE = False; return c


def cfg_pkg_vix():
    c = cfg_no_sqqq(); c.VIX_HALVE_ENABLED = True; return c


def cfg_pkg_vix_trail():
    c = cfg_pkg_vix(); c.STOP_MODE = 'trail21'; return c


def cfg_pkg_full():
    c = cfg_pkg_vix_trail()
    c.RV90_BUY_BLOCK_ENABLED = True
    c.BREADTH_SCALING_ENABLED = True
    return c


VARIANTS = [
    ('base', cfg_base),
    ('no_sqqq', cfg_no_sqqq),
    ('pkg_vix', cfg_pkg_vix),
    ('pkg_vix_trail', cfg_pkg_vix_trail),
    ('pkg_full', cfg_pkg_full),
]


def run_one(cfg, prices, benchmark, vix, fundamentals):
    eng = BacktestEngine(cfg)
    res = eng.run(prices, benchmark, fundamentals,
                  use_next_day_open=True, vix=vix)
    dates = prices.index[252:]
    pv = res['portfolio_values']
    spy = benchmark.iloc[252:252 + len(pv)]
    n_hedge = sum(1 for tr in res['trades'] if tr['symbol'] == cfg.HEDGE_ETF)
    return {
        'total_return': round(res['total_return'] * 100, 1),
        'cagr': round(res['cagr'] * 100, 1),
        'sharpe': round(res['sharpe'], 2),
        'mdd': round(res['max_drawdown'] * 100, 1),
        'excess': round(res['excess_return'] * 100, 1),
        'n_trades': res['n_trades'],
        'n_hedge_trades': n_hedge,
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
    for name, mk in VARIANTS:
        if which != 'all' and name != which:
            continue
        print(f'running {name} ...', flush=True)
        results[name] = run_one(mk(), prices, benchmark, vix, fundamentals)
        r = results[name]
        print(f"  {name}: ret {r['total_return']}% sharpe {r['sharpe']} "
              f"mdd {r['mdd']}% segs {r['seg_2020_2023']}/{r['seg_2024_2026']}",
              flush=True)
        json.dump(results, open(OUT, 'w'), indent=1)
    print('done ->', OUT)


if __name__ == '__main__':
    main()
