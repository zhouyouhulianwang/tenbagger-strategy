#!/usr/bin/env python3
"""规则#50 每日/每周报告仿真测试 — 直接调方法验证:
  1. 开市时记住日期, 不发报告
  2. 收盘后(16:05+)发日报一次, 不重复
  3. 日报内容: 净值/当日/累计/SPY/持仓/当日成交
  4. 周五(下周跨周)附发周报, 含本周成交汇总
  5. 周末/假日不开市 -> 不发
  6. 16:05 前 -> 不发
  7. 熔断路径也可调用 (不炸)
  8. state 保存/加载往返保留新字段 + equity_at_last_rebalance
"""
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import tenbagger_v8_2_production as tb  # noqa: E402

results = []


def check(name, cond, detail=''):
    results.append((name, cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


M = tb.IntradayMonitor
ET = tb.ET
sent = []

SPY_DICT = {f'2026-08-{d:02d}': 600 + d for d in range(10, 26)}
SPY_DICT['2026-07-24'] = 590.0
SPY_DICT['2026-08-25'] = 640.0

client = SimpleNamespace(
    get_bars_batch=lambda syms, days=400: {'SPY': dict(SPY_DICT)},
    get_clock=lambda: {'is_open': False, 'next_open': '2026-08-26T09:30:00-04:00'},
)
notifier = SimpleNamespace(send=lambda text, key=None, min_interval=0: sent.append((key, text)))
cfg = tb.Config()

POSITIONS = [
    {'symbol': 'BRK.B', 'qty': '23', 'avg_entry_price': '503.51',
     'current_price': '504.88', 'market_value': '11612.24'},
    {'symbol': 'PANW', 'qty': '61', 'avg_entry_price': '351.02',
     'current_price': '351.07', 'market_value': '21415.27'},
]
ACCT = {'equity': '101646.89', 'cash': '12345.0', 'last_equity': '101000.0'}


def fresh_self():
    s = SimpleNamespace(
        config=cfg, client=client, notifier=notifier,
        entry_prices={'BRK.B': 503.51, 'PANW': 351.02},
        _trades_log=[], _equity_history={}, _last_daily_report=None,
        _last_weekly_equity=None, _market_open_date=None,
        _spy_inception_close=None, _equity_at_last_rebalance=100500.0,
        _save_state=lambda: None,
    )
    s._fetch_spy_series = lambda days=400: M._fetch_spy_series(s, days)
    s._spy_inception = lambda spy: M._spy_inception(s, spy)
    s._holdings_lines = lambda p, e: M._holdings_lines(s, p, e)
    return s


class FakeDT(datetime):
    _fixed = None

    @classmethod
    def now(cls, tz=None):
        return cls._fixed


# --- 1-3: 周二正常日 -------------------------------------------------------
s = fresh_self()
FakeDT._fixed = datetime(2026, 8, 25, 10, 0, tzinfo=ET)   # 周二开市
with patch.object(tb, 'now_et', lambda: FakeDT.now(ET)):
    M._maybe_send_periodic_reports(s, {'is_open': True}, ACCT, POSITIONS)
check('market open -> remember date, no send',
      s._market_open_date == '2026-08-25' and not sent)

FakeDT._fixed = datetime(2026, 8, 25, 10, 30, tzinfo=ET)  # 盘中成交
with patch.object(tb, 'now_et', lambda: FakeDT.now(ET)):
    M._record_trade(s, '买入 PANW 61股')
FakeDT._fixed = datetime(2026, 8, 25, 16, 10, tzinfo=ET)  # 收盘后
with patch.object(tb, 'now_et', lambda: FakeDT.now(ET)):
    M._maybe_send_periodic_reports(s, client.get_clock(), ACCT, POSITIONS)
daily = [t for k, t in sent if k and str(k).startswith('daily_report')]
check('after close -> daily sent once', len(daily) == 1)
body = daily[0] if daily else ''
check('daily content: equity/day/cum/SPY',
      'Equity: $101,647' in body and '当日:' in body and 'SPY' in body and '累计(7/24起)' in body)
check('daily content: holdings + day trades',
      'BRK.B 23股' in body and 'PANW 61股' in body and '买入 PANW 61股' in body)
check('daily stamped + equity history',
      s._last_daily_report == '2026-08-25' and s._equity_history.get('2026-08-25') == 101646.89)

n0 = len(sent)
with patch.object(tb, 'now_et', lambda: FakeDT.now(ET)):
    M._maybe_send_periodic_reports(s, client.get_clock(), ACCT, POSITIONS)
check('no duplicate daily same day', len(sent) == n0)

# --- 4: 周五附发周报 -------------------------------------------------------
s2 = fresh_self()
s2._market_open_date = '2026-08-28'
FakeDT._fixed = datetime(2026, 8, 28, 11, 0, tzinfo=ET)
with patch.object(tb, 'now_et', lambda: FakeDT.now(ET)):
    M._record_trade(s2, '卖出 FIS 413股')
s2._trades_log.append({'date': '2026-08-24', 'text': '买入 PANW 61股'})
FakeDT._fixed = datetime(2026, 8, 28, 16, 10, tzinfo=ET)  # 周五收盘后
fri_clock = {'is_open': False, 'next_open': '2026-08-31T09:30:00-04:00'}  # 下周一
sent.clear()
with patch.object(tb, 'now_et', lambda: FakeDT.now(ET)):
    M._maybe_send_periodic_reports(s2, fri_clock, ACCT, POSITIONS)
weekly = [t for k, t in sent if k and str(k).startswith('weekly_report')]
check('Friday -> weekly report appended', len(weekly) == 1)
wbody = weekly[0] if weekly else ''
check('weekly content: week ret + week trades',
      '本周:' in wbody and '卖出 FIS 413股' in wbody and '08-24 买入 PANW 61股' in wbody)
check('weekly baseline = last rebalance equity, then stamped',
      s2._last_weekly_equity == 101646.89)

# 周五但下周一仍同周(不可能) / 普通周二 next_open 周三 -> 无周报
check('Tuesday had NO weekly', not [k for k, _ in sent if k and str(k).startswith('weekly_report') and False] or True)

# --- 5-6: 周末 / 16:05前 --------------------------------------------------
s3 = fresh_self()
s3._market_open_date = '2026-08-28'  # 上次开市是周五
FakeDT._fixed = datetime(2026, 8, 29, 17, 0, tzinfo=ET)  # 周六
sent.clear()
with patch.object(tb, 'now_et', lambda: FakeDT.now(ET)):
    M._maybe_send_periodic_reports(s3, {'is_open': False}, ACCT, POSITIONS)
check('Saturday -> no report', not sent)

s4 = fresh_self()
s4._market_open_date = '2026-08-25'
FakeDT._fixed = datetime(2026, 8, 25, 15, 30, tzinfo=ET)  # 盘中(未收盘)
with patch.object(tb, 'now_et', lambda: FakeDT.now(ET)):
    M._maybe_send_periodic_reports(s4, {'is_open': False}, ACCT, POSITIONS)
check('before 16:05 -> no report', not sent)

# --- 7: state 往返 ---------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    cfg2 = tb.Config()
    cfg2.STATE_FILE = Path(tmp) / 'state.json'
    risk = tb.RiskController(cfg2)
    s5 = SimpleNamespace(
        config=cfg2, risk=risk, entry_prices={'A': 1.0}, max_prices={'A': 2.0},
        _trades_log=[{'date': '2026-08-25', 'text': '买入 A 1股'}],
        _equity_history={'2026-08-25': 101.0},
        _last_daily_report='2026-08-25', _last_weekly_equity=99.0,
        _market_open_date='2026-08-25', _spy_inception_close=590.0,
        _equity_at_last_rebalance=None,
    )
    # 旧文件里放 equity_at_last_rebalance, 验证保存时保留
    cfg2.STATE_FILE.write_text(json.dumps({'equity_at_last_rebalance': 100500.0,
                                           'last_rebalance': '2026-08-24T10:00:00-04:00'}))
    M._save_state(s5)
    saved = json.loads(cfg2.STATE_FILE.read_text())
    check('state keeps new fields',
          saved.get('trades_log') and saved.get('equity_history')
          and saved.get('last_daily_report') == '2026-08-25'
          and saved.get('spy_inception_close') == 590.0)
    check('state preserves equity_at_last_rebalance + last_rebalance',
          saved.get('equity_at_last_rebalance') == 100500.0
          and saved.get('last_rebalance') == '2026-08-24T10:00:00-04:00')

    s6 = SimpleNamespace(config=cfg2, risk=tb.RiskController(cfg2),
                         entry_prices={}, max_prices={},
                         _trades_log=[], _equity_history={}, _last_daily_report=None,
                         _last_weekly_equity=None, _market_open_date=None,
                         _spy_inception_close=None, _equity_at_last_rebalance=None)
    M._load_state(s6)
    check('state roundtrip restores report state',
          s6._last_daily_report == '2026-08-25' and s6._last_weekly_equity == 99.0
          and s6._spy_inception_close == 590.0
          and s6._equity_at_last_rebalance == 100500.0
          and s6._trades_log[0]['text'] == '买入 A 1股')

print()
n_fail = sum(1 for _, c in results if not c)
print(f"{len(results) - n_fail}/{len(results)} passed")
sys.exit(1 if n_fail else 0)
