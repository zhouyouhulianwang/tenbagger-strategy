#!/usr/bin/env python3
"""Re-validate battery winners on data extended to 2026-11-18 (4 weeks
after the original battery). Rule#4/#6: conclusions must hold on the
freshest data before a config change stays in production."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from optimize_battery_experiments import mk, run_one  # noqa: E402
from strategy_experiments import load_data  # noqa: E402


def main():
    prices, benchmark, vix, pit = load_data()
    print(f'data: {prices.index[0].date()} -> {prices.index[-1].date()}', flush=True)
    results = {}
    for name, cfg in [('base', mk()),
                      ('rb30', mk(STRATEGY_RESONANCE_BONUS=0.30)),
                      ('vt40', mk(VOLATILITY_TARGET=0.40))]:
        r = run_one(cfg, prices, benchmark, vix, pit)
        results[name] = r
        print(f"{name}: ret {r['total_return']}% sharpe {r['sharpe']} "
              f"mdd {r['mdd']}% segs {r['seg_2020_2023']}/{r['seg_2024_2026']}",
              flush=True)
        print(f"  yearly: {r['yearly']}", flush=True)
    b = results['base']
    for name in ('rb30', 'vt40'):
        y = results[name]['yearly']
        holes = {yr: b['yearly'][yr] - y.get(yr, b['yearly'][yr]) for yr in b['yearly']}
        print(f"{name} max yearly hole vs base: {max(holes.values()):+.1f}pp",
              flush=True)


if __name__ == '__main__':
    main()
