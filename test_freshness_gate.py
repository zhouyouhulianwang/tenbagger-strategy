#!/usr/bin/env python3
"""规则#47 数据新鲜度闸门仿真测试 — 不改生产代码，直接调方法验证四条路径:
  1. 价格新鲜（今天 bar）           -> 闸门通过
  2. 价格新鲜（上一工作日 bar）      -> 闸门通过
  3. 价格过期（4 天前）              -> 闸门拒绝（重拉循环会中止）
  4. PIT 超龄 + 重建成功            -> 重载通过
  5. PIT 超龄 + 重建失败            -> 中止 + failures=['stale_pit'] + 告警
"""
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from tenbagger_v8_2_production import (  # noqa: E402
    Config, IntradayMonitor, PointInTimeFundamentals, ET,
)

results = []


def check(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


monitor_cls = IntradayMonitor
fake_self = SimpleNamespace()

# --- 价格新鲜度 -----------------------------------------------------------
today = datetime.now(ET).date()
d = today
while d.weekday() >= 5:  # 找上一工作日
    d -= timedelta(days=1)
last_weekday = d

idx_fresh_today = pd.date_range(end=pd.Timestamp(today), periods=300, freq='B')
idx_fresh_lastwd = pd.date_range(end=pd.Timestamp(last_weekday), periods=300, freq='B')
idx_stale = pd.date_range(end=pd.Timestamp(today - timedelta(days=4)), periods=300, freq='B')

check('price fresh (today bar)',
      monitor_cls._price_data_fresh(fake_self, pd.DataFrame({'A': range(300)}, index=idx_fresh_today)))
check('price fresh (last weekday bar)',
      monitor_cls._price_data_fresh(fake_self, pd.DataFrame({'A': range(300)}, index=idx_fresh_lastwd)))
check('price stale (4d old) rejected',
      not monitor_cls._price_data_fresh(fake_self, pd.DataFrame({'A': range(300)}, index=idx_stale)))
check('empty df rejected',
      not monitor_cls._price_data_fresh(fake_self, pd.DataFrame()))

# --- PIT 新鲜度 -----------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    pit = tmp / 'pit_fundamentals_full.json'
    pit.write_text(json.dumps({'symbols': {'AAA': [{'avail': '2026-08-01', 'shares': 1}]},
                               'sectors': {'AAA': 'Tech'}}))
    old = time.time() - 30 * 86400  # 30 天前
    import os
    os.utime(pit, (old, old))

    cfg = Config()
    cfg.DATA_DIR = tmp
    cfg.PIT_MAX_AGE_DAYS = 10

    sent = []
    notifier = SimpleNamespace(send=lambda msg, key=None, min_interval=0: sent.append((key, msg)))
    pit_inst = object.__new__(PointInTimeFundamentals)  # bypass __init__, 仅过 isinstance
    self2 = SimpleNamespace(fundamentals=pit_inst, config=cfg, notifier=notifier)

    # 路径 4: 超龄 + 重建成功（mock subprocess.run 摸新 mtime）
    def fake_run_ok(*a, **kw):
        now = time.time()
        os.utime(pit, (now, now))
        return None
    failures = []
    with patch('subprocess.run', side_effect=fake_run_ok):
        ok = monitor_cls._ensure_pit_fresh(self2, failures)
    check('PIT stale + rebuild ok -> pass, reloaded', ok and not failures,
          f'fundamentals type={type(self2.fundamentals).__name__}')
    check('PIT reloaded real instance', isinstance(self2.fundamentals, PointInTimeFundamentals)
          and 'AAA' in self2.fundamentals.snaps)

    # 路径 5: 超龄 + 重建失败 -> 中止 + 告警
    self2.fundamentals = object.__new__(PointInTimeFundamentals)
    os.utime(pit, (old, old))
    failures = []
    sent.clear()
    with patch('subprocess.run', side_effect=subprocess.CalledProcessError(2, 'build')):
        ok = monitor_cls._ensure_pit_fresh(self2, failures)
    check('PIT stale + rebuild fail -> abort', not ok and failures == ['stale_pit'])
    check('abort alerted via telegram', any(k == 'stale_pit_abort' for k, _ in sent))

    # 路径 6: 新鲜 PIT 直接通过（不触发重建）
    now = time.time()
    os.utime(pit, (now, now))
    failures = []
    with patch('subprocess.run', side_effect=AssertionError('should not be called')):
        ok = monitor_cls._ensure_pit_fresh(self2, failures)
    check('PIT fresh -> pass, no rebuild', ok and not failures)

    # 路径 7: yfinance 回退实例不适用龄期检查
    self2.fundamentals = SimpleNamespace()  # 非 PointInTimeFundamentals
    failures = []
    ok = monitor_cls._ensure_pit_fresh(self2, failures)
    check('non-PIT fundamentals -> pass through', ok and not failures)

print()
n_fail = sum(1 for _, c, _ in results if not c)
print(f"{len(results) - n_fail}/{len(results)} passed")
sys.exit(1 if n_fail else 0)
