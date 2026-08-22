#!/usr/bin/env python3
"""Build point-in-time quarterly fundamentals from SEC XBRL companyfacts.

For every ticker: quarterly flow facts (revenue / net income / gross profit /
dividends) are converted to TTM series; each quarterly snapshot becomes
available on its earliest EDGAR 'filed' date. Share counts are split-adjusted
to latest-share units so they match split-adjusted price histories. SIC codes
(from the submissions API) are mapped to rough sector buckets.

Usage: python3 build_pit_fundamentals.py [ticker_file] [out_json]
Defaults: all tickers in Config.UNIVERSE -> data/pit_fundamentals_full.json
"""
import json, os, sys, time, datetime, bisect, urllib.request, urllib.error

SEC_H = {'User-Agent': 'tenbagger-research admin@example.com'}
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'pit')
os.makedirs(CACHE, exist_ok=True)

SPLIT_RATIOS = (20, 15, 10, 7, 5, 4, 3, 2.5, 2, 1.5, 0.5, 0.25, 0.2, 0.1, 0.05)
REV_FAMILY = ['RevenueFromContractWithCustomerExcludingAssessedTax',
              'RevenueFromContractWithCustomerIncludingAssessedTax',
              'Revenues', 'SalesRevenueNet', 'SalesRevenueGoodsNet',
              'RegulatedAndUnregulatedOperatingRevenue']
BANK_REV = ['RevenuesNetOfInterestExpense']
NI_KEYS = ['NetIncomeLoss', 'ProfitLoss']
GP_KEYS = ['GrossProfit']
COST_KEYS = ['CostOfRevenue', 'CostOfGoodsAndServicesSold', 'CostOfGoodsSold',
             'CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization']
INSURER_COST_KEYS = ['PolicyholderBenefitsAndClaimsIncurredHealthCare',
                     'PolicyholderBenefitsAndClaimsIncurredNet']
EQ_KEYS = ['StockholdersEquity',
           'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest']
DIV_KEYS = ['PaymentsOfDividends', 'PaymentsOfDividendsCommonStock', 'Dividends']


def sec_json(url, cache_path):
    if os.path.exists(cache_path):
        try:
            return json.load(open(cache_path))
        except Exception:
            pass
    req = urllib.request.Request(url, headers=SEC_H)
    for attempt in range(3):
        try:
            data = json.load(urllib.request.urlopen(req, timeout=30))
            json.dump(data, open(cache_path, 'w'))
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1 + attempt)
        except Exception:
            time.sleep(1 + attempt)
    return None


def sec_facts(cik):
    return sec_json(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json',
                    f'{CACHE}/facts_{cik}.json')


def _dur_days(i):
    try:
        return (datetime.date.fromisoformat(i['end']) - datetime.date.fromisoformat(i['start'])).days
    except Exception:
        return None


def _dedup_earliest_filed(items):
    best = {}
    for i in items:
        if 'start' not in i or 'end' not in i or 'filed' not in i:
            continue
        k = (i['start'], i['end'])
        if k not in best or i['filed'] < best[k]['filed']:
            best[k] = i
    return list(best.values())


def _quarterize(fact_items, min_q=60, max_q=120):
    """flow fact -> natural quarterly series {end: (val, filed)}.
    Handles standalone ~90d records, YTD cumulative differencing (prefix must
    span the same start), and Q4 = annual - 3 quarters."""
    items = _dedup_earliest_filed(fact_items)
    q, spans = {}, []
    for i in items:
        d = _dur_days(i)
        if d is None:
            continue
        if min_q <= d <= max_q:
            q[i['end']] = (i['val'], i['filed'], i['start'])
        elif max_q < d <= 380:
            spans.append((i['start'], i['end'], d, i['val'], i['filed']))
    for s, e, d, v, f in sorted(spans, key=lambda r: r[2]):
        if e in q:
            continue
        cands = []
        for pe, (pv, pf, ps) in q.items():
            if ps == s and pe < e:
                dd = (datetime.date.fromisoformat(e) - datetime.date.fromisoformat(pe)).days
                cands.append((pe, pv, dd))
        for s2, e2, d2, v2, f2 in spans:
            if s2 == s and e2 < e and (s2, e2) != (s, e):
                cands.append((e2, v2, d - d2))
        cands = [c for c in cands if min_q <= c[2] <= max_q]
        if cands:
            pe, pv, dd = max(cands, key=lambda c: c[0])
            q[e] = (v - pv, f, pe)
    for s, e, d, v, f in spans:
        if 330 <= d <= 380 and e not in q:
            parts = [(qe, qv) for qe, (qv, qf, qs) in q.items() if s < qe < e]
            if len(parts) == 3:
                q[e] = (v - sum(pv for _, pv in parts), f, s)
    return {e: (v, f) for e, (v, f, s) in q.items()}


def _ttm_from_q(q):
    ends = sorted(q.keys())
    out = {}
    for idx in range(3, len(ends)):
        span = (datetime.date.fromisoformat(ends[idx]) - datetime.date.fromisoformat(ends[idx - 3])).days
        if 240 <= span <= 320:
            vals = [q[ends[idx - j]] for j in range(4)]
            out[ends[idx]] = {'end': ends[idx], 'ttm': sum(v[0] for v in vals),
                              'filed': max(v[1] for v in vals)}
    return out


def _series_ttm(fact_items):
    return _ttm_from_q(_quarterize(fact_items))


def _merge_keys(gaap, keys):
    pool = []
    for k in keys:
        if k in gaap and 'USD' in gaap[k]['units']:
            pool.extend(gaap[k]['units']['USD'])
    return pool


def _q_coverage(items, since='2018'):
    return sum(1 for i in items if 60 <= (_dur_days(i) or 0) <= 380 and i['end'] >= since)


def _instants(items):
    best = {}
    for i in items:
        if 'end' not in i or 'filed' not in i:
            continue
        k = i['end']
        if k not in best or i['filed'] < best[k]['filed']:
            best[k] = i
    return {e: (i['val'], i['filed']) for e, i in best.items()}


def _adjust_share_splits(obs):
    """obs: [(end, shares)] sorted by end -> [(end, adj_shares)] in latest-share units."""
    if not obs:
        return obs
    factors = [1.0] * len(obs)
    run = 1.0
    for i in range(len(obs) - 1, 0, -1):
        factors[i] = run
        ratio = obs[i][1] / obs[i - 1][1] if obs[i - 1][1] else 1.0
        for R in SPLIT_RATIOS:
            if abs(ratio - R) / R < 0.06:
                run *= R
                break
    factors[0] = run
    return [(e, v * f) for (e, v), f in zip(obs, factors)]


def _share_series(facts):
    gaap, dei = facts['facts'].get('us-gaap', {}), facts['facts'].get('dei', {})
    obs = [(i['end'], i['val']) for i in
           dei.get('EntityCommonStockSharesOutstanding', {}).get('units', {}).get('shares', []) if 'end' in i]
    if len(obs) < 8:
        obs2 = [(i['end'], i['val']) for i in
                gaap.get('CommonStockSharesOutstanding', {}).get('units', {}).get('shares', []) if 'end' in i]
        if len(obs2) > len(obs):
            obs = obs2
    if len(obs) < 8:
        obs3 = [(i['end'], i['val']) for i in
                gaap.get('WeightedAverageNumberOfDilutedSharesOutstanding', {}).get('units', {}).get('shares', [])
                if 'end' in i and 60 <= (_dur_days(i) or 0) <= 120]
        if len(obs3) > len(obs):
            obs = obs3
    by_end = {}
    for e, v in obs:
        by_end[e] = max(by_end.get(e, 0), v)
    return dict(_adjust_share_splits(sorted(by_end.items())))


def _pick_cost_ttm(gaap, rev_ttm):
    gp_items = _merge_keys(gaap, GP_KEYS)
    if _q_coverage(gp_items) >= 8:
        return _series_ttm(gp_items)
    cost_items = _merge_keys(gaap, COST_KEYS)
    cost_ttm = _series_ttm(cost_items) if cost_items else {}
    ins_items = _merge_keys(gaap, INSURER_COST_KEYS)
    ins_ttm = _series_ttm(ins_items) if _q_coverage(ins_items) >= 8 else {}
    ends = set(cost_ttm) | set(ins_ttm)
    out = {}
    for e in ends:
        if e not in rev_ttm:
            continue
        c = cost_ttm.get(e, {}).get('ttm', 0.0) + ins_ttm.get(e, {}).get('ttm', 0.0)
        filed = max([rev_ttm[e]['filed']] + [d['filed'] for d in (cost_ttm.get(e), ins_ttm.get(e)) if d])
        out[e] = {'end': e, 'ttm': rev_ttm[e]['ttm'] - c, 'filed': filed}
    return out


def sic_to_sector(sic):
    if sic is None:
        return 'Unknown'
    try:
        sic = int(sic)
    except Exception:
        return 'Unknown'
    if sic in (6321, 6324):
        return 'Healthcare'  # GICS managed care
    if sic in (1311, 1381, 1382, 1389, 2911, 4612, 4613, 4619, 4922, 4923, 4924) or 1300 <= sic <= 1399:
        return 'Energy'
    if 4900 <= sic <= 4999:
        return 'Utilities'
    if 8000 <= sic <= 8099 or sic in (2834, 2835, 2836, 3841, 3842, 3843, 3844, 3845, 3851, 8071, 8082):
        return 'Healthcare'
    if sic == 6798 or 6500 <= sic <= 6599:
        return 'Real Estate'
    if 6000 <= sic <= 6499 or 6700 <= sic <= 6799:
        return 'Financial Services'
    if 7370 <= sic <= 7379 or sic in (3570, 3571, 3572, 3576, 3577, 3661, 3663, 3669,
                                      3671, 3672, 3674, 3678, 3679, 3812, 5045, 5065, 5734):
        return 'Technology'
    if 4800 <= sic <= 4899 or sic in (7812, 7819, 7822, 7830, 7841, 7997, 7948):
        return 'Communication Services'
    if 2000 <= sic <= 2141 or sic in (2840, 2842, 2844, 5411, 5912) or 5200 <= sic <= 5299:
        return 'Consumer Defensive'
    if 5500 <= sic <= 5999 or 2300 <= sic <= 2399 or 2500 <= sic <= 2599 or 3000 <= sic <= 3199 \
            or 3900 <= sic <= 3999 or 7000 <= sic <= 7299 or 7500 <= sic <= 7699 or 7800 <= sic <= 7899:
        return 'Consumer Cyclical'
    if 1000 <= sic <= 1499 or 2600 <= sic <= 2899 or 3200 <= sic <= 3399:
        return 'Materials'
    if 1500 <= sic <= 1799 or 3400 <= sic <= 3599 or 3680 <= sic <= 3999 or 4000 <= sic <= 4799 \
            or 7300 <= sic <= 7369 or 7380 <= sic <= 7499 or 8700 <= sic <= 8999:
        return 'Industrials'
    return 'Unknown'


def build_pit(symbol, cik_of):
    facts = sec_facts(cik_of[symbol])
    if not facts:
        return []
    gaap = facts['facts'].get('us-gaap', {})
    rev_a = _merge_keys(gaap, REV_FAMILY)
    rev_b = _merge_keys(gaap, BANK_REV)
    rev_items = rev_b if _q_coverage(rev_b) > _q_coverage(rev_a) else rev_a
    rev_ttm = _series_ttm(rev_items)
    ni_ttm = _series_ttm(_merge_keys(gaap, NI_KEYS))
    div_items = _merge_keys(gaap, DIV_KEYS)
    div_ttm = _series_ttm(div_items) if div_items else {}
    gp_ttm = _pick_cost_ttm(gaap, rev_ttm)
    eq_items = _merge_keys(gaap, EQ_KEYS)
    equity = _instants(eq_items) if eq_items else {}
    sh_adj = _share_series(facts)
    snaps = []
    ends = sorted(rev_ttm.keys())
    for idx, e in enumerate(ends):
        r = rev_ttm[e]
        ni = ni_ttm.get(e)
        eq = equity.get(e)
        sh_cands = [se for se in sh_adj if se <= e]
        sh = sh_adj[max(sh_cands)] if sh_cands else None
        ya = None
        if idx >= 4:
            e4 = ends[idx - 4]
            span = (datetime.date.fromisoformat(e) - datetime.date.fromisoformat(e4)).days
            if 330 <= span <= 380:
                ya = {'rev': rev_ttm[e4]['ttm'],
                      'ni': ni_ttm[e4]['ttm'] if e4 in ni_ttm else None}
        filed_parts = [r['filed']]
        if ni:
            filed_parts.append(ni['filed'])
        if eq:
            filed_parts.append(eq[1])
        snaps.append({'period_end': e, 'avail': max(filed_parts),
                      'rev_ttm': r['ttm'], 'ni_ttm': ni['ttm'] if ni else None,
                      'gp_ttm': gp_ttm[e]['ttm'] if e in gp_ttm else None,
                      'div_ttm': div_ttm[e]['ttm'] if e in div_ttm else 0.0,
                      'equity': eq[0] if eq else None, 'shares': sh,
                      'rev_ya': ya['rev'] if ya else None,
                      'ni_ya': ya['ni'] if ya else None})
    return snaps


def main():
    tick_path = f'{CACHE}/company_tickers.json'
    tickers_json = sec_json('https://www.sec.gov/files/company_tickers.json', tick_path)
    cik_of = {v['ticker'].upper(): v['cik_str'] for v in tickers_json.values()}

    # 2026-08-22 fixes (weekly cron rebuild on 08-08 and 08-22 silently
    # dropped symbols - the 08-08 regression broke baseline reproducibility
    # until patched by hand):
    #  1) dot-tickers: our universe uses BRK.B/BF.B but SEC's ticker file
    #     uses dashes (BRK-B/BF-B) -> look up the dashed form.
    #  2) CIK overrides: SEC maps some listed tickers to holding entities
    #     whose companyfacts carry no us-gaap financials, while the actual
    #     filer is the legacy operating entity:
    #       XOM -> 2115436 'ExxonMobil Holdings Corp' (ffd-only facts);
    #              real filer Exxon Mobil Corp 34088 (current thru 2026-03).
    CIK_OVERRIDE = {'XOM': 34088}

    def resolve_cik(sym):
        if sym in CIK_OVERRIDE:
            return CIK_OVERRIDE[sym]
        if sym in cik_of:
            return cik_of[sym]
        dashed = sym.replace('.', '-')
        return cik_of.get(dashed)

    if len(sys.argv) > 1:
        tickers = [l.strip() for l in open(sys.argv[1]) if l.strip()]
    else:
        import re
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'tenbagger_v8_2_production.py')).read()
        m = re.search(r'UNIVERSE: List\[str\] = field\(default_factory=lambda: \[(.*?)\]\)', src, re.S)
        tickers = re.findall(r"'([A-Z.]+)'", m.group(1))
    out_json = sys.argv[2] if len(sys.argv) > 2 else 'data/pit_fundamentals_full.json'

    pit, sectors, fails = {}, {}, []
    t0 = time.time()
    for i, sym in enumerate(tickers):
        try:
            cik = resolve_cik(sym)
            if cik is None:
                fails.append((sym, 'no_cik'))
                continue
            snaps = build_pit(sym, {sym: cik})
            if snaps:
                pit[sym] = snaps
            else:
                fails.append((sym, 'no_snaps'))
            sub = sec_json(f'https://data.sec.gov/submissions/CIK{cik:010d}.json',
                           f'{CACHE}/sub_{cik}.json')
            sectors[sym] = sic_to_sector((sub or {}).get('sic'))
            time.sleep(0.12)
        except Exception as ex:
            fails.append((sym, str(ex)[:80]))
        if (i + 1) % 50 == 0:
            print(f"[{i+1}/{len(tickers)}] {(time.time()-t0)/60:.1f}min ok={len(pit)} fail={len(fails)}",
                  flush=True)
    out = {'_meta': {'source': 'SEC XBRL companyfacts', 'built': datetime.date.today().isoformat(),
                     'avail': 'earliest EDGAR filed date per period (point-in-time)',
                     'shares': 'split-adjusted to latest-share units'},
           'sectors': sectors,
           'symbols': pit}
    with open(out_json, 'w') as f:
        json.dump(out, f)
    print(f"DONE {(time.time()-t0)/60:.1f}min ok={len(pit)} fail={len(fails)} -> {out_json}")
    print("fails:", fails)
    # 2026-08-22: regression guard - these symbols were silently dropped by
    # the 08-08/08-22 rebuilds (dot-ticker no_cik / holdco CIK). If they go
    # missing again, FAIL LOUDLY so the weekly cron log shows it.
    REQUIRED = ['BRK.B', 'BF.B', 'XOM']
    missing = [s for s in REQUIRED if s not in pit]
    if missing:
        print(f"*** REGRESSION GUARD: required symbols missing: {missing} ***")
        sys.exit(2)


if __name__ == '__main__':
    main()
