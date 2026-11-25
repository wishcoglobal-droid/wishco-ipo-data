"""Buybacks (tender offer + open market)  ->  data/buybacks.json        WishCo IPO Desk, 25 Nov 2026

Source: Chittorgarh buyback pages  chittorgarh.com/buyback/<slug>/<id>/  (any slug works; the id decides the page).
New ids are found two ways: the buyback calendar page (ids in its links) and by trying the next few ids after the
highest one known. Each page gives: issue type, size (shares, %, Rs cr), buyback price, face value, listing,
timetable (last date to buy, record date, offer opens / closes, finalisation of acceptance, settlement, open-market
opening / closing date), the "Buyback Ratio" table (small shareholders / general category) and the last market price.
Nothing is invented: a field the page does not give stays empty, and a field that was read before is kept when a later
read misses it.  Pages: running buybacks every 30 minutes, others every 6 hours, completed ones not again; dropped
60 days after completion."""
import re, sys, os, html, datetime, time
sys.path.insert(0, os.path.dirname(__file__))
from common import get, rows, num, stamp, load, save, now_ist

OUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'buybacks.json')
CG = 'https://www.chittorgarh.com'
CAL = CG + '/calendar/buyback-calendar/5/'
MAX_READS = 25
AHEAD = 4
FAST, SLOW = 30 * 60, 6 * 3600


def text(h):
    h = re.sub(r'(?is)<script.*?</script>|<style.*?</style>', ' ', h)
    h = re.sub(r'(?i)<br\s*/?>|</(p|div|li|tr|h\d|td|th)>', '\n', h)
    return re.sub(r'[ \t\xa0]+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h)))


def ddate(s):
    s = re.sub(r'^[A-Za-z]{3},\s*', '', str(s or '').strip())
    s = re.sub(r'\s+', ' ', s)
    for f in ('%b %d, %Y', '%B %d, %Y', '%d %b %Y', '%d %B %Y', '%d-%m-%Y', '%d/%m/%Y'):
        try:
            return datetime.datetime.strptime(s, f).date().isoformat()
        except ValueError:
            pass
    m = re.search(r'([A-Z][a-z]+ \d{1,2}, \d{4})', s)
    return ddate(m.group(1)) if m and m.group(1) != s else None


LAB = [('type', r'^issue type$'), ('size_sh', r'^issue size \(shares\)$'), ('size_amt', r'^issue size \(amount\)$'),
       ('price', r'^buyback price$'), ('fv', r'^face value$'), ('listing', r'^listing at$'),
       ('lastBuy', r'^last date to buy'), ('record', r'^record date$'), ('open', r'^offer opens on$|^buyback opening date$|^offer opening date$'),
       ('close', r'^offer closes on$|^buyback closing date$|^offer closing date$|^last date for receipt of tender'),
       ('accept', r'^finali[sz]ation of buyback acceptance'), ('settle', r'^last date for settl?e?ment of bids')]
DATES = {'lastBuy', 'record', 'open', 'close', 'accept', 'settle'}


def parse(h, pid):
    """One buyback page -> dict (only fields that were found)."""
    out = {'id': pid}
    t = text(h)
    m = re.search(r'(?is)<h1[^>]*>(.*?)</h1>', h)
    name = text(m.group(1)).strip() if m else ''
    name = re.sub(r'\s*Buyback.*$', '', name).strip()
    if not name:
        m = re.search(r'(?is)<title>(.*?)</title>', h)
        name = re.sub(r'\s*Buyback.*$', '', text(m.group(1)).strip()) if m else ''
    if not name or 'Total Records: 0' in t and 'Buyback Price' not in t:
        return None
    out['name'] = name
    for r in rows(h):
        lab = r[0].strip().lower().rstrip(':')
        for k, rx in LAB:
            if k in out or not re.search(rx, lab):
                continue
            v = r[1].strip()
            if k in DATES:
                d = ddate(v)
                if d:
                    out[k] = d
            else:
                out[k] = v
        c0 = r[0].strip().lower()
        if len(r) >= 2 and re.search(r'small shareholder|reserved', c0):
            m = re.search(r'(\d+)\s*:\s*(\d+)', r[1])
            if m and int(m.group(2)):
                out['ratioS'] = [int(m.group(1)), int(m.group(2))]
                if len(r) > 2 and num(r[2]):
                    out['sharesS'] = int(num(r[2]))
        if len(r) >= 2 and re.search(r'general', c0):
            m = re.search(r'(\d+)\s*:\s*(\d+)', r[1])
            if m and int(m.group(2)):
                out['ratioG'] = [int(m.group(1)), int(m.group(2))]
                if len(r) > 2 and num(r[2]):
                    out['sharesG'] = int(num(r[2]))
    # text fallback for anything the tables missed (label then value on the next line)
    for k, rx in LAB:
        if k in out:
            continue
        m = re.search(r'(?im)^\s*(%s)\s*:?\s*\n?\s*([^\n]{3,60})' % rx.strip('^$').replace('$', '').replace('^', ''), t)
        if m:
            v = m.group(len(m.groups())).strip()
            if k in DATES:
                d = ddate(v)
                if d:
                    out[k] = d
            elif v and v not in ('[.]', '-'):
                out[k] = v
    ty = (out.get('type') or '').lower()
    out['type'] = 'open' if 'open market' in ty else 'tender' if 'tender' in ty else None
    if not out['type']:
        return None
    p = num(re.sub(r'(?i)per share.*$', '', out.get('price') or ''))
    out['price'] = p
    out['fv'] = num(re.sub(r'(?i)per share.*$', '', out.get('fv') or ''))
    s = out.pop('size_sh', '') or ''
    m = re.match(r'(?i)\s*(?:up to\s*)?([\d,.]+)\s*(lakh|crore)?', s)
    if m and num(m.group(1)) is not None:
        v = num(m.group(1)) * (1e5 if (m.group(2) or '').lower() == 'lakh' else 1e7 if (m.group(2) or '').lower() == 'crore' else 1)
        out['shares'] = int(round(v))
    m = re.search(r'([\d.]+)\s*%', s)
    out['pct'] = float(m.group(1)) if m else None
    a = out.pop('size_amt', '') or ''
    m = re.search(r'([\d,.]+)\s*Cr', a, re.I)
    out['amt'] = num(m.group(1)) if m else None
    # last market price: price panel  "NSE ... 372.90 ▼4.65 (1.23%)"  or  "Last Price 372.90"
    m = (re.search(r'(?i)(?:last|current)\s+(?:traded\s+|market\s+)?price[^\d₹]{0,30}₹?\s*([\d,]+\.\d{1,2})', t) or
         re.search(r'₹?\s*([\d,]+\.\d{2})\s*[▲▼]', t))
    if m and num(m.group(1)):
        out['mp'] = num(m.group(1))
        out['mpDate'] = now_ist().date().isoformat()
    out['url'] = CG + '/buyback/x/%d/' % pid
    return out


def done(x, today):
    z = x.get('close') if x.get('type') == 'open' else (x.get('settle') or None)
    return bool(z and z < today)


def main():
    old = load(OUT, {})
    have = {x['id']: x for x in old.get('items', []) if x.get('id')}
    meta = old.get('meta', {})
    today = now_ist().date().isoformat()
    ids = set(have)
    try:
        ids |= {int(i) for i in re.findall(r'/buyback(?:-calendar-events)?/[a-z0-9-]+/(\d+)/', get(CAL))}
    except Exception as e:
        print('buyback: calendar', e)
    top = max(ids | {old.get('max_id', 0)}) if ids else old.get('max_id', 0)
    probe = list(range(top + 1, top + 1 + AHEAD))
    want = []
    for i in sorted(ids, reverse=True):
        x = have.get(i)
        if x and done(x, today):
            continue
        last = meta.get(str(i), 0)
        wait = FAST if (not x or not done(x, today)) and (x is None or x.get('record') is None or (x.get('close') or '9') >= today) else SLOW
        if time.time() - last >= wait:
            want.append(i)
    want = probe + want
    reads = 0
    new_top = top
    for i in want:
        if reads >= MAX_READS:
            break
        reads += 1
        try:
            p = parse(get(CG + '/buyback/x/%d/' % i), i)
        except Exception as e:
            print('buyback: page', i, e)
            continue
        meta[str(i)] = int(time.time())
        if not p:
            continue
        new_top = max(new_top, i)
        x = have.get(i, {'id': i, 'first': today})
        for k, v in p.items():
            if v not in (None, ''):
                x[k] = v
        have[i] = x
    keep = []
    for x in have.values():
        z = x.get('close') if x.get('type') == 'open' else (x.get('settle') or x.get('close'))
        if z and (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(z)).days > 60:
            continue
        keep.append(x)
    keep.sort(key=lambda x: -x['id'])
    save(OUT, {'updated': stamp(), 'src': 'Chittorgarh buyback pages (company filings)', 'max_id': new_top,
               'items': keep, 'meta': meta, 'reads': reads, 'history': old.get('history') or []})
    print('buyback: %d items, %d pages read, top id %d' % (len(keep), reads, new_top))


if __name__ == '__main__':
    main()
