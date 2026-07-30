#!/usr/bin/env python3
"""Strategy attribution & ablation experiments (full pool, 2020-01 -> latest).

Loads price/PIT data once, then runs a battery of config-patched backtests:
  - solo_<strat>   : one strategy at 100% weight in every regime
  - abl_no_<strat> : that strategy zeroed out (others unchanged, NOT renormalized)
  - hedge_*        : hedge off / VIX 30 / 5% size
  - risk_off       : daily-loss & drawdown breakers effectively disabled
  - filt_*         : 21d-high / volatility filters off
  - stops_*        : wider stops / stops off
Writes results to data/strategy_experiments.json
"""
import os, sys, json, copy, time
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tenbagger_v8_2_production import (Config, BacktestEngine, PointInTimeFundamentals,
                                       PortfolioConstructor)

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
OUT = os.path.join(DATA, 'strategy_experiments.json')


def load_data():
    cfg = Config()
    price_files = {}
    uni_dir = os.path.join(DATA, 'universe')
    for sym in cfg.UNIVERSE:
        fp = os.path.join(uni_dir, f'{sym}.csv')
        if os.path.exists(fp):
            price_files[sym] = fp
    price_files['SPY'] = os.path.join(DATA, 'spy_2021_2023_v2.csv')
    price_files['SQQQ'] = os.path.join(DATA, 'sqqq.csv')
    all_data = {}
    for sym, fp in price_files.items():
        df = pd.read_csv(fp, index_col=0, parse_dates=True)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        all_data[sym] = df['Close'] if 'Close' in df.columns else df.iloc[:, 0]
    prices = pd.DataFrame(all_data)
    first_spy = prices['SPY'].first_valid_index()
    late = [c for c in prices.columns
            if c not in ('SPY', 'SQQQ') and prices[c].first_valid_index() > first_spy]
    prices = prices.drop(columns=late).ffill().dropna()
    benchmark = prices['SPY']
    vdf = pd.read_csv(os.path.join(DATA, 'vix.csv'))
    vdf.columns = [c.strip().upper() for c in vdf.columns]
    vix = pd.Series(vdf['CLOSE'].values,
                    index=pd.to_datetime(vdf['DATE'], format='%m/%d/%Y'), name='VIX')
    vix = vix.reindex(prices.index, method='ffill').dropna()
    fundamentals = PointInTimeFundamentals(cfg, pit_file=os.path.join(DATA, 'pit_fundamentals_full.json'))
    return prices, benchmark, vix, fundamentals


def make_cfg(mutate=None):
    cfg = Config()
    if mutate:
        mutate(cfg)
    return cfg


def solo(name):
    def m(cfg):
        for w in ('WEIGHT_BULL', 'WEIGHT_NEUTRAL', 'WEIGHT_BEAR', 'WEIGHT_PANIC'):
            setattr(cfg, w, {'momentum': 0, 'sector': 0, 'growth': 0, 'value': 0,
                             'defensive': 0, name: 1.0})
    return m


def ablate(name):
    def m(cfg):
        for w in ('WEIGHT_BULL', 'WEIGHT_NEUTRAL', 'WEIGHT_BEAR', 'WEIGHT_PANIC'):
            d = dict(getattr(cfg, w))
            d[name] = 0.0
            setattr(cfg, w, d)
    return m


def m_hedge_off(cfg):
    cfg.ENABLE_HEDGE = False

def m_hedge_vix30(cfg):
    cfg.HEDGE_VIX_ACTIVATE = 30.0
    cfg.HEDGE_VIX_DEACTIVATE = 29.75

def m_hedge_pct5(cfg):
    cfg.HEDGE_POSITION_PCT = 0.05

def m_risk_off(cfg):
    cfg.DAILY_LOSS_LIMIT_PCT = -0.99
    cfg.MAX_DRAWDOWN_LIMIT_PCT = -0.99

def m_filt_vol_off(cfg):
    cfg.MAX_VOLATILITY = 10.0  # disables both the global vol filter and momentum's vol gate

def m_stops_wide(cfg):
    cfg.HARD_STOP_LOSS_PCT = -0.15
    cfg.TRAILING_STOP_50_PCT = -0.30
    cfg.TRAILING_STOP_100_PCT = -0.35

def m_stops_off(cfg):
    cfg.HARD_STOP_LOSS_PCT = -0.99
    cfg.TRAILING_STOP_50_PCT = -0.99
    cfg.TRAILING_STOP_100_PCT = -0.99


def m_compress_only(cfg):
    cfg.HEDGE_POSITION_PCT = 0.001  # ~$100 SQQQ: keeps compression, no real hedge drag

def m_opt_v1(cfg):
    # remove growth (negative contributor) + hedge at 5%
    for w in ('WEIGHT_BULL', 'WEIGHT_NEUTRAL', 'WEIGHT_BEAR', 'WEIGHT_PANIC'):
        d = dict(getattr(cfg, w)); d['growth'] = 0.0; setattr(cfg, w, d)
    cfg.HEDGE_POSITION_PCT = 0.05

def m_opt_v2(cfg):
    # growth weight transferred to value (best-Sharpe strategy) + hedge at 5%
    transfers = {
        'WEIGHT_BULL':     {'momentum': 0.35, 'sector': 0, 'growth': 0, 'value': 0.35, 'defensive': 0.05},
        'WEIGHT_NEUTRAL':  {'momentum': 0.25, 'sector': 0, 'growth': 0, 'value': 0.40, 'defensive': 0.10},
        'WEIGHT_BEAR':     {'momentum': 0.10, 'sector': 0, 'growth': 0, 'value': 0.50, 'defensive': 0.25},
        'WEIGHT_PANIC':    {'momentum': 0.05, 'sector': 0, 'growth': 0, 'value': 0.35, 'defensive': 0.50},
    }
    for w, d in transfers.items():
        setattr(cfg, w, d)
    cfg.HEDGE_POSITION_PCT = 0.05

def m_opt_v3(cfg):
    # opt_v1 + hedge at 2.5% (drag even lower, compression kept)
    for w in ('WEIGHT_BULL', 'WEIGHT_NEUTRAL', 'WEIGHT_BEAR', 'WEIGHT_PANIC'):
        d = dict(getattr(cfg, w)); d['growth'] = 0.0; setattr(cfg, w, d)
    cfg.HEDGE_POSITION_PCT = 0.025


EXPERIMENTS = [
    ('base', None),
    ('solo_momentum', solo('momentum')),
    ('solo_growth', solo('growth')),
    ('solo_value', solo('value')),
    ('solo_defensive', solo('defensive')),
    ('abl_no_momentum', ablate('momentum')),
    ('abl_no_growth', ablate('growth')),
    ('abl_no_value', ablate('value')),
    ('abl_no_defensive', ablate('defensive')),
    ('hedge_off', m_hedge_off),
    ('hedge_vix30', m_hedge_vix30),
    ('hedge_pct5', m_hedge_pct5),
    ('risk_off', m_risk_off),
    ('filt_vol_off', m_filt_vol_off),
    ('stops_wide', m_stops_wide),
    ('stops_off', m_stops_off),
    ('compress_only', m_compress_only),
    ('opt_v1', m_opt_v1),
    ('opt_v2', m_opt_v2),
    ('opt_v3', m_opt_v3),
]


def yearly(pv, dates):
    s = pd.Series(pv, index=dates[:len(pv)])
    out = {}
    for y, g in s.groupby(s.index.year):
        out[str(y)] = round((g.iloc[-1] / g.iloc[0] - 1) * 100, 1)
    return out


def seg_return(pv, dates, start, end):
    s = pd.Series(pv, index=dates[:len(pv)])
    seg = s.loc[start:end]
    if len(seg) < 2:
        return None
    return round((seg.iloc[-1] / seg.iloc[0] - 1) * 100, 1)


def run_one(name, prices, benchmark, vix, fundamentals, mutate, filt21d_off=False):
    cfg = make_cfg(mutate)
    if filt21d_off:
        PortfolioConstructor.filter_21d_high = lambda self, signals, p, t, threshold=0.8: signals
    eng = BacktestEngine(cfg)
    res = eng.run(prices, benchmark, fundamentals, use_next_day_open=True, vix=vix)
    dates = prices.index[252:]
    pv = res['portfolio_values']
    spy = benchmark.iloc[252:252 + len(pv)]
    spy_yearly = yearly((spy / spy.iloc[0]).tolist(), spy.index)
    return {
        'total_return': round(res['total_return'] * 100, 1),
        'cagr': round(res['cagr'] * 100, 1),
        'sharpe': round(res['sharpe'], 2),
        'mdd': round(res['max_drawdown'] * 100, 1),
        'excess': round(res['excess_return'] * 100, 1),
        'win_rate': round(res['win_rate'] * 100, 1),
        'n_trades': res['n_trades'],
        'yearly': yearly(pv, dates),
        'spy_yearly': spy_yearly,
        'seg_2020_2023': seg_return(pv, dates, '2020-01-01', '2023-12-31'),
        'seg_2024_2026': seg_return(pv, dates, '2024-01-01', '2026-12-31'),
        'spy_seg_2020_2023': seg_return((spy / spy.iloc[0]).tolist(), spy.index, '2020-01-01', '2023-12-31'),
        'spy_seg_2024_2026': seg_return((spy / spy.iloc[0]).tolist(), spy.index, '2024-01-01', '2026-12-31'),
        'trades': res['trades'],  # kept for attribution (base only)
    }


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    print('loading data...', flush=True)
    prices, benchmark, vix, fundamentals = load_data()
    print(f'data: {len(prices)} days x {len(prices.columns)} cols', flush=True)

    results = {}
    if os.path.exists(OUT):
        results = json.load(open(OUT))

    for name, mutate in EXPERIMENTS:
        if which != 'all' and name != which:
            continue
        t0 = time.time()
        filt21d_off = name == 'filt_21d_off'
        r = run_one(name, prices, benchmark, vix, fundamentals, mutate, filt21d_off)
        results[name] = r
        # save without trades to keep the file small; base trades saved separately
        slim = {k: v for k, v in r.items() if k != 'trades'}
        results[name] = {**slim, 'trades': r['trades']}
        json.dump({k: {kk: vv for kk, vv in v.items() if kk != 'trades'} for k, v in results.items()},
                  open(OUT, 'w'), indent=1,
                  default=lambda o: float(o) if hasattr(o, '__float__') else str(o))
        if name == 'base':
            json.dump(r['trades'], open(os.path.join(DATA, 'base_trades.json'), 'w'),
                      default=lambda o: float(o) if hasattr(o, '__float__') else str(o))
        print(f"{name}: ret={r['total_return']}% sharpe={r['sharpe']} mdd={r['mdd']}% "
              f"({time.time()-t0:.0f}s)", flush=True)

    # filt_21d_off as an extra experiment (needs the monkeypatch)
    if which in ('all', 'filt_21d_off'):
        t0 = time.time()
        r = run_one('filt_21d_off', prices, benchmark, vix, fundamentals, None, filt21d_off=True)
        results['filt_21d_off'] = r
        json.dump({k: {kk: vv for kk, vv in v.items() if kk != 'trades'} for k, v in results.items()},
                  open(OUT, 'w'), indent=1,
                  default=lambda o: float(o) if hasattr(o, '__float__') else str(o))
        print(f"filt_21d_off: ret={r['total_return']}% sharpe={r['sharpe']} ({time.time()-t0:.0f}s)", flush=True)

    print('DONE', flush=True)


if __name__ == '__main__':
    main()
