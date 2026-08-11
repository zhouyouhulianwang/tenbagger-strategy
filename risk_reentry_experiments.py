#!/usr/bin/env python3
"""Risk-liquidation re-entry timing experiment (v9.2, full pool).

Prompted by the 2026-08-05 event: DVA gapped -17% on earnings, hard stops
fired, daily-loss limit emergency-liquidated the rest on a Wednesday, and
the account sat in cash until the Monday rebalance. Question: is waiting
for the next scheduled rebalance optimal, or should the portfolio rebuild
sooner after a risk liquidation?

Single-bit variants (Config.RISK_REENTRY_MODE):
  scheduled   : current behaviour - cash until next regular rebalance
                (must reproduce the 559.6/1.59/-22.8 baseline)
  next_day    : forced rebalance 1 trading day after the risk event
  cooldown_2d : forced rebalance 2 trading days after the risk event

Drawdown-breaker events additionally wait out the 24h circuit cooldown in
all modes (check_limits gates every day). Metrics identical to the other
experiment scripts, plus risk-event count and average idle trading days
per event (event day -> first rebalance day that re-enters positions).

Writes results to data/risk_reentry_experiments.json
"""
import os, sys, json
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tenbagger_v8_2_production import Config, BacktestEngine
from strategy_experiments import load_data, yearly, seg_return

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
OUT = os.path.join(DATA, 'risk_reentry_experiments.json')


def mk(mode):
    c = Config()
    c.RISK_REENTRY_MODE = mode
    return c


VARIANTS = [
    ('scheduled',   mk('scheduled')),
    ('next_day',    mk('next_day')),
    ('cooldown_2d', mk('cooldown_2d')),
]


def run_one(cfg, prices, benchmark, vix, fundamentals):
    eng = BacktestEngine(cfg)
    res = eng.run(prices, benchmark, fundamentals,
                  use_next_day_open=True, vix=vix)
    dates = prices.index[252:]
    pv = res['portfolio_values']
    spy = benchmark.iloc[252:252 + len(pv)]
    trades = res.get('trades', [])
    sells = Counter(t.get('reason', '?') for t in trades if t.get('action') == 'SELL')
    # risk events = distinct dates with risk_* sells; idle days = trading
    # days from event until the next BUY (re-entry)
    event_dates = sorted({t['date'] for t in trades
                          if t.get('reason', '').startswith('risk_')})
    idle = []
    for d in event_dates:
        nxt = [t2['date'] for t2 in trades
               if t2.get('action') == 'BUY' and t2['date'] > d
               and t2.get('reason', '') != 'hedge_activate']
        if nxt:
            idle.append((nxt[0] - d).days)
    return {
        'total_return': round(res['total_return'] * 100, 1),
        'cagr': round(res['cagr'] * 100, 1),
        'sharpe': round(res['sharpe'], 2),
        'mdd': round(res['max_drawdown'] * 100, 1),
        'excess': round(res['excess_return'] * 100, 1),
        'n_trades': res['n_trades'],
        'sell_reasons': dict(sells),
        'n_risk_events': len(event_dates),
        'avg_idle_cal_days': round(sum(idle) / len(idle), 1) if idle else None,
        'max_idle_cal_days': max(idle) if idle else None,
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
              f"events {r['n_risk_events']} idle_cal {r['avg_idle_cal_days']}",
              flush=True)
        json.dump(results, open(OUT, 'w'), indent=1)
    print('done ->', OUT)


if __name__ == '__main__':
    main()
