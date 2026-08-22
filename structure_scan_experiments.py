#!/usr/bin/env python3
"""Structure scans (v9.2, full pool) - 2026-08-22 full review follow-ups.

Three independent single-bit groups:

  sizing    : SIZING_MODE vol_score (current backtest sizing, must
              reproduce 559.6/1.59/-22.8) vs equal (what live
              smart_rebalance() actually does -> quantifies the
              live/backtest sizing gap found in the review)
  positions : MAX_POSITIONS 5/6(current)/7/8/10 - never scanned before
              (only the 30% single-name cap was scanned, v8.8 era)
  phase     : REBALANCE_PHASE 0(current)-4 - shifts the 5-day cycle
              anchor; tests whether the weekly anchor's phase matters
              (live anchors Monday; backtest anchored at t=252)

Usage: python3 structure_scan_experiments.py [sizing|positions|phase|all]
Writes data/structure_scan_experiments.json (per-group sub-dicts).
"""
import os, sys, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tenbagger_v8_2_production import Config, BacktestEngine
from strategy_experiments import load_data, yearly, seg_return

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
OUT = os.path.join(DATA, 'structure_scan_experiments.json')


def mk(**kw):
    c = Config()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


GROUPS = {
    'sizing': [
        ('vol_score', mk()),                       # base
        ('equal',     mk(SIZING_MODE='equal')),
    ],
    'positions': [
        ('n5',  mk(MAX_POSITIONS=5)),
        ('n6',  mk()),                             # base
        ('n7',  mk(MAX_POSITIONS=7)),
        ('n8',  mk(MAX_POSITIONS=8)),
        ('n10', mk(MAX_POSITIONS=10)),
    ],
    'phase': [
        ('p0', mk()),                              # base
        ('p1', mk(REBALANCE_PHASE=1)),
        ('p2', mk(REBALANCE_PHASE=2)),
        ('p3', mk(REBALANCE_PHASE=3)),
        ('p4', mk(REBALANCE_PHASE=4)),
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
    # 2026-08-22: the sandbox mount flipped files mid-session and silently
    # changed backtest inputs between runs (same config -> 559.6 vs 432.6).
    # Hash every input file at load time and stamp it into each result so
    # cross-run comparability is verifiable, not assumed.
    import hashlib
    def _h(p):
        try:
            return hashlib.md5(open(p, 'rb').read()).hexdigest()[:12]
        except Exception:
            return 'NA'
    pit_hash = _h(os.path.join(DATA, 'pit_fundamentals_full.json'))
    uni_dir = os.path.join(DATA, 'universe')
    import glob as _g
    uni_hash = hashlib.md5(''.join(
        f"{os.path.basename(f)}:{os.path.getsize(f)}:{int(os.path.getmtime(f))};"
        for f in sorted(_g.glob(os.path.join(uni_dir, '*.csv')))).encode()).hexdigest()[:12]
    spy_hash = _h(os.path.join(DATA, 'spy_2021_2023_v2.csv'))
    sqqq_hash = _h(os.path.join(DATA, 'sqqq.csv'))
    vix_hash = _h(os.path.join(DATA, 'vix.csv'))
    print(f'INPUT HASHES: pit={pit_hash} universe={uni_hash} '
          f'spy={spy_hash} sqqq={sqqq_hash} vix={vix_hash}', flush=True)
    prices, benchmark, vix, fundamentals = load_data()
    results = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for group, variants in GROUPS.items():
        if which != 'all' and group != which:
            continue
        results.setdefault(group, {})
        for name, cfg in variants:
            if name in results.get(group, {}):
                print(f'skip {group}/{name} (already done)', flush=True)
                continue
            print(f'running {group}/{name} ...', flush=True)
            r = run_one(cfg, prices, benchmark, vix, fundamentals)
            r['input_hash'] = f'pit={pit_hash},uni={uni_hash},spy={spy_hash}'
            print(f"  {group}/{name}: ret {r['total_return']}% sharpe {r['sharpe']} "
                  f"mdd {r['mdd']}% segs {r['seg_2020_2023']}/{r['seg_2024_2026']}",
                  flush=True)
            # merge-on-dump: concurrent group processes each own one group
            # key; re-load the file and update only ours so we never wipe
            # another group's results (lost ~12min of compute to this race
            # on 2026-08-22 before the fix).
            try:
                disk = json.load(open(OUT))
            except Exception:
                disk = {}
            disk.setdefault(group, {})[name] = r
            json.dump(disk, open(OUT, 'w'), indent=1)
    print('done ->', OUT)


if __name__ == '__main__':
    main()
