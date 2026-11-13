"""MCX / NCDEX, GIFT Nifty, FII / DII  ->  data/market.json
Same sources and safety rules as the Apps Script MarketFeeds v2.1.
A value that fails a check keeps its previous good value (with its old time)."""
import re, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from common import get, rows, num, stamp, r2, load, save

OUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'market.json')
MCX = [['Gold', 'MCX GOLD'], ['Silver', 'MCX SILVER'], ['Crude oil', 'MCX CRUDE OIL'], ['Natural gas', 'MCX NATURAL GAS'],
       ['Copper', 'MCX COPPER'], ['Aluminium', 'MCX ALUMINIUM'], ['Lead', 'MCX LEAD'], ['Zinc', 'MCX ZINC']]
NCD = [['Jeera', 'NCDEX JEERA'], ['Coriander', 'NCDEX CORIANDER'], ['Turmeric', 'NCDEX TURMERIC'], ['Guar seed', 'NCDEX GUAR SEED'],
       ['Guar gum', 'NCDEX GUAR GUM'], ['Castor seed', 'NCDEX CASTOR SEED'], ['Cotton seed oilcake', 'NCDEX COTTON SEED OILCAKE']]


def pick(rs, key):
    k = key.upper()
    for r in rs:
        n = r[0].upper()
        if (n == k or n.startswith(k)) and not re.search(r'MINI|MICRO|PETAL|GUINEA|TEN|M\b', n[len(k):]):
            v = [x for x in (num(c) for c in r[1:]) if x is not None]
            if len(v) >= 5:
                return {'last': v[0], 'chg': v[1], 'pct': v[2], 'high': v[3], 'low': v[4]}
            return None
    return None


def commodities(rs, lst, exch, old, log):
    out = []
    for name, key in lst:
        prev = next((o for o in old if o.get('name') == name and o.get('exch') == exch), None)
        v = pick(rs, key) if rs else None
        why = ''
        if not v or not v['last']:
            why = 'not found'
        elif not v['low']:
            why = 'low 0'
        elif abs(v['pct'] or 0) > 10:
            why = '|%chg| > 10'
        elif prev and prev.get('price') and abs(v['last'] / prev['price'] - 1) > 0.15:
            why = 'moved > 15% from %s' % prev['price']
        if why:
            log.append('%s %s: skipped (%s)' % (exch, name, why))
            if prev:
                out.append(prev)
            continue
        out.append({'exch': exch, 'name': name, 'price': v['last'], 'prev': r2(v['last'] - (v['chg'] or 0)),
                    'pct': v['pct'], 'high': v['high'], 'low': v['low'], 'at': stamp(), 'src': 'liveindex.org'})
    return out


def main():
    old = load(OUT, {})
    log = []
    res = {'commodities': [], 'gift': old.get('gift'), 'fiidii': old.get('fiidii')}
    oc = old.get('commodities') or []
    mcx_rows = None
    try:
        mcx_rows = rows(get('https://liveindex.org/mcx-india/'))
    except Exception as e:
        log.append('MCX: %s' % e)
    res['commodities'] += commodities(mcx_rows, MCX, 'MCX', oc, log)
    ncd_rows = None
    try:
        ncd_rows = rows(get('https://liveindex.org/ncdex-india/'))
    except Exception as e:
        log.append('NCDEX: %s' % e)
    res['commodities'] += commodities(ncd_rows, NCD, 'NCDEX', oc, log)

    # GIFT Nifty: shown on liveindex.org as "SGX NIFTY FUTURE"
    g = None
    for r in (mcx_rows or []):
        if re.match(r'(?i)^(SGX|GIFT)\s*NIFTY', r[0]):
            v = [x for x in (num(c) for c in r[1:]) if x is not None]
            if len(v) >= 2 and v[0] > 1000:
                g = {'price': v[0], 'prev': r2(v[0] - v[1]), 'pct': r2(v[1] / (v[0] - v[1]) * 100), 'at': stamp(), 'src': 'liveindex.org'}
            break
    og = old.get('gift')
    if not g:
        log.append('GIFT Nifty: not found')
    elif og and og.get('price') and abs(g['price'] / og['price'] - 1) > 0.06:
        log.append('GIFT Nifty: %s is more than 6%% away from %s - kept old' % (g['price'], og['price']))
    else:
        res['gift'] = g

    # FII / DII net cash: groww.in daily table  Date, FII buy, sell, net, DII buy, sell, net
    try:
        f = None
        for r in rows(get('https://groww.in/fii-dii-data')):
            if re.match(r'^\d{1,2} [A-Za-z]{3} \d{4}$', r[0]) and len(r) >= 7:
                a, b = num(r[3]), num(r[6])
                if a is not None and b is not None:
                    f = {'date': r[0], 'fii': a, 'dii': b, 'at': stamp(), 'src': 'groww.in'}
                break
        if f:
            res['fiidii'] = f
        else:
            log.append('FII/DII: table not found')
    except Exception as e:
        log.append('FII/DII: %s' % e)

    res['updated'] = stamp()
    res['log'] = log
    save(OUT, res)
    print('\n'.join(log) or 'market: all ok')


if __name__ == '__main__':
    main()
