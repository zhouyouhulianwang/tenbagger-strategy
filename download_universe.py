#!/usr/bin/env python3
"""Download Nasdaq 1000-row daily history for the full UNIVERSE (P2 task).
Writes data/universe/{SYM}.csv (Date,Open,High,Low,Close,Volume) and a
validation report data/universe/_validation.json. Invalid/suspended tickers
are revealed implicitly by empty responses.
"""
import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime

HDRS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Origin': 'https://www.nasdaq.com',
    'Referer': 'https://www.nasdaq.com/',
}
OUT = 'data/universe'
os.makedirs(OUT, exist_ok=True)

def fetch_nasdaq(symbol, min_rows=900, tries=6):
    """Full-range request is the only one that reliably returns rows; keep best."""
    url_sym = symbol.replace('.', '/')  # BRK.B -> BRK/B for nasdaq API
    best = []
    for attempt in range(tries):
        try:
            url = (f'https://api.nasdaq.com/api/quote/{url_sym}/historical?assetclass=stocks'
                   f'&fromdate=2018-01-01&todate=2024-01-01&limit=1000')
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode())
            rows = (data.get('data') or {}).get('tradesTable', {}).get('rows', []) or []
            if len(rows) > len(best):
                best = rows
            if len(best) >= min_rows:
                break
        except Exception:
            pass
        time.sleep(0.8 + attempt * 0.5)
    return best

def main():
    symbols = [l.strip() for l in open('/tmp/universe.txt') if l.strip()]
    # skip ones we already have in data/ root (same content)
    done, failed, short = [], [], {}
    t0 = time.time()
    for i, sym in enumerate(symbols):
        fp = os.path.join(OUT, f'{sym}.csv')
        if os.path.exists(fp) and os.path.getsize(fp) > 20000:
            done.append(sym); continue
        rows = fetch_nasdaq(sym)
        if len(rows) >= 900:
            rows = list(reversed(rows))  # API returns newest first
            def num(x):
                return x.replace('$', '').replace(',', '').strip()
            with open(fp, 'w') as f:
                f.write('Date,Open,High,Low,Close,Volume\n')
                for r in rows:
                    m, dd, y = r['date'].split('/')
                    f.write(f"{y}-{m}-{dd},{num(r['open'])},{num(r['high'])},"
                            f"{num(r['low'])},{num(r['close'])},{num(r['volume'])}\n")
            done.append(sym)
        else:
            if len(rows) == 0: failed.append(sym)
            else: short[sym] = len(rows)
        if (i + 1) % 25 == 0:
            el = time.time() - t0
            print(f"[{i+1}/{len(symbols)}] {el/60:.1f}min ok={len(done)} fail={len(failed)} short={len(short)}",
                  flush=True)
    report = {'ok': done, 'failed': failed, 'short': short, 'ts': datetime.now().isoformat()}
    with open(os.path.join(OUT, '_validation.json'), 'w') as f:
        json.dump(report, f, indent=1)
    print(f"DONE ok={len(done)} failed={len(failed)} short={len(short)}")
    print("failed:", failed)
    print("short:", short)

if __name__ == '__main__':
    main()
