#!/usr/bin/env python3
"""Liquidity floor experiment (v8.9 base, full pool).

User directive 2026-08-03: risk-control rule - daily volume >= 10M shares.
Single-bit change on candidate selection only:
  base        : MIN_ADV_SHARES=0 (must reproduce v8.9: 559.6/1.59/-22.8)
  adv20_10m   : 20d average daily volume >= 10M shares
  day_10m     : latest-day volume >= 10M shares (literal reading)

Volume panel: consolidated daily share volume from data/universe/*.csv
(same source as the price panel). Writes data/volume_filter_experiments.json
"""
import os, sys, json
from collections import Counter

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tenbagger_v8_2_production import Config, BacktestEngine
from strategy_experiments import load_data, yearly, seg_return

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
OUT = os.path.join(DATA, 'volume_filter_experiments.json')


def load_volumes(prices):
    """Volume panel aligned to the prices panel's symbols/index."""
    uni_dir = os.path.join(DATA, 'universe')
    vols = {}
    for sym in prices.columns:
        fp = os.path.join(uni_dir, f'{sym}.csv')
        if not os.path.exists(fp):
            continue
        df = pd.read_csv(fp, index_col=0, parse_dates=True)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        if 'Volume' in df.columns:
            vols[sym] = df['Volume']
    return pd.DataFrame(vols).reindex(prices.index).ffill()


def mk(shares, mode='adv20'):
    c = Config()
    c.MIN_ADV_SHARES = shares
    c.MIN_ADV_MODE = mode
    return c


VARIANTS = [
    ('base',      mk(0)),
    ('adv20_10m', mk(10_000_000, 'adv20')),
    ('day_10m',   mk(10_000_000, 'day')),
]


def run_one(cfg, prices, benchmark, vix, fundamentals, volumes):
    eng = BacktestEngine(cfg)
    res = eng.run(prices, benchmark, fundamentals,
                  use_next_day_open=True, vix=vix, volumes=volumes)
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
    volumes = load_volumes(prices)
    print(f'data: {len(prices)} days x {len(prices.columns)} cols, '
          f'volumes: {len(volumes.columns)} cols', flush=True)
    results = json.load(open(OUT)) if os.path.exists(OUT) else {}
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    for name, cfg in VARIANTS:
        if which != 'all' and name != which:
            continue
        print(f'running {name} ...', flush=True)
        results[name] = run_one(cfg, prices, benchmark, vix, fundamentals, volumes)
        r = results[name]
        print(f"  {name}: ret {r['total_return']}% sharpe {r['sharpe']} "
              f"mdd {r['mdd']}% segs {r['seg_2020_2023']}/{r['seg_2024_2026']}",
              flush=True)
        json.dump(results, open(OUT, 'w'), indent=1)
    print('done ->', OUT)


if __name__ == '__main__':
    main()
