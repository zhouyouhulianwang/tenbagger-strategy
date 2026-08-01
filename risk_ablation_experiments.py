#!/usr/bin/env python3
"""Sell-side & risk-control ablation (v8.9 base, full pool).

Scores each sell/risk component by removing it (single-bit ablations):
  base        : v8.9 as-is (must reproduce 559.6/1.59/-22.8)
  no_stops    : STOP_MODE='off' - no hard -8% / trailing +50%/+100% stops
  no_daily    : DAILY_LOSS_LIMIT_PCT effectively off (-3%/day liquidate-all)
  no_dd       : MAX_DRAWDOWN_LIMIT_PCT effectively off (-10% circuit breaker)
  no_risk_all : all three removed - pure weekly top-6 rotation

A component "earns its keep" if removing it makes results WORSE.
Writes results to data/risk_ablation_experiments.json
"""
import os, sys, json
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tenbagger_v8_2_production import Config, BacktestEngine
from strategy_experiments import load_data, yearly, seg_return

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
OUT = os.path.join(DATA, 'risk_ablation_experiments.json')


def mk(stops=True, daily=True, dd=True):
    c = Config()
    if not stops:
        c.STOP_MODE = 'off'
    if not daily:
        c.DAILY_LOSS_LIMIT_PCT = -0.9999
    if not dd:
        c.MAX_DRAWDOWN_LIMIT_PCT = -0.9999
    return c


VARIANTS = [
    ('base',        mk()),
    ('no_stops',    mk(stops=False)),
    ('no_daily',    mk(daily=False)),
    ('no_dd',       mk(dd=False)),
    ('no_risk_all', mk(stops=False, daily=False, dd=False)),
]


def run_one(cfg, prices, benchmark, vix, fundamentals):
    eng = BacktestEngine(cfg)
    res = eng.run(prices, benchmark, fundamentals,
                  use_next_day_open=True, vix=vix)
    dates = prices.index[252:]
    pv = res['portfolio_values']
    spy = benchmark.iloc[252:252 + len(pv)]
    sells = Counter(t.get('reason', '?') for t in res.get('trades', [])
                    if t.get('action') == 'SELL')
    return {
        'total_return': round(res['total_return'] * 100, 1),
        'cagr': round(res['cagr'] * 100, 1),
        'sharpe': round(res['sharpe'], 2),
        'mdd': round(res['max_drawdown'] * 100, 1),
        'excess': round(res['excess_return'] * 100, 1),
        'n_trades': res['n_trades'],
        'sell_reasons': dict(sells),
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
              f"mdd {r['mdd']}% segs {r['seg_2020_2023']}/{r['seg_2024_2026']} "
              f"sells {r['sell_reasons']}", flush=True)
        json.dump(results, open(OUT, 'w'), indent=1)
    print('done ->', OUT)


if __name__ == '__main__':
    main()
