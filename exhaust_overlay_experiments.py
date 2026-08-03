#!/usr/bin/env python3
"""Exhaustion-layer overlays (v8.9 base, full pool) - ported from an external
research table the user shared 2026-07-31. Their system differs (baseline
65.7%/2.07 vs ours 40.7%/1.59), so signals are re-validated on OUR system.

Definition mappings (ours):
  leader group : current holdings; distance = vs 252d closing high, median
  breadth      : fraction of universe with r252 > 0 (same as BREADTH_SCALING)
  halve        : daily pro-rata sell 50% while triggered, restore on clear

Variants:
  base        : v8.9 as-is (must reproduce 559.6/1.59/-22.8)
  exh_leader  : median leader dist-from-252d-high < -8% -> halve
  exh_breadth : breadth drops 15pt in 21d -> halve
  exh_combo   : either -> halve (取严, their ✅✅ winner)

Writes results to data/exhaust_overlay_experiments.json
"""
import os, sys, json
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tenbagger_v8_2_production import Config, BacktestEngine
from strategy_experiments import load_data, yearly, seg_return

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
OUT = os.path.join(DATA, 'exhaust_overlay_experiments.json')


def mk(leader=False, breadth=False):
    c = Config()
    c.EXHAUST_LEADER_HIGH_ENABLED = leader
    c.EXHAUST_BREADTH_ENABLED = breadth
    return c


VARIANTS = [
    ('base',        mk()),
    ('exh_leader',  mk(leader=True)),
    ('exh_breadth', mk(breadth=True)),
    ('exh_combo',   mk(leader=True, breadth=True)),
]


def run_one(cfg, prices, benchmark, vix, fundamentals):
    eng = BacktestEngine(cfg)
    res = eng.run(prices, benchmark, fundamentals,
                  use_next_day_open=True, vix=vix)
    dates = prices.index[252:]
    pv = res['portfolio_values']
    spy = benchmark.iloc[252:252 + len(pv)]
    n_days = len(pv)
    sells = Counter(t.get('reason', '?') for t in res.get('trades', [])
                    if t.get('action') == 'SELL')
    return {
        'total_return': round(res['total_return'] * 100, 1),
        'cagr': round(res['cagr'] * 100, 1),
        'sharpe': round(res['sharpe'], 2),
        'mdd': round(res['max_drawdown'] * 100, 1),
        'excess': round(res['excess_return'] * 100, 1),
        'n_trades': res['n_trades'],
        'half_day_pct': round(res.get('exhaust_half_days', 0) / max(n_days, 1) * 100, 1),
        'exhaust_sells': sells.get('exhaust_halve', 0),
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
              f"mdd {r['mdd']}% half-days {r['half_day_pct']}% "
              f"segs {r['seg_2020_2023']}/{r['seg_2024_2026']}", flush=True)
        json.dump(results, open(OUT, 'w'), indent=1)
    print('done ->', OUT)


if __name__ == '__main__':
    main()
