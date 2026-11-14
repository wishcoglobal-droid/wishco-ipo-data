"""IPO list from the IPO Premium home page  ->  data/ipos.json
Table columns: Company Name, Type, GMP, Open, Close, Price Band, Listing Date.
If the page does not answer or the table is not found, the previous file is kept as it is."""
import re, sys, os, html, datetime
sys.path.insert(0, os.path.dirname(__file__))
from common import get, rows, num, stamp, load, save, now_ist

OUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'ipos.json')
URL = 'https://www.ipopremium.in/'


def day(s):
    try:
        return datetime.datetime.strptime(s.strip(), '%b %d, %Y').strftime('%Y-%m-%d')
    except Exception:
        return ''


def detail(page):
    """Lot size, category minimums, issue size and allotment / listing days from an IPO page."""
    rs = rows(page)
    if not rs:
        return None
    top = html.unescape(' '.join(rs[0]))
    d = {}
    m = re.search(r'Lot Size\s+([\d,]+)\s+shares', top)
    if m:
        d['lot'] = int(m.group(1).replace(',', ''))
    m = re.search(r'₹\s*([\d,.]+)\s*cr issue', top)
    if m:
        d['issue_cr'] = num(m.group(1))
    yr = now_ist().year
    for k, lab in (('allot', 'Allotment'), ('listing', 'Listing')):
        m = re.search(lab + r'\s+([A-Z][a-z]{2})\s+(\d{1,2})\b', top)
        if m:
            try:
                d[k] = datetime.datetime.strptime('%s %s %d' % (m.group(1), m.group(2), yr), '%b %d %Y').strftime('%Y-%m-%d')
            except Exception:
                pass
    mins = {}
    for r in rs:
        k = {'retail': 'r', 'individual': 'r', 'shni': 's', 'bhni': 'b'}.get(r[0].strip().lower())
        if k and len(r) >= 4:
            lots, sh, amt = num(r[1]), num(r[2]), num(html.unescape(r[3]))
            if lots and sh and amt:
                mins[k] = {'lots': int(lots), 'shares': int(sh), 'amount': amt, 'label': r[0].strip()}
    if mins:
        d['mins'] = mins
    return d or None


def main():
    old = load(OUT, {})
    try:
        page = get(URL)
    except Exception as e:
        old['log'] = ['IPO Premium: %s (old list kept)' % e]
        old['checked'] = stamp()
        save(OUT, old)
        print(old['log'][0])
        return
    links = {}
    for m in re.finditer(r'href="(https://www\.ipopremium\.in/view/ipo/(\d+)/[^"#?]*)"[^>]*>\s*(?:<[^>]+>\s*)*([^<]+)', page):
        links.setdefault(re.sub(r'\W+', '', html.unescape(m.group(3)).lower()), (m.group(2), m.group(1)))
    rs = rows(page)
    start = next((i for i, r in enumerate(rs) if r[:2] == ['Company Name', 'Type']), -1)
    out = []
    today = now_ist().strftime('%Y-%m-%d')
    if start >= 0:
        for r in rs[start + 1:]:
            if len(r) < 7 or r[1] not in ('SME', 'EQ'):
                continue
            full = html.unescape(r[0])
            m = re.match(r'^(.*?)\s*\(([^)]*)\)\s*$', full)
            name, where = (m.group(1).strip(), m.group(2).strip().upper()) if m else (full, '')
            band = [num(x) for x in re.split(r'[–-]', html.unescape(r[5]))]
            band = [x for x in band if x is not None]
            o, c, l = day(r[3]), day(r[4]), day(r[6])
            if not o or not c:
                continue
            st = 'upcoming' if today < o else 'open' if today <= c else 'closed' if (not l or today < l) else 'listed'
            lk = links.get(re.sub(r'\W+', '', full.lower())) or links.get(re.sub(r'\W+', '', name.lower())) or ('', '')
            out.append({'name': name, 'board': 'SME' if r[1] == 'SME' else 'Mainboard', 'exch': where,
                        'gmp': num(r[2]), 'open': o, 'close': c, 'listing': l,
                        'low': band[0] if band else None, 'high': band[-1] if band else None,
                        'status': st, 'id': lk[0], 'url': lk[1]})
    # full details (lot size, minimum amounts, issue size, allotment day) from each upcoming / open IPO's own page.
    # A page is read again only after 55 minutes; if it does not answer, the earlier details are kept.
    prev = {x.get('id'): x for x in (old.get('ipos') or []) if x.get('id')}
    nowt = int(now_ist().timestamp())
    for x in out:
        if x['status'] not in ('upcoming', 'open') or not x['url']:
            continue
        o = prev.get(x['id']) or {}
        if o.get('det') and nowt - int(o.get('det_t') or 0) < 3300:
            x['det'], x['det_t'] = o['det'], o['det_t']
            continue
        try:
            d = detail(get(x['url']))
            if d:
                x['det'], x['det_t'] = d, nowt
            elif o.get('det'):
                x['det'], x['det_t'] = o['det'], o.get('det_t')
        except Exception as e:
            if o.get('det'):
                x['det'], x['det_t'] = o['det'], o.get('det_t')
    if len(out) < 3:
        old['log'] = ['IPO Premium: table not found (old list kept)']
        old['checked'] = stamp()
        save(OUT, old)
        print(old['log'][0])
        return
    save(OUT, {'updated': stamp(), 'checked': stamp(), 'src': 'ipopremium.in', 'log': [], 'ipos': out})
    print('ipos: %d rows, %d open/upcoming' % (len(out), sum(1 for x in out if x['status'] in ('open', 'upcoming'))))


if __name__ == '__main__':
    main()
