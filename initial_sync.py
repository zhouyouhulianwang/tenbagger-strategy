#!/usr/bin/env python3
"""One-time initial portfolio sync (approved 2026-07-30):
wait for the 10:00 ET trading window -> sell legacy positions -> verify cash
-> buy v8.6 targets -> post-rebalance report. Uses the v8.5 AlpacaClient
(retry, fill polling, no 4xx retry). Keys come from env vars only.

Usage:
  ALPACA_API_KEY=... ALPACA_SECRET_KEY=... python3 initial_sync.py [--now]
"""
import os, sys, json, time
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tenbagger_v8_2_production import Config, AlpacaClient

ET = ZoneInfo('America/New_York')
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'initial_sync.log')

# v8.6 targets from the approved pre-rebalance report (weights sum to 0.60)
TARGET_W = {'PEG': 0.162, 'EIX': 0.124, 'PG': 0.114, 'EG': 0.079, 'T': 0.069, 'MKC': 0.052}
WINDOW_START = '10:00'
WINDOW_END = '15:30'


def log(msg):
    line = f"{datetime.now(ET).strftime('%H:%M:%S')} ET | {msg}"
    print(line, flush=True)
    with open(LOG, 'a') as f:
        f.write(line + '\n')


def latest_price(client, sym):
    r = client._request('GET', f"{client.config.ALPACA_DATA_URL}/v2/stocks/{sym}/trades/latest",
                        params={'feed': client.config.DATA_FEED})
    if r.status_code == 200:
        return float(r.json()['trade']['p'])
    return 0.0


def wait_for_window(client):
    log(f"waiting for trading window {WINDOW_START}-{WINDOW_END} ET ...")
    while True:
        now = datetime.now(ET)
        hm = now.strftime('%H:%M')
        clock = client.get_clock()
        if clock.get('is_open') and WINDOW_START <= hm <= WINDOW_END:
            log(f"window open ({hm}, market is_open=True) - starting sync")
            return
        if hm > WINDOW_END:
            log(f"window missed ({hm}) - aborting for today")
            sys.exit(2)
        time.sleep(30)


def main():
    cfg = Config()
    client = AlpacaClient(cfg)

    if '--now' not in sys.argv:
        wait_for_window(client)
    else:
        log('--now flag: skipping window wait')

    # 0. cancel orphan orders (v8.5 P1-3)
    client.cancel_our_orders()

    # 1. account snapshot
    acct = client.get_account()
    equity = float(acct['equity'])
    log(f"equity=${equity:,.2f} cash=${float(acct['cash']):,.2f} "
        f"daytrade_count={acct.get('daytrade_count')}")

    # 2. sell all legacy stock positions (no overlap with targets)
    positions = client.get_positions()
    failures = []
    for p in positions:
        sym = p['symbol']
        if sym == cfg.HEDGE_ETF:
            continue
        qty = int(float(p['qty']))
        if qty <= 0:
            continue
        order = client.submit_order(sym, qty, 'sell')
        if order and order.get('status') in ('filled', 'accepted', 'new', 'partially_filled'):
            log(f"SELL {sym} x{qty} -> {order.get('status')} @ {order.get('filled_avg_price')}")
        else:
            failures.append(f'sell:{sym}')
            log(f"SELL {sym} x{qty} FAILED")
        time.sleep(0.3)

    # 3. verify cash freed (poll account up to 60s)
    cash = 0.0
    for _ in range(12):
        acct = client.get_account()
        cash = float(acct['cash'])
        if cash > 1000:
            break
        time.sleep(5)
    log(f"cash after sells: ${cash:,.2f}")
    if cash < 1000 and positions:
        failures.append('no_cash_after_sells')
        log("CRITICAL: cash not freed - aborting buys")
        report(failures, [])
        sys.exit(1)

    # 4. buys sized on CURRENT equity at latest prices
    equity = float(client.get_account()['equity'])
    budget = min(cash, equity * sum(TARGET_W.values()))
    log(f"buy budget: ${budget:,.2f} (cash-capped)")
    fills = []
    for sym, w in TARGET_W.items():
        target_val = equity * w
        if target_val > budget:
            target_val = budget * (w / sum(TARGET_W.values()))
        px = latest_price(client, sym)
        if px <= 0:
            failures.append(f'price:{sym}')
            log(f"BUY {sym}: no price - skipped")
            continue
        qty = int(target_val / px)
        if qty < 1:
            log(f"BUY {sym}: qty=0 (${target_val:,.0f} @ ${px:.2f}) - skipped")
            continue
        order = client.submit_order(sym, qty, 'buy')
        if order and order.get('status') in ('filled', 'accepted', 'new', 'partially_filled'):
            log(f"BUY {sym} x{qty} -> {order.get('status')} @ {order.get('filled_avg_price')}")
            fills.append({'symbol': sym, 'qty': qty, 'status': order.get('status'),
                          'price': order.get('filled_avg_price')})
        else:
            failures.append(f'buy:{sym}')
            log(f"BUY {sym} x{qty} FAILED")
        time.sleep(0.3)

    report(failures, fills)


def report(failures, fills):
    time.sleep(2)
    client = AlpacaClient(Config())
    acct = client.get_account()
    positions = client.get_positions()
    log('=' * 60)
    log('调仓后报告 (POST-SYNC REPORT)')
    log(f"equity=${float(acct['equity']):,.2f} cash=${float(acct['cash']):,.2f}")
    for p in positions:
        log(f"  {p['symbol']:<6} qty={p['qty']:<7} mv=${float(p['market_value']):>10,.2f} "
            f"entry=${float(p['avg_entry_price']):>8.2f}")
    log(f"failures: {failures if failures else 'none'}")
    log('=' * 60)
    sys.exit(0 if not failures else 1)


if __name__ == '__main__':
    main()
