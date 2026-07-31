import sys, os, types, json
sys.path.insert(0, '/mnt/agents/output/tenbagger-strategy')
os.chdir('/mnt/agents/output/tenbagger-strategy')
import tenbagger_v8_2_production as tb

class MockClient:
    ORDER_PREFIX = 'tb_'
    def __init__(self, account=None, positions=None):
        self._account = account if account is not None else {'equity': '100000', 'cash': '50000', 'daytrade_count': 0}
        self._positions = positions
        self.liquidated = False
    def _request(self, *a, **k): raise AssertionError('raw request not mocked')
    def get_account(self): return self._account
    def get_positions(self): return self._positions
    def get_clock(self): return {'is_open': False}
    def get_open_our_orders(self): return []
    def cancel_our_orders(self): pass
    def submit_order(self, *a, **k): self.liquidated = True; return {'status': 'filled', 'id': 'x'}

def make_monitor(client):
    m = tb.IntradayMonitor.__new__(tb.IntradayMonitor)
    m.config = tb.Config()
    m.client = client
    m.risk = tb.RiskController(m.config)
    m.rebalancer = tb.FailSafeRebalancer(m.config)
    m.constructor = tb.PortfolioConstructor(m.config)
    m.macro = tb.MacroTiming(m.config)
    m.hedge = tb.HedgeEngine(m.config, client)
    m.entry_prices = {'AAPL': 100.0}
    m.max_prices = {'AAPL': 130.0}
    m.notifier = tb.Notifier(m.config)
    m._last_positions = [{'symbol': 'AAPL', 'qty': '10', 'current_price': '120', 'avg_entry_price': '100'}]
    m._consecutive_errors = 0
    return m

# T1 (P0): account read fails -> HOLD, no liquidation
m = make_monitor(MockClient(account={}, positions=[]))
m.run_cycle()
assert not m.client.liquidated, 'P0 FAIL: liquidation on failed account read'
assert m.risk._liquidated_for_circuit == False
print('T1 PASS: failed account read -> HOLD, no liquidation')

# T2 (P0): account returns zero equity -> HOLD
m = make_monitor(MockClient(account={'equity': '0'}, positions=[]))
m.run_cycle()
assert not m.client.liquidated
print('T2 PASS: zero equity -> HOLD')

# T3 (P1): positions read fails -> state preserved, last-known returned
m = make_monitor(MockClient(positions=None))
out = m.sync_positions()
assert out == m._last_positions and 'AAPL' in m.entry_prices and m.max_prices['AAPL'] == 130.0
print('T3 PASS: failed positions read -> state preserved')

# T4: healthy positions read updates state normally
m = make_monitor(MockClient(positions=[{'symbol': 'AAPL', 'qty': '10', 'current_price': '125', 'avg_entry_price': '100'}]))
out = m.sync_positions()
assert m.max_prices['AAPL'] == 130.0 and m._last_positions == out
print('T4 PASS: healthy read updates peak')

# T5: notifier disabled without env -> no crash
m.notifier.send('test', key='t', min_interval=0)
print('T5 PASS: notifier no-op without credentials')

# T6: emergency_liquidate with unreadable positions -> abort, no orders
c = MockClient(positions=None)
r = tb.RiskController(tb.Config()).emergency_liquidate(c)
assert r['failed'] == ['positions_read_failed'] and not c.liquidated
print('T6 PASS: liquidation aborted when positions unreadable')
print('ALL V9.0 TESTS PASS')
