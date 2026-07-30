#!/usr/bin/env python3
"""Regime detection sensitivity experiments (full pool, 2020-01 -> latest).

Single-bit variants of MacroTiming.detect (anti-overfitting discipline: one
change at a time, measured against base v8.6):
  base            : current logic
  neutral_100d    : NEUTRAL needs above_100d instead of above_50d
  neutral_200d    : NEUTRAL needs above_200d instead of above_50d
  bull_no_mom     : BULL drops the mom_20 > 0 requirement
  lenient_combo   : neutral_100d + bull_no_mom (interaction check)

Writes results to data/regime_experiments.json
"""
import os, sys, json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tenbagger_v8_2_production import (Config, BacktestEngine, MacroTiming)
from strategy_experiments import load_data, yearly, seg_return

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
OUT = os.path.join(DATA, 'regime_experiments.json')
ORIG_DETECT = MacroTiming.detect


def make_detect(neutral_ma: int = 50, bull_mom: bool = True):
    """Parameterized clone of MacroTiming.detect (single-bit knobs only)."""
    def detect(self, prices: pd.DataFrame, t: int):
        spy_col = 'SPY' if 'SPY' in prices.columns else prices.columns[0]
        spy = prices[spy_col].iloc[:t + 1]
        if t < 60 or len(spy) < 60:
            return 'NEUTRAL', {'position_factor': 0.85, 'hedge_ratio': 0.05,
                               'reason': 'insufficient_data'}
        recent_ret = spy.pct_change().dropna().iloc[-20:]
        current_vol = recent_ret.std() * np.sqrt(252)

        above_200d = False
        if t >= 200 and len(spy) >= 200:
            ma200 = spy.rolling(200).mean()
            if not ma200.isna().iloc[-1]:
                above_200d = spy.iloc[-1] > ma200.iloc[-1]
        above_n = False
        if t >= neutral_ma and len(spy) >= neutral_ma:
            man = spy.rolling(neutral_ma).mean()
            if not man.isna().iloc[-1]:
                above_n = spy.iloc[-1] > man.iloc[-1]
        mom_20 = spy.iloc[-1] / spy.iloc[-20] - 1 if t >= 20 and len(spy) >= 20 else 0

        bull_ok = current_vol < 0.18 and above_200d and (mom_20 > 0 if bull_mom else True)
        if bull_ok:
            regime, pf, hr = 'BULL', 1.0, 0.0
        elif current_vol < 0.25 and above_n:
            regime, pf, hr = 'NEUTRAL', 0.85, 0.05
        elif current_vol < 0.35:
            regime, pf, hr = 'BEAR', 0.60, 0.15
        else:
            regime, pf, hr = 'PANIC', 0.40, 0.25

        if t >= 40 and len(spy) >= 41:
            older_vol_data = spy.pct_change().dropna().iloc[-40:-20]
            if len(older_vol_data) >= 19:
                older_vol = older_vol_data.std() * np.sqrt(252)
                if current_vol - older_vol > 0.05:
                    pf *= 0.80
                    hr = min(hr + 0.10, 0.30)
        return regime, {
            'regime': regime, 'position_factor': max(pf, 0.20),
            'hedge_ratio': hr, 'current_vol': current_vol,
            'above_200d': above_200d, 'mom_20': mom_20,
        }
    return detect


VARIANTS = [
    ('base',          dict(neutral_ma=50,  bull_mom=True)),
    ('neutral_100d',  dict(neutral_ma=100, bull_mom=True)),
    ('neutral_200d',  dict(neutral_ma=200, bull_mom=True)),
    ('bull_no_mom',   dict(neutral_ma=50,  bull_mom=False)),
    ('lenient_combo', dict(neutral_ma=100, bull_mom=False)),
]


def regime_distribution(prices, t0=252):
    spy_df = prices[['SPY']]
    macro = MacroTiming(Config())
    counts, pfs = {}, []
    for t in range(t0, len(prices)):
        r, sig = MacroTiming.detect(macro, spy_df, t)
        counts[r] = counts.get(r, 0) + 1
        pfs.append(sig['position_factor'])
    n = sum(counts.values())
    return {k: round(v / n * 100, 1) for k, v in sorted(counts.items())}, \
           round(float(np.mean(pfs)), 3)


def run_one(name, prices, benchmark, vix, fundamentals, params):
    MacroTiming.detect = make_detect(**params)
    try:
        dist, avg_pf = regime_distribution(prices)
        eng = BacktestEngine(Config())
        res = eng.run(prices, benchmark, fundamentals,
                      use_next_day_open=True, vix=vix)
    finally:
        MacroTiming.detect = ORIG_DETECT
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
        'regime_dist_pct': dist,
        'avg_position_factor': avg_pf,
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
    for name, params in VARIANTS:
        if which != 'all' and name != which:
            continue
        print(f'running {name} ...', flush=True)
        results[name] = run_one(name, prices, benchmark, vix, fundamentals, params)
        r = results[name]
        print(f"  {name}: ret {r['total_return']}% cagr {r['cagr']}% "
              f"sharpe {r['sharpe']} mdd {r['mdd']}% dist {r['regime_dist_pct']}",
              flush=True)
        json.dump(results, open(OUT, 'w'), indent=1)
    print('done ->', OUT)


if __name__ == '__main__':
    main()
