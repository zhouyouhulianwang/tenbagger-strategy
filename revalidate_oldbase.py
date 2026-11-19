#!/usr/bin/env python3
"""Re-validate rb30 on data extended to 2026-11-18 (rule#4/#6).
NOTE: production file already carries 0.30, so the OLD base must be
pinned explicitly (0.20). Only the missing number is run: old base."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from optimize_battery_experiments import mk, run_one  # noqa: E402
from strategy_experiments import load_data  # noqa: E402


def main():
    prices, benchmark, vix, pit = load_data()
    print(f'data: {prices.index[0].date()} -> {prices.index[-1].date()}', flush=True)
    # pinned OLD production value (deployed file now defaults to 0.30)
    r = run_one(mk(STRATEGY_RESONANCE_BONUS=0.20), prices, benchmark, vix, pit)
    print(f"oldbase020: ret {r['total_return']}% sharpe {r['sharpe']} "
          f"mdd {r['mdd']}% segs {r['seg_2020_2023']}/{r['seg_2024_2026']}",
          flush=True)
    print(f"  yearly: {r['yearly']}", flush=True)


if __name__ == '__main__':
    main()
