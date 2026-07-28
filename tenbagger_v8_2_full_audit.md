# Tenbagger v8.1 → v8.2 深度代码审查报告
## 生产级量化交易系统全面审查 | 2026-07-27

---

## 审查方法

- **静态代码分析**: 逐行阅读1975行代码，检查逻辑正确性
- **运行时验证**: 通过Python执行确认关键bug
- **量化最佳实践对比**: 对照行业生产标准
- **模拟盘vs实盘差异分析**: 逐条对比Alpaca Paper vs Live

---

## PART A: 已验证的BUG (4个Critical)

### BUG-001 [CRITICAL] RiskController 除零错误 → 日亏损限制完全失效

**位置**: `RiskController.check_limits()` line ~760

**代码**:
```python
if self._last_date and now.date() != self._last_date:
    self._last_equity = 0  # ← BUG: 重置为0！
self._last_date = now.date()
...
daily_pnl = (equity - self._last_equity) / self._last_equity  # ← 除以零！
```

**影响**: Daily Loss Limit (`-3%`) 永远不会正确触发。第一天 `_last_equity=0` 导致 `daily_pnl = inf`，条件 `daily_pnl <= -0.03` 不会被满足（inf > -0.03）。

**修复**: 每天重置时应设为 `self._last_equity = equity`

---

### BUG-002 [CRITICAL] 移动止损100%逻辑永远不会执行

**位置**: `IntradayMonitor.check_stops()` line ~1610, `BacktestEngine` line ~1286

**代码**:
```python
elif peak_pct >= 0.50:      # peak=120% 走这里
    ...                      # 检查 trailing_50
elif peak_pct >= 1.0:       # ← 永远不会到这里！
    ...                      # trailing_100 完全失效
```

**验证**: peak_pct=120% 时，第一个 `elif peak_pct >= 0.50` 为True，进入该分支。
第二个 `elif` 被跳过。即使 trailing_50 未触发，程序也不会检查 trailing_100。

**影响**: 盈利100%+后的 `-25%` 移动止损**完全失效**。高盈利股票回撤保护缺失。

**修复**: 改为独立的 `if` 语句，按优先级从高到低排序

---

### BUG-003 [HIGH] TransactionCostModel net_price 漏算SEC/FINRA费用

**位置**: `TransactionCostModel.calculate()` line ~155

**代码**:
```python
net_price = price * (1 + slippage_bps / 10000)  # ← 只含滑点！
# SEC fee 和 FINRA TAF 被计算但从未应用到 net_price
```

**影响**: 每笔卖出交易少计约 0.2bp 成本。回测收益被轻微高估。

**修复**: `net_price = price + total_cost / qty`

---

### BUG-004 [HIGH] 止损基准(entry_price)与实际成本(net_price)不一致

**位置**: `BacktestEngine` line ~1389

**代码**:
```python
cash -= shares * net_price              # 实际按净价扣款
entry_prices[sym] = price               # ← 却用毛价记录！
# 后续止损: pnl = (current - entry) / entry  ← 基于毛价
```

**影响**: 真实成本 > 记录成本。亏损被低估，止损延迟触发（可能多亏损0.5-1%）。

**修复**: `entry_prices[sym] = net_price`

---

## PART B: 高优先级问题 (10个)

### HP-001 回测中 `getattr(self, '_last_t', 0)` 反模式
**位置**: `BacktestEngine.run()` line ~1314

使用 `getattr` 动态检查属性是Python反模式。应该用实例变量在 `__init__` 中初始化。

### HP-002 `emergency_liquidate` 不检查返回值
**位置**: `RiskController.emergency_liquidate()` line ~798

```python
def emergency_liquidate(self, client):
    for p in client.get_positions():
        client.submit_order(p['symbol'], qty, 'sell')  # ← 不检查成功/失败
```

紧急清仓时如果API调用失败，失败的股票不会被重试卖出。

### HP-003 `trade_logger` 没有设置 Formatter
**位置**: 日志初始化 section

`trade_logger` 用于写 JSON Lines 文件，但没有设置 formatter。默认的 `logging.Formatter` 会在每行前面加上时间戳和日志级别，破坏 JSON 格式。

### HP-004 `do_rebalance` 硬编码股票池
**位置**: `IntradayMonitor.do_rebalance()` line ~1647

```python
universe = ['AAPL','MSFT','NVDA',...]  # 27只硬编码
```

应该使用 Config 或动态获取的股票池。

### HP-005 WalkForwardValidator 不是真正的 Walk-Forward
**位置**: `WalkForwardValidator.run()` line ~1465

当前实现只是在不同时间段上运行回测，**没有使用训练期来优化参数**。真正的 WFA 需要：
1. 训练期：优化策略参数
2. 测试期：用优化后的参数运行
3. 重复

当前代码跳过了步骤1。

### HP-006 `MacroTiming.detect` 数据长度检查不足
**位置**: `MacroTiming.detect()` line ~865

```python
above_200d = spy.iloc[-1] > spy.rolling(200).mean().iloc[-1] if t >= 200 else True
# t >= 200 只保证有 201 个数据点 (0..200)
# rolling(200).mean() 在索引 200 处需要至少 200 个非NaN值
# 但 iloc[:t+1] 切出的是 0..t 共 t+1=201 个值
# 所以 rolling(200) 在索引 199 处已经有足够数据
# 这个检查其实是正确的，但边界条件很微妙
```

### HP-007 `PortfolioConstructor.allocate` 传入未使用的参数
**位置**: `PortfolioConstructor.allocate()` line ~1178

```python
def allocate(self, signals, capital, prices, t, fundamentals):
    # fundamentals 参数传入但从未使用
```

### HP-008 `SecureConfig` XOR 加密不够安全
**位置**: `SecureConfig._simple_encrypt()` line ~125

XOR加密在生产环境中不够安全。虽然标注了 "production: use Fernet"，但这就是生产代码。

### HP-009 `cancel_all_orders` 使用 DELETE /v2/orders
**位置**: `AlpacaClient.cancel_all_orders()` line ~277

Alpaca API 的 `DELETE /v2/orders` 会取消**所有**订单（包括可能不是本系统提交的）。应该只取消本系统的订单（通过 client_order_id 前缀过滤）。

### HP-010 `_calc_performance` benchmark 计算基准错误
**位置**: `BacktestEngine._calc_performance()` line ~1417

```python
bench_ret = (benchmark.iloc[-1] / benchmark.iloc[252]) - 1
# benchmark.iloc[252] 是回测开始后的第252天
# 但回测实际从 prices 的第252天开始
# 两者可能不一致！
```

---

## PART C: 中优先级问题 (6个)

### MP-001 缺少订单状态轮询
**位置**: `AlpacaClient.submit_order()`

提交订单后只返回 order dict，不检查是否被填充（filled）。在Paper Trading中market order通常立即填充，但在Live中可能部分填充。

### MP-002 回测中现金可能为负
**位置**: `BacktestEngine.run()` line ~1386

```python
if cost <= cash:  # ← 有检查
    cash -= cost
```
虽然检查了 `cost <= cash`，但浮点数精度可能导致 cash 变成极小的负数。

### MP-003 `check_stops` 和 `do_rebalance` 共享 positions 迭代
**位置**: `IntradayMonitor.run_cycle()`

```python
positions = self.sync_positions()     # 第一次获取
self.check_stops(positions)           # 可能修改（卖出）
self.do_rebalance()                   # 内部又调用 get_positions()
```

两次获取的 positions 可能不一致。

### MP-004 日志目录权限未检查
**位置**: 日志初始化

`LOG_DIR.mkdir(exist_ok=True)` 不检查是否可写。

### MP-005 回测中 `n_days - 1` 循环导致最后一天不处理
**位置**: `BacktestEngine.run()` line ~1250

```python
for t in range(252, n_days - 1):  # ← -1 跳过了最后一天
```

### MP-006 `get_bars` 使用 `iex` feed
**位置**: `AlpacaClient.get_bars()` line ~288

```python
'feed': 'iex'  # IEX数据可能延迟15分钟
```

在Paper Trading中没问题，但在Live Trading中应使用 `sip` feed（实时数据，可能需要订阅）。

---

## PART D: Alpaca Paper vs Live 差异分析

| # | 差异项 | Paper Trading | Live Trading | 影响级别 |
|---|--------|--------------|-------------|---------|
| 1 | 订单执行 | 模拟成交，无滑点 | 真实市场深度 | HIGH |
| 2 | 数据延迟 | 可能有轻微延迟 | SIP实时数据 | MEDIUM |
| 3 | 部分成交 | 全部成交 | 可能部分填充 | HIGH |
| 4 | 停机保护 | 无 | 需要自动恢复 | CRITICAL |
| 5 | 并发控制 | 单实例 | 多实例部署需锁 | MEDIUM |
| 6 | 风控执行 | 模拟 | 真实资金亏损 | CRITICAL |

---

## 修复总结

| 类别 | 数量 | 修复方式 |
|------|------|---------|
| Critical Bug | 4 | 代码修正 |
| High Priority | 10 | 代码修正 + 架构改进 |
| Medium Priority | 6 | 建议改进 |
| Paper vs Live | 6 | 文档说明 + 部分代码改进 |
| **总计** | **26** | v8.2 版本 |
