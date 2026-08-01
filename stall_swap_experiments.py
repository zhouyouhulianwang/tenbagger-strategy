#!/usr/bin/env python3
"""Stall-swap experiment (v8.9 base, full pool).

User hypothesis: among top-ranked picks, some are "stalling" (high score but
recent momentum faded); swapping them for slightly lower-ranked candidates
with confirmed natural momentum may improve results.

Single-bit change on selection only (everything else = v8.9 base):
  base       : STALL_SWAP_MODE='off'  (must reproduce v8.9: 559.6/1.59/-22.8)
  v1_filter  : 'filter' - hard-exclude candidates with r21 <= 0, fall through
               to next rank (any sleeve)
  v2_swap    : 'swap'   - only top-6 stallers swapped, replacement must have
               r21 > 0 AND r126 >= the staller's r126 (natural momentum)

Writes results to data/stall_swap_experiments.json
"""
import os, sys, json, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tenbagger_v8_2_production import Config, BacktestEngine
from strategy_experiments import load_data, yearly, seg_return

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
OUT = os.path.join(DATA, 'stall_swap_experiments.json')


def mk(mode):
    c = Config()
    c.STALL_SWAP_MODE = mode
    return c


VARIANTS = [
    ('base',      mk('off')),
    ('v1_filter', mk('filter')),
    ('v2_swap',   mk('swap')),
]


class StallCounter(logging.Handler):
    def __init__(self):
        super().__init__()
        self.n = 0

    def emit(self, record):
        msg = record.getMessage()
        if msg.startswith('STALL-'):
            self.n += 1


def run_one(cfg, prices, benchmark, vix, fundamentals):
    counter = StallCounter()
    logging.getLogger().addHandler(counter)
    try:
        eng = BacktestEngine(cfg)
        res = eng.run(prices, benchmark, fundamentals,
                      use_next_day_open=True, vix=vix)
    finally:
        logging.getLogger().removeHandler(counter)
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
        'stall_events': counter.n,
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
              f"mdd {r['mdd']}% events {r['stall_events']} "
              f"segs {r['seg_2020_2023']}/{r['seg_2024_2026']}", flush=True)
        json.dump(results, open(OUT, 'w'), indent=1)
    print('done ->', OUT)


if __name__ == '__main__':
    main()
