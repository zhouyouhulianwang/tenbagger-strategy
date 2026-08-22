#!/usr/bin/env python3
"""Structure scans (v9.2, full pool) - 2026-08-22 full review follow-ups.

Three independent single-bit groups:

  sizing    : SIZING_MODE vol_score (current backtest sizing, must
              reproduce 559.6/1.59/-22.8) vs equal (what live
              smart_rebalance() actually does -> quantifies the
              live/backtest sizing gap found in the review)
  positions : MAX_POSITIONS 5/6(current)/7/8/10 - never scanned before
              (only the 30% single-name cap was scanned, v8.8 era)
  phase     : REBALANCE_PHASE 0(current)-4 - shifts the 5-day cycle
              anchor; tests whether the weekly anchor's phase matters
              (live anchors Monday; backtest anchored at t=252)

Usage: python3 structure_scan_experiments.py [sizing|positions|phase|all]
Writes data/structure_scan_experiments.json (per-group sub-dicts).
"""
import os, sys, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tenbagger_v8_2_production import Config, BacktestEngine
from strategy_experiments import load_data, yearly, seg_return

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
OUT = os.path.join(DATA, 'structure_scan_experiments.json')


def mk(**kw):
    c = Config()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


GROUPS = {
    'sizing': [
        ('vol_score', mk()),                       # base
        ('equal',     mk(SIZING_MODE='equal')),
    ],
    'positions': [
        ('n5',  mk(MAX_POSITIONS=5)),
        ('n6',  mk()),                             # base
        ('n7',  mk(MAX_POSITIONS=7)),
        ('n8',  mk(MAX_POSITIONS=8)),
        ('n10', mk(MAX_POSITIONS=10)),
    ],
    'phase': [
        ('p0', mk()),                              # base
        ('p1', mk(REBALANCE_PHASE=1)),
        ('p2', mk(REBALANCE_PHASE=2)),
        ('p3', mk(REBALANCE_PHASE=3)),
        ('p4', mk(REBALANCE_PHASE=4)),
    ],
}


def run_one(cfg, prices, benchmark, vix, fundamentals):
    eng = BacktestEngine(cfg)
    res = eng.run(prices, benchmark, fundamentals,
                  use_next_day_open=True, vix=vix)
    dates = prices.index[252:]
    pv = res['portfolio_values']
    return {
        'total_return': round(res['total_return'] * 100, 1),
        'cagr': round(res['cagr'] * 100, 1),
        'sharpe': round(res['sharpe'], 2),
        'mdd': round(res['max_drawdown'] * 100, 1),
        'n_trades': res['n_trades'],
        'yearly': yearly(pv, dates),
        'seg_2020_2023': seg_return(pv, dates, '2020-01-01', '2023-12-31'),
        'seg_2024_2026': seg_return(pv, dates, '2024-01-01', '2026-12-31'),
    }


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    print(f'loading data... group={which}', flush=True)
    prices, benchmark, vix, fundamentals = load_data()
    results = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for group, variants in GROUPS.items():
        if which != 'all' and group != which:
            continue
        results.setdefault(group, {})
        for name, cfg in variants:
            print(f'running {group}/{name} ...', flush=True)
            results[group][name] = run_one(cfg, prices, benchmark, vix, fundamentals)
            r = results[group][name]
            print(f"  {group}/{name}: ret {r['total_return']}% sharpe {r['sharpe']} "
                  f"mdd {r['mdd']}% segs {r['seg_2020_2023']}/{r['seg_2024_2026']}",
                  flush=True)
            json.dump(results, open(OUT, 'w'), indent=1)
    print('done ->', OUT)


if __name__ == '__main__':
    main()
