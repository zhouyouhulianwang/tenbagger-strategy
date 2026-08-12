#!/usr/bin/env python3
"""Daily-loss-limit threshold scan (v9.2, full pool).

User question 2026-08-11: "can the -3% daily-loss limit be -5% or -10%?
recent underperformance vs SPY". Single-parameter sweep of
Config.DAILY_LOSS_LIMIT_PCT. Reference points already archived:
  base -3%  = 559.6/1.59/-22.8 (must reproduce)
  off       = 269.2/1.12/-30.4 (risk_ablation_experiments.json no_daily)

Writes results to data/daily_loss_threshold_experiments.json
"""
import os, sys, json
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tenbagger_v8_2_production import Config, BacktestEngine
from strategy_experiments import load_data, yearly, seg_return

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
OUT = os.path.join(DATA, 'daily_loss_threshold_experiments.json')


def mk(pct):
    c = Config()
    c.DAILY_LOSS_LIMIT_PCT = pct
    return c


VARIANTS = [
    ('limit_2pct',   mk(-0.02)),
    ('limit_2_5pct', mk(-0.025)),
    ('limit_3pct',   mk(-0.03)),   # current live setting - must reproduce base
    ('limit_3_5pct', mk(-0.035)),
    ('limit_4pct',   mk(-0.04)),
    ('limit_5pct',   mk(-0.05)),
    ('limit_10pct',  mk(-0.10)),
]


def run_one(cfg, prices, benchmark, vix, fundamentals):
    eng = BacktestEngine(cfg)
    res = eng.run(prices, benchmark, fundamentals,
                  use_next_day_open=True, vix=vix)
    dates = prices.index[252:]
    pv = res['portfolio_values']
    trades = res.get('trades', [])
    sells = Counter(t.get('reason', '?') for t in trades if t.get('action') == 'SELL')
    dl_events = len({t['date'] for t in trades
                     if t.get('reason') == 'risk_daily_loss_limit'})
    return {
        'total_return': round(res['total_return'] * 100, 1),
        'cagr': round(res['cagr'] * 100, 1),
        'sharpe': round(res['sharpe'], 2),
        'mdd': round(res['max_drawdown'] * 100, 1),
        'excess': round(res['excess_return'] * 100, 1),
        'daily_limit_events': dl_events,
        'sell_reasons': dict(sells),
        'yearly': yearly(pv, dates),
        'seg_2020_2023': seg_return(pv, dates, '2020-01-01', '2023-12-31'),
        'seg_2024_2026': seg_return(pv, dates, '2024-01-01', '2026-12-31'),
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
              f"events {r['daily_limit_events']}", flush=True)
        json.dump(results, open(OUT, 'w'), indent=1)
    print('done ->', OUT)


if __name__ == '__main__':
    main()
