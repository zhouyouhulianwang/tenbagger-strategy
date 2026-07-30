#!/usr/bin/env python3
"""Extend all price histories to the latest available day (Nasdaq 1700-row window).

Replaces data/universe/*.csv and the 12 root CSVs with 2020-01-10 -> latest
rows. Validation per rule: row count >= old, overlap closes vs the
git-committed version must match within 0.5% (split-adjustment drift).
"""
import json, os, subprocess, sys, time, urllib.request

HDRS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://www.nasdaq.com/',
}
ETF = {'SPY', 'SQQQ'}
ROOT_FILES = {
    'AAPL': 'aapl.csv', 'MSFT': 'msft.csv', 'NVDA': 'nvda.csv',
    'AMZN': 'amzn_2021_2023.csv', 'GOOGL': 'googl_2021_2023.csv',
    'META': 'meta_2021_2023.csv', 'TSLA': 'tsla.csv',
    'JPM': 'jpm.csv', 'UNH': 'unh.csv', 'SPY': 'spy_2021_2023_v2.csv',
    'SQQQ': 'sqqq.csv',
}
MIN_DATE = '2020-01-10'

def fetch(symbol, tries=6):
    asset = 'etf' if symbol in ETF else 'stocks'
    url_sym = symbol.replace('.', '%2E')
    best = []
    for attempt in range(tries):
        try:
            url = (f'https://api.nasdaq.com/api/quote/{url_sym}/historical?assetclass={asset}'
                   f'&fromdate=2018-01-01&todate=2026-07-31&limit=1700')
            req = urllib.request.Request(url, headers=HDRS)
            data = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
            rows = (data.get('data') or {}).get('tradesTable', {}).get('rows', []) or []
            best = max(best, rows, key=len)
            if len(best) >= 1600:
                break
        except Exception:
            pass
        time.sleep(0.8 + attempt * 0.5)
    return best

def to_lines(rows):
    num = lambda x: x.replace('$', '').replace(',', '').strip()
    out = []
    for r in reversed(rows):  # newest first -> oldest first
        m, d, y = r['date'].split('/')
        iso = f'{y}-{m}-{d}'
        if iso < MIN_DATE:
            continue
        out.append(f"{iso},{num(r['open'])},{num(r['high'])},{num(r['low'])},{num(r['close'])},{num(r['volume'])}")
    return out

def committed_closes(path):
    """closes of the git-committed version of path (for overlap validation)"""
    try:
        content = subprocess.run(['git', 'show', f'HEAD:{path}'],
                                 capture_output=True, text=True, check=True).stdout
        closes = {}
        for line in content.strip().splitlines()[1:]:
            p = line.split(',')
            closes[p[0]] = float(p[4])
        return closes
    except Exception:
        return {}

def main():
    targets = {}  # path -> symbol
    for fn in sorted(os.listdir('data/universe')):
        if fn.endswith('.csv') and not fn.startswith('_'):
            targets[f'data/universe/{fn}'] = fn[:-4]
    for sym, fn in ROOT_FILES.items():
        targets[f'data/{fn}'] = sym

    ok, failed, mismatch = [], [], []
    t0 = time.time()
    for i, (path, sym) in enumerate(sorted(targets.items(), key=lambda x: x[1])):
        rows = fetch(sym)
        lines = to_lines(rows)
        old_closes = committed_closes(path)
        if len(lines) <= len(old_closes):
            failed.append((sym, f'rows {len(lines)} <= old {len(old_closes)}'))
        else:
            # overlap validation
            bad = 0
            new_closes = {l.split(',')[0]: float(l.split(',')[4]) for l in lines}
            for d, c in old_closes.items():
                if d in new_closes and c > 0 and abs(new_closes[d] / c - 1) > 0.005:
                    bad += 1
            if bad > 3:
                mismatch.append((sym, bad))
            else:
                with open(path, 'w') as f:
                    f.write('Date,Open,High,Low,Close,Volume\n' + '\n'.join(lines) + '\n')
                ok.append(sym)
        if (i + 1) % 50 == 0:
            print(f"[{i+1}/{len(targets)}] {(time.time()-t0)/60:.1f}min ok={len(ok)} fail={len(failed)} mismatch={len(mismatch)}",
                  flush=True)
    print(f"DONE {(time.time()-t0)/60:.1f}min ok={len(ok)} fail={len(failed)} mismatch={len(mismatch)}")
    print("failed:", failed)
    print("mismatch:", mismatch)

if __name__ == '__main__':
    main()
