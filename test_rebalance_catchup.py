#!/usr/bin/env python3
"""假日调仓兜底 (audit P1) 仿真测试:
  1. 周一 + 无戳         -> True   (正常锚日)
  2. 周一 + 今天已调     -> False  (当日去重)
  3. 周二 + 昨天调过     -> False  (正常周)
  4. 周二 + 上次 8 天前  -> True   (假日周一兜底: 9/7 Labor Day 场景)
  5. 周三 + 上次 8 天前  -> True   (周一二中止后的继续重试)
  6. 周六 + 上次 8 天前  -> False  (周末不开市, 不兜底)
  7. 周二 + 上次恰好6天前 -> False (阈值边界)
  8. 周三 + 从未调过(None) -> False (新部署保持旧行为: 等锚日)
  9. state 文件损坏       -> 不炸, 周一仍 True
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

M = tb.IntradayMonitor
ET = tb.ET
results = []


def check(name, cond):
    results.append((name, cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}")


def mk(state_file):
    cfg = tb.Config()
    cfg.STATE_FILE = Path(state_file)
    return SimpleNamespace(config=cfg)


def run_case(name, fake_now, stamp, expect):
    with tempfile.TemporaryDirectory() as tmp:
        sf = Path(tmp) / 'state.json'
        if stamp == 'CORRUPT':
            sf.write_text('{not json')
        elif stamp is not None:
            sf.write_text(json.dumps({'last_rebalance': stamp}))
        s = mk(sf)
        with patch.object(tb, 'now_et', lambda: fake_now):
            got = M.should_rebalance(s)
    check(name, got is expect)


# 2026-09-07 是周一 (Labor Day); 上周调仓 2026-08-31 周一
run_case('Mon anchor, no stamp -> True',
         datetime(2026, 9, 7, 10, 0, tzinfo=ET), None, True)
run_case('Mon, stamped today -> False',
         datetime(2026, 9, 7, 10, 0, tzinfo=ET), '2026-09-07T10:02:58-04:00', False)
run_case('Tue, last=Yesterday(Mon) -> False',
         datetime(2026, 9, 8, 10, 0, tzinfo=ET), '2026-09-07T10:02:58-04:00', False)
run_case('Tue, last=8d ago (holiday Mon) -> True',
         datetime(2026, 9, 8, 10, 0, tzinfo=ET), '2026-08-31T10:02:58-04:00', True)
run_case('Wed, last=9d ago -> True',
         datetime(2026, 9, 9, 10, 0, tzinfo=ET), '2026-08-31T10:02:58-04:00', True)
run_case('Sat, last=8d ago -> False',
         datetime(2026, 9, 12, 10, 0, tzinfo=ET), '2026-09-04T10:02:58-04:00', False)
run_case('Tue, last=exactly 6d -> False',
         datetime(2026, 9, 8, 10, 0, tzinfo=ET), '2026-09-02T10:02:58-04:00', False)
run_case('Wed, never rebalanced (None) -> False',
         datetime(2026, 9, 9, 10, 0, tzinfo=ET), None, False)
run_case('Mon, corrupt state -> True (no crash)',
         datetime(2026, 9, 7, 10, 0, tzinfo=ET), 'CORRUPT', True)

print()
n_fail = sum(1 for _, c in results if not c)
print(f"{len(results) - n_fail}/{len(results)} passed")
sys.exit(1 if n_fail else 0)
