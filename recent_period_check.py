#!/usr/bin/env python3
"""One-off: how would base / rb30 / vt40 have done during the live loss
window 2026-08-24 -> 2026-10-22? Complements optimize_battery_experiments.
Informational only; not a production change."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd  # noqa: E402
from optimize_battery_experiments import mk  # noqa: E402
from strategy_experiments import load_data  # noqa: E402
from tenbagger_v8_2_production import BacktestEngine  # noqa: E402


def main():
    prices, benchmark, vix, pit = load_data()
    dates = prices.index[252:]
    for name, cfg in [('base', mk()),
                      ('rb30', mk(STRATEGY_RESONANCE_BONUS=0.30)),
                      ('vt40', mk(VOLATILITY_TARGET=0.40))]:
        eng = BacktestEngine(cfg)
        r = eng.run(prices, benchmark, pit, use_next_day_open=True, vix=vix)
        pv = pd.Series(r['portfolio_values'])
        pv.index = dates[:len(pv)]
        endv = pv[pv.index <= '2026-10-22'].iloc[-1]
        aug_oct = round((endv / pv[pv.index <= '2026-08-21'].iloc[-1] - 1) * 100, 1)
        ytd26 = round((endv / pv[pv.index <= '2025-12-31'].iloc[-1] - 1) * 100, 1)
        print(f'{name}: 2026YTD {ytd26}% | 8/24-10/22 window {aug_oct}%',
              flush=True)


if __name__ == '__main__':
    main()
