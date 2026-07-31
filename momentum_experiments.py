#!/usr/bin/env python3
"""Momentum strategy enhancement experiments (v8.7 base, full pool).

Base: 21/63/126/252d momentum [0.30,0.35,0.25,0.10] + RS rating + MA50 gate.
Variants (single-concept changes, same gates everywhere: rs>=60, vol cap,
above_50d, >=2 of mom_21/63/126 positive):
  mp6_eq        : 6 periods [1,5,21,63,126,252] equal weight
  mp6_w         : 6 periods weighted [0.05,0.10,0.20,0.30,0.25,0.10] (peak 63d)
  base_rsi      : base + RSI(14) overlay  (rsi-50)/100*0.2
  base_rsi_gate : base + RSI overlay + require 50<=RSI<=75
  base_boll     : base + Bollinger %B(20,2) overlay  clamp(%B-0.5)*0.2
  combo         : mp6_w + RSI overlay + Bollinger overlay
Writes results to data/momentum_experiments.json
"""
import os, sys, json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tenbagger_v8_2_production import Config, BacktestEngine, MomentumStrategy
from strategy_experiments import load_data, yearly, seg_return

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
OUT = os.path.join(DATA, 'momentum_experiments.json')
ORIG_SCORE = MomentumStrategy.score

PERIODS6 = [1, 5, 21, 63, 126, 252]
W6_EQ = [1 / 6] * 6
W6_W = [0.05, 0.10, 0.20, 0.30, 0.25, 0.10]


def rsi(prices: pd.Series, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    d = prices.diff().dropna().iloc[-period:]
    gains = d.clip(lower=0).mean()
    losses = (-d.clip(upper=0)).mean()
    if losses == 0:
        return 100.0
    return 100 - 100 / (1 + gains / losses)


def bollinger_pctb(prices: pd.Series, period: int = 20, k: float = 2.0) -> float:
    if len(prices) < period:
        return 0.5
    w = prices.iloc[-period:]
    sd = w.std()
    if sd == 0:
        return 0.5
    ma = w.mean()
    return (prices.iloc[-1] - (ma - k * sd)) / (2 * k * sd)


def make_score(mode: str):
    def score(self, symbol, prices, benchmark, t):
        s = prices[symbol].iloc[:t + 1]
        b = benchmark.iloc[:t + 1]
        if len(s) < 252:
            return None
        ind = self.ind
        mom_21 = ind.momentum(s, 21)
        mom_63 = ind.momentum(s, 63)
        mom_126 = ind.momentum(s, 126)
        mom_252 = ind.momentum(s, 252)
        rs = ind.rs_rating(s, b, 126)
        above_50d = ind.above_ma(s, 50)
        above_200d = ind.above_ma(s, 200)
        vol = ind.volatility(s, 20)
        if rs < self.config.RS_MIN or vol > self.config.MAX_VOLATILITY or not above_50d:
            return None
        if sum([mom_21 > 0, mom_63 > 0, mom_126 > 0]) < 2:
            return None

        if mode in ('mp6_eq', 'mp6_w', 'combo'):
            w = W6_EQ if mode == 'mp6_eq' else W6_W
            moms = [ind.momentum(s, p) for p in PERIODS6]
            mom_score = sum(m * wi for m, wi in zip(moms, w))
        else:
            W = self.config.MOMENTUM_WEIGHTS
            mom_score = (mom_21 * W[0] + mom_63 * W[1] +
                         mom_126 * W[2] + mom_252 * W[3])

        trend_bonus = 0.10 if above_200d else 0.0
        rs_bonus = (rs - self.config.RS_MIN) / 100 * 0.15
        total = mom_score + trend_bonus + rs_bonus

        if mode in ('base_rsi', 'base_rsi_gate', 'combo'):
            r = rsi(s, 14)
            if mode == 'base_rsi_gate' and not (50 <= r <= 75):
                return None
            total += (r - 50) / 100 * 0.2
        if mode in ('base_boll', 'combo'):
            pb = bollinger_pctb(s, 20, 2.0)
            total += max(min(pb - 0.5, 0.5), -0.5) * 0.2

        return {'total': total, 'mom_21': mom_21, 'mom_63': mom_63,
                'mom_126': mom_126, 'mom_252': mom_252, 'rs': rs,
                'above_50d': above_50d, 'above_200d': above_200d,
                'volatility': vol, 'trend_bonus': trend_bonus,
                'rs_bonus': rs_bonus}
    return score


VARIANTS = ['base', 'mp6_eq', 'mp6_w', 'base_rsi', 'base_rsi_gate',
            'base_boll', 'combo']


def run_one(mode, prices, benchmark, vix, fundamentals):
    if mode != 'base':
        MomentumStrategy.score = make_score(mode)
    try:
        eng = BacktestEngine(Config())
        res = eng.run(prices, benchmark, fundamentals,
                      use_next_day_open=True, vix=vix)
    finally:
        MomentumStrategy.score = ORIG_SCORE
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
    for name in VARIANTS:
        if which != 'all' and name != which:
            continue
        print(f'running {name} ...', flush=True)
        results[name] = run_one(name, prices, benchmark, vix, fundamentals)
        r = results[name]
        print(f"  {name}: ret {r['total_return']}% sharpe {r['sharpe']} "
              f"mdd {r['mdd']}% segs {r['seg_2020_2023']}/{r['seg_2024_2026']}",
              flush=True)
        json.dump(results, open(OUT, 'w'), indent=1)
    print('done ->', OUT)


if __name__ == '__main__':
    main()
