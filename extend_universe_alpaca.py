#!/usr/bin/env python3
"""Extend all price histories to the latest available day via ALPACA
(rule#2: Alpaca is the preferred data source). MERGE-APPEND mode:
keeps every row of the existing CSVs and appends only Alpaca bars
dated AFTER the old file's last row.

Why merge-append (2026-10-23 finding): Alpaca IEX-feed daily history
starts 2020-07-27, but our Nasdaq-sourced files start 2020-01-10.
A full replace would silently drop the first ~6.5 months of 2020
(139 trading days) — the COVID crash/recovery the honest baseline
depends on. Merge-append preserves the old lineage 2020-01-10 ->
2026-07-29 and stitches Alpaca IEX bars 2026-07-30 -> latest.

Why not extend_universe.py (Nasdaq): on 2026-10-23 it returned data
ending 2026-07-31 only (stale endpoint). Alpaca batch daily bars
(feed=iex, adjustment=all) are the same source the live monitor uses,
so backtest and live see ONE data lineage going forward.

Validation (per standing rule: verify before overwrite):
  - overlap closes (last 20 common days) median abs diff < 0.5%
    (IEX daily close vs Nasdaq official close tolerance)
  - merged rows > old rows, merged end > old end
  - on ANY failure the old file is left untouched
Report: data/universe/_extend_validation.json
Categories: extended / new_file / current / failed / empty.

Volume note: IEX-feed volume is ~2-3% of consolidated. Production
config has MIN_ADV_SHARES=0 (volume filters OFF), so volume
comparability does not affect the strategy; closes are what matter.

Run on the server (Alpaca creds in /root/.tenbagger-env):
  cd /data/tenbagger && source /root/.tenbagger-env && \
    ./venv/bin/python extend_universe_alpaca.py
"""
import json
import os
import sys
import time
import urllib.request

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tenbagger_v8_2_production import Config, AlpacaClient  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
UNI = os.path.join(DATA, 'universe')
ROOT_FILES = {
    'SPY': 'spy_2021_2023_v2.csv',
    'SQQQ': 'sqqq.csv',
}
MIN_DATE = '2020-01-10'
MAX_DIFF_PCT = 0.5


def fetch_raw(client, symbols):
    """Paginated raw bars (o/h/l/c/v) for all symbols, 2020 -> now."""
    end = pd.Timestamp.now()
    start = pd.Timestamp(MIN_DATE)
    url = f"{client.config.ALPACA_DATA_URL}/v2/stocks/bars"
    collected = {s: [] for s in symbols}
    page_token = None
    pages = 0
    while True:
        params = {
            'symbols': ','.join(symbols),
            'start': start.isoformat() + 'Z',
            'end': end.isoformat() + 'Z',
            'timeframe': '1Day',
            'feed': client.config.DATA_FEED,
            'adjustment': 'all',
            'limit': 10000,
        }
        if page_token:
            params['page_token'] = page_token
        r = client._request('GET', url, params=params)
        if r.status_code != 200:
            raise RuntimeError(f'batch bars HTTP {r.status_code}')
        payload = r.json()
        for sym, bars in (payload.get('bars') or {}).items():
            collected.setdefault(sym, []).extend(bars)
        page_token = payload.get('next_page_token')
        pages += 1
        if not page_token:
            break
        time.sleep(0.3)
    print(f'fetched {sum(len(v) for v in collected.values())} bars '
          f'for {sum(1 for v in collected.values() if v)}/{len(symbols)} symbols '
          f'in {pages} pages', flush=True)
    return collected


def bars_to_df(bars):
    df = pd.DataFrame(bars)
    # IEX daily bars are timestamped 05:00 UTC (= ET midnight); normalize
    # to a plain date so rows match the existing CSV format exactly.
    df['t'] = pd.to_datetime(df['t']).dt.tz_localize(None).dt.normalize()
    df = df.rename(columns={'t': 'Date', 'o': 'Open', 'h': 'High',
                            'l': 'Low', 'c': 'Close', 'v': 'Volume'})
    df = df[['Date', 'Open', 'High', 'Low', 'Close', 'Volume']]
    return df.set_index('Date').sort_index()


def merge_append(old_path, new_df):
    """Return (merged_df or None, category, reason)."""
    if not os.path.exists(old_path):
        return new_df, 'new_file', 'new file'
    old = pd.read_csv(old_path, index_col=0, parse_dates=True)
    old.index = pd.to_datetime(old.index).normalize()
    old = old[~old.index.duplicated(keep='last')].sort_index()
    new_df = new_df[~new_df.index.duplicated(keep='last')]

    common = old.index.intersection(new_df.index)
    med = None
    if len(common) >= 20:
        chk = common[-20:]
        diff = (new_df.loc[chk, 'Close'] / old.loc[chk, 'Close'] - 1).abs() * 100
        med = float(diff.median())
        if med > MAX_DIFF_PCT:
            return None, 'failed', f'overlap median diff {med:.3f}% > {MAX_DIFF_PCT}%'

    tail = new_df[new_df.index > old.index[-1]]
    if tail.empty:
        return None, 'current', f'already ends {old.index[-1].date()}'
    merged = pd.concat([old, tail])
    if len(merged) <= len(old):
        return None, 'failed', 'merged not longer than old'
    reason = f'+{len(tail)} rows -> {merged.index[-1].date()}'
    if med is not None:
        reason += f' (overlap diff {med:.3f}%)'
    else:
        reason += ' (short overlap)'
    return merged, 'extended', reason


def main():
    cfg = Config()
    client = AlpacaClient(cfg)
    symbols = list(cfg.UNIVERSE) + ['SQQQ']  # SPY already in UNIVERSE
    collected = fetch_raw(client, symbols)

    report = {'extended': [], 'new_file': [], 'current': [],
              'failed': [], 'empty': []}
    for sym in symbols:
        bars = collected.get(sym) or []
        path = os.path.join(UNI, f'{sym}.csv')
        if sym in ROOT_FILES:
            path = os.path.join(DATA, ROOT_FILES[sym])
        if not bars:
            report['empty'].append(sym)
            continue
        new_df = bars_to_df(bars)
        merged, cat, reason = merge_append(path, new_df)
        if merged is not None:
            merged.to_csv(path)
        report[cat].append(f'{sym}: {reason}')

    # VIX: CBOE official history
    try:
        import io
        with urllib.request.urlopen(cfg.VIX_CBOE_URL, timeout=30) as r:
            vix_csv = r.read().decode()
        vdf = pd.read_csv(io.StringIO(vix_csv))
        vdf.columns = [c.strip().upper() for c in vdf.columns]
        with open(os.path.join(DATA, 'vix.csv'), 'w') as f:
            f.write(vix_csv)
        report['vix_end'] = str(vdf['DATE'].iloc[-1])
    except Exception as e:
        report['vix_error'] = str(e)

    with open(os.path.join(UNI, '_extend_validation.json'), 'w') as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    print(' '.join(f'{k}={len(v)}' for k, v in report.items()
                   if isinstance(v, list)), flush=True)
    for cat in ('failed', 'empty'):
        if report[cat]:
            print(f'{cat}:', *report[cat][:20], sep='\n  ')


if __name__ == '__main__':
    main()
