#!/usr/bin/env python3
"""Optimization battery (user request 2026-08-26: 提高收益率) - v9.3 base.

Six single-bit groups against the CURRENT production config. All prior
scans (RESULTS.md) covered: sizing mode, MAX_POSITIONS, phase, daily-loss
threshold, risk reentry, stall-swap, exhaustion, volume floor, hedge,
de-gross, strategy ablation, momentum periods/weights, position cap,
vol gate (coarse, old base), regime thresholds. These dimensions have
NEVER been scanned:

  cycle     : REBALANCE_DAYS 3/5(base)/10/15/20 - cycle LENGTH (phase was
              scanned; length never was). Fewer trades = less cost but
              staler signals; longer cycles = less churn.
  voltarget : VOLATILITY_TARGET 0.15/0.20/0.25(base)/0.30/0.40 - sizing
              aggression (min(VT/vol, 2) in the inline sizer)
  rsmin     : RS_MIN 50/60(base)/70/80 - momentum strength gate
  resonance : STRATEGY_RESONANCE_BONUS 0/0.10/0.20(base)/0.30 - multi-
              strategy agreement bonus in combine()
  volgate   : MAX_VOLATILITY 0.50/0.60(base)/0.75 - candidate vol ceiling
              (v8.x scan on the OLD base said 60; recheck on v3 + finer)
  minpos    : MIN_SINGLE_POSITION_PCT 0.00/0.05(base) - the 5% floor

Base runs ONCE and is injected into every group (same-config duplicate
runs wasted ~15min in the 2026-08-22 scans). Verdict discipline: a win
must beat base on Sharpe AND not hole either segment or any single year
by >10pp - headline-return-only wins are best-of-n noise (see n5/p1).

Usage: python3 optimize_battery_experiments.py [group|all]
Writes data/optimize_battery_experiments.json (merge-on-dump, resume-safe).
"""
import os, sys, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tenbagger_v8_2_production import Config, BacktestEngine
from strategy_experiments import load_data, yearly, seg_return

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
OUT = os.path.join(DATA, 'optimize_battery_experiments.json')


def mk(**kw):
    c = Config()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


BASE = mk()

GROUPS = {
    'cycle': [
        ('d3',  mk(REBALANCE_DAYS=3)),
        ('d5',  BASE),
        ('d10', mk(REBALANCE_DAYS=10)),
        ('d15', mk(REBALANCE_DAYS=15)),
        ('d20', mk(REBALANCE_DAYS=20)),
    ],
    'voltarget': [
        ('vt15', mk(VOLATILITY_TARGET=0.15)),
        ('vt20', mk(VOLATILITY_TARGET=0.20)),
        ('vt25', BASE),
        ('vt30', mk(VOLATILITY_TARGET=0.30)),
        ('vt40', mk(VOLATILITY_TARGET=0.40)),
    ],
    'rsmin': [
        ('rs50', mk(RS_MIN=50.0)),
        ('rs60', BASE),
        ('rs70', mk(RS_MIN=70.0)),
        ('rs80', mk(RS_MIN=80.0)),
    ],
    'resonance': [
        ('rb00', mk(STRATEGY_RESONANCE_BONUS=0.0)),
        ('rb10', mk(STRATEGY_RESONANCE_BONUS=0.10)),
        ('rb20', BASE),
        ('rb30', mk(STRATEGY_RESONANCE_BONUS=0.30)),
    ],
    'volgate': [
        ('vg50', mk(MAX_VOLATILITY=0.50)),
        ('vg60', BASE),
        ('vg75', mk(MAX_VOLATILITY=0.75)),
    ],
    'minpos': [
        ('mp0', mk(MIN_SINGLE_POSITION_PCT=0.0)),
        ('mp5', BASE),
    ],
    # informational only: interaction check of the two single-variable
    # winners (rb30 + vt40). NOT a production candidate by itself —
    # combining winners is a new search dimension (best-of-n risk).
    'combo': [
        ('rb30vt40', mk(STRATEGY_RESONANCE_BONUS=0.30, VOLATILITY_TARGET=0.40)),
    ],
}


def run_one(cfg, prices, benchmark, vix, fundamentals):
    eng = BacktestEngine(cfg)
    res = eng.run(prices, benchmark, fundamentals,
                  use_next_day_open=True, vix=vix)
    dates = prices.index[252:]
    pv = res['portfolio_values']
    return {
        'total_return': round(res['total_return'] * 100, 1),
        'cagr': round(res['cagr'] * 100, 1),
        'sharpe': round(res['sharpe'], 2),
        'mdd': round(res['max_drawdown'] * 100, 1),
        'n_trades': res['n_trades'],
        'yearly': yearly(pv, dates),
        'seg_2020_2023': seg_return(pv, dates, '2020-01-01', '2023-12-31'),
        'seg_2024_2026': seg_return(pv, dates, '2024-01-01', '2026-12-31'),
    }


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    print(f'loading data... group={which}', flush=True)
    import hashlib, glob as _g
    def _h(p):
        try:
            return hashlib.md5(open(p, 'rb').read()).hexdigest()[:12]
        except Exception:
            return 'NA'
    pit_hash = _h(os.path.join(DATA, 'pit_fundamentals_full.json'))
    uni_dir = os.path.join(DATA, 'universe')
    uni_hash = hashlib.md5(''.join(
        f"{os.path.basename(f)}:{os.path.getsize(f)}:{int(os.path.getmtime(f))};"
        for f in sorted(_g.glob(os.path.join(uni_dir, '*.csv')))).encode()).hexdigest()[:12]
    spy_hash = _h(os.path.join(DATA, 'spy_2021_2023_v2.csv'))
    vix_hash = _h(os.path.join(DATA, 'vix.csv'))
    print(f'INPUT HASHES: pit={pit_hash} universe={uni_hash} '
          f'spy={spy_hash} vix={vix_hash}', flush=True)
    prices, benchmark, vix, fundamentals = load_data()
    print(f'data loaded: {prices.shape[1]} symbols, '
          f'{prices.index[0].date()} -> {prices.index[-1].date()}', flush=True)

    results = json.load(open(OUT)) if os.path.exists(OUT) else {}

    def dump(group, name, r):
        r['input_hash'] = f'pit={pit_hash},uni={uni_hash},spy={spy_hash}'
        try:
            disk = json.load(open(OUT))
        except Exception:
            disk = {}
        disk.setdefault(group, {})[name] = r
        json.dump(disk, open(OUT, 'w'), indent=1)

    # base runs once, injected into every group
    if 'base' not in results.get('_base', {}):
        print('running base (current production config) ...', flush=True)
        dump('_base', 'base', run_one(BASE, prices, benchmark, vix, fundamentals))
        print(f"  base: ret {results.get('_base', {}).get('base', {}).get('total_return')}", flush=True)
    base_r = json.load(open(OUT))['_base']['base']
    print(f"base: {base_r['total_return']}%/{base_r['sharpe']}/{base_r['mdd']}% "
          f"segs {base_r['seg_2020_2023']}/{base_r['seg_2024_2026']}", flush=True)

    for group, variants in GROUPS.items():
        if which != 'all' and group != which:
            continue
        for name, cfg in variants:
            if name in results.get(group, {}):
                print(f'skip {group}/{name} (already done)', flush=True)
                continue
            if cfg is BASE:
                dump(group, name, dict(base_r))
                print(f'  {group}/{name}: = base (injected)', flush=True)
                continue
            print(f'running {group}/{name} ...', flush=True)
            r = run_one(cfg, prices, benchmark, vix, fundamentals)
            print(f"  {group}/{name}: ret {r['total_return']}% sharpe {r['sharpe']} "
                  f"mdd {r['mdd']}% segs {r['seg_2020_2023']}/{r['seg_2024_2026']}",
                  flush=True)
            dump(group, name, r)
    print('done ->', OUT)


if __name__ == '__main__':
    main()
