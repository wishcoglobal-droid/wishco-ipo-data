"""Anchor books from Chittorgarh  ->  data/anchors.json

Source: each IPO's Chittorgarh subscription page  chittorgarh.com/ipo_subscription/<slug>/<id>/
        table "Anchor Investor Allocation" (#, Anchor, Group Entity, Shares Allotted, Amt (Rs cr), % Allocated, ...)
IPOs:   Chittorgarh's mainboard and SME IPO dashboards (current and recent IPOs, with slug and id).

Kind of each anchor:  m = Indian mutual fund (group entity says MUTUAL FUND; or a known Indian AMC fund whose group
entity is written without those words, e.g. "OLD BRIDGE"), i = insurer / pension fund, f = foreign and others.
Totals are checked: the rows must add up to the table's Total line (shares exactly, Rs cr within 0.05) and every row's
Rs cr must equal shares x price. A book that fails the check is written with ok=false and the app does not use it.

Score inputs for the app's 5-pillar anchor score (same rules as the IPO Desk app, aScore):
  tier  = large names: distinct mutual fund houses + distinct insurers / pension funds + distinct global names
  flags = weak-fund check 6..18: 18 - 0.3 x (% of the book that went to small, little-known funds), rounded
Nothing is invented: a page without the table is recorded as "not yet" and read again later.
Pages: an IPO with no anchor book yet is read every 25 minutes; one with a book every 6 hours; an IPO that closed more
than 7 days ago is not read again, and is dropped from the file 45 days after it closed."""
import re, sys, os, html, math, datetime
sys.path.insert(0, os.path.dirname(__file__))
from common import get, rows, num, stamp, load, save, now_ist

OUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'anchors.json')
CG = 'https://www.chittorgarh.com'
DASH = ['/ipo/ipo_dashboard.asp', '/ipo/ipo_dashboard.asp?a=sme']
MAX_READS = 40            # pages read per run (each about a second)
WAIT_NONE = 25 * 60       # seconds before a page without an anchor book is read again
WAIT_HAVE = 6 * 3600      # seconds before a page with an anchor book is read again

INS = re.compile(r'INSURANCE|ASSURANCE|PENSION|\bNPS\b|PROVIDENT|\bLIC\b|EMPLOYEES', re.I)
FOREIGN = re.compile(r'\b(ICAV|PLC|VCC|SICAV|PTE|MAURITIUS|SINGAPORE|LUXEMBOURG|CAYMAN|ODI|LLC|INC|GMBH|S\.?A\.?|AG)\b', re.I)
AMC = re.compile(r'^(HDFC|SBI|ICICI PRU(DENTIAL)?|NIPPON INDIA|KOTAK|AXIS|ADITYA BIRLA( SUN LIFE)?|ABSL|TATA|MIRAE ASSET|DSP|UTI|'
                 r'INVESCO INDIA|MOTILAL OSWAL|EDELWEISS|BANDHAN|CANARA ROBECO|FRANKLIN INDIA|HSBC|PGIM INDIA|QUANT|WHITEOAK CAPITAL|'
                 r'360 ONE|BARODA BNP PARIBAS|SUNDARAM|LIC MF|ITI|JM|MAHINDRA MANULIFE|PARAG PARIKH|UNION|BAJAJ FINSERV|GROWW|NAVI|'
                 r'HELIOS|OLD BRIDGE|SAMCO|ZERODHA|TRUST ?MF|SHRIRAM|NJ|UNIFI|ANGEL ONE|CHOICE|TITANIUM|ISIF)\b.*\b(FUND|SCHEME)\b', re.I)
# large global names (counted as top-tier); key = short name shown in the app
GLOBAL = [
    ('ADIA', r'ABU DHABI INVESTMENT'), ('Société Générale', r'SOCIETE GENERALE'), ('Morgan Stanley', r'MORGAN STANLEY'),
    ('Goldman Sachs', r'GOLDMAN SACHS'), ('Citigroup', r'CITIGROUP'), ('Ashoka', r'\bASHOKA\b'), ('Nomura', r'\bNOMURA\b'),
    ('IFC (World Bank group)', r'INTERNATIONAL FINANCE CORP'), ('MIT', r'MASSACHUSETTS INSTITUTE'), ('SageOne', r'SAGEONE'),
    ('GIC Singapore', r'GOVERNMENT OF SINGAPORE'), ('Monetary Authority of Singapore', r'MONETARY AUTHORITY OF SINGAPORE'),
    ('Norges Bank', r'\bNORGES\b'), ('Government Pension Fund Global', r'GOVERNMENT PENSION FUND GLOBAL'),
    ('Kuwait Investment Authority', r'KUWAIT INVESTMENT'), ('Qatar Investment Authority', r'QATAR INVESTMENT'),
    ('Temasek', r'TEMASEK'), ('BlackRock', r'BLACKROCK'), ('Fidelity', r'FIDELITY'), ('Vanguard', r'VANGUARD'),
    ('Jupiter', r'\bJUPITER\b'), ('Amansa', r'AMANSA'), ('Allianz', r'ALLIANZ'), ('Pictet', r'PICTET'), ('T. Rowe Price', r'T\.? ?ROWE'),
    ('Capital Group', r'CAPITAL GROUP|SMALLCAP WORLD|NEW WORLD FUND'), ('J.P. Morgan', r'J\.? ?P\.? ?MORGAN|JPMORGAN'),
    ('BNP Paribas', r'BNP PARIBAS'), ('HSBC Global', r'HSBC GLOBAL'), ('Natixis', r'NATIXIS'), ('Eastspring', r'EASTSPRING'),
    ('Schroders', r'SCHRODER'), ('abrdn', r'ABERDEEN|ABRDN'), ('UBS', r'\bUBS\b'), ('BofA', r'BOFA|MERRILL LYNCH'),
    ('Macquarie', r'MACQUARIE'), ('Invesco', r'\bINVESCO\b'), ('Franklin Templeton', r'TEMPLETON'), ('Nuveen', r'NUVEEN'),
    ('Ontario Teachers', r'ONTARIO TEACHERS'), ('CPP Investments', r'CANADA PENSION'), ('Wellington', r'WELLINGTON'),
    ('Copthall', r'COPTHALL'), ('Goldman', r'GOLDMAN'), ('Societe Generale', r'SOCGEN'),
]
# known names that are neither top-tier nor "small funds"
KNOWN = re.compile(r'INTEGRATED CORE|238 PLAN|360 ONE|NUVAMA|AVENDUS|MARCELLUS|ABAKKUS|CARNELIAN|MALABAR|ENAM|\bASK\b|'
                   r'KOTAK|HDFC|ICICI|AXIS|MOTILAL|ADITYA BIRLA|EDELWEISS|BANDHAN|WHITEOAK|TATA', re.I)
SMALLFUND = re.compile(r'\b(FUND|SCHEME|VCC|AIF|CAPITAL)\b', re.I)


def key(name):
    t = html.unescape(str(name or '')).lower().replace('&', ' and ')
    t = re.sub(r'\b(ipo|limited|ltd|private|pvt|india|the|and)\b', ' ', t)
    return re.sub(r'[^a-z0-9]', '', t)


def ddate(s):
    s = re.sub(r'^[A-Za-z]{3},\s*', '', str(s or '').strip())
    for f in ('%b %d, %Y', '%d %b %Y', '%B %d, %Y'):
        try:
            return datetime.datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def short(d):
    return d.strftime('%d %b').lstrip('0') if d else 'NA'


def inr(x):
    """1234567.8 -> '12,34,567.80' (Indian grouping, 2 decimals)."""
    neg, x = x < 0, abs(x)
    a, b = ('%.2f' % x).split('.')
    if len(a) > 3:
        h, t = a[:-3], a[-3:]
        h = re.sub(r'(\d)(?=(\d\d)+$)', r'\1,', h)
        a = h + ',' + t
    return ('-' if neg else '') + a + '.' + b


def kind(name, group):
    g, n = (group or '').upper(), (name or '').upper()
    if 'MUTUAL FUND' in g:
        return 'm'
    if INS.search(g) or INS.search(n):
        return 'i'
    if AMC.search(n) and not FOREIGN.search(n):
        return 'm'
    return 'f'


def glob(name, group):
    t = (name or '') + ' | ' + (group or '')
    for k, rx in GLOBAL:
        if re.search(rx, t, re.I):
            return {'Goldman': 'Goldman Sachs', 'Societe Generale': 'Société Générale'}.get(k, k)
    return None


def title(s):
    s = re.sub(r'\b(FUND|SCHEME|LTD\.?|LIMITED|PVT\.?)\b|[-–]\s*I+$', '', s or '', flags=re.I)
    w = [x for x in re.split(r'\s+', s.strip(' -.,')) if x]
    up = {'AIF', 'LLC', 'VCC', 'PLC', 'ICAV', 'II', 'III', 'IV'}
    return ' '.join(x.upper() if len(x) <= 2 or x.upper() in up or not re.search(r'[AEIOUaeiou]', x) else x.capitalize() for x in w)


def weakname(x):
    g = (x['group'] or '').strip()
    if len(g.split()) >= 2:
        return title(g)
    return title(' '.join(re.split(r'\s+|-', re.sub(r'\b(FUND|SCHEME|VCC)\b.*$', '', x['name'], flags=re.I).strip())[:2]))


def dashboard():
    """[(slug, id, name, board)] from the two IPO dashboards."""
    out, seen = [], set()
    for path in DASH:
        board = 'SME' if 'sme' in path else 'Mainboard'
        try:
            page = get(CG + path)
        except Exception as e:
            print('dashboard %s: %s' % (path, e))
            continue
        for m in re.finditer(r'<a[^>]+href="(?:https://www\.chittorgarh\.com)?/ipo/([a-z0-9-]+)/(\d+)/"[^>]*>(.*?)</a>', page, re.S):
            nm = html.unescape(re.sub(r'<[^>]+>', '', m.group(3))).strip()
            nm = re.sub(r'\s+IPO$', '', nm)
            if m.group(2) in seen or not nm or len(nm) > 90:
                continue
            seen.add(m.group(2))
            out.append((m.group(1), m.group(2), nm, board))
    return out


def parse(page):
    """Anchor book from a subscription page, or {'found': False} when the table is not there yet."""
    text = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', page)))
    o = {'found': False}
    m = re.search(r'\|\s*(?:Listing|Listed) at [^|]{1,40}\|\s*([A-Z][a-z]{2}, [A-Z][a-z]{2} \d{1,2}, \d{4})\s*-\s*([A-Z][a-z]{2}, [A-Z][a-z]{2} \d{1,2}, \d{4})', text)
    if m:
        a, b = ddate(m.group(1)), ddate(m.group(2))
        o['open'], o['close'] = (a.isoformat() if a else ''), (b.isoformat() if b else '')
    i = page.find("id='AnchorTable'")
    if i < 0:
        i = page.find('id="AnchorTable"')
    if i < 0:
        return o
    blk = page[max(0, page.rfind('anchorinvestorlist', 0, i)):i]
    bt = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', blk)))
    bd = re.search(r'Bid Date\s+([A-Z][a-z]{2} \d{1,2}, \d{4})', bt)
    pr = re.search(r'Price\s+₹\s*([\d,.]+)', bt) or re.search(r'price of Rs\.?\s*([\d,.]+)', bt)
    l30 = re.search(r'Shares Locked \(30 Days\)\s+([\d,]+)', bt)
    l90 = re.search(r'Shares Locked \(90 Days\)\s+([\d,]+)', bt)
    tb = page[i:page.find('</table>', i)]
    data, total = [], None
    for r in rows(tb):
        if r[0].strip().isdigit() and len(r) >= 5:
            sh, cr = num(r[3]), num(r[4])
            if sh is None or cr is None:
                continue
            data.append({'name': html.unescape(r[1]).strip(), 'group': html.unescape(r[2]).strip(), 'shares': int(sh), 'cr': cr})
        elif len(r) >= 2 and num(r[0]) and num(r[1]) and not data == []:
            total = (int(num(r[0])), num(r[1]))
    if not data:
        return o
    price = num(pr.group(1)) if pr else None
    bid = ddate(bd.group(1)) if bd else None
    o.update(found=True, bid=bid.isoformat() if bid else '', price=price, lock30_shares=int(num(l30.group(1))) if l30 else None,
             lock90_shares=int(num(l90.group(1))) if l90 else None, list=data, total=total)
    return o


def book(p):
    """Score inputs and the app's anchor JSON fields from a parsed table."""
    L = p['list']
    for x in L:
        x['k'] = kind(x['name'], x['group'])
    sh = sum(x['shares'] for x in L) or 1
    cr = round(sum(x['cr'] for x in L), 2)
    tot = p.get('total')
    price = p.get('price')
    bad_rows = [x['name'] for x in L if price and abs(x['shares'] * price / 1e7 - x['cr']) > 0.011 + x['cr'] * 0.0005]
    ok_sh = bool(tot) and tot[0] == sh
    ok_cr = bool(tot) and abs(tot[1] - cr) <= 0.05
    share = lambda k: round(sum(x['shares'] for x in L if x['k'] == k) / sh * 100, 2)
    mf, ins = share('m'), share('i')
    mfg = sorted({x['group'].upper() for x in L if x['k'] == 'm'})
    mfs = [x for x in L if x['k'] == 'm']
    insg = sorted({x['group'].upper() for x in L if x['k'] == 'i'})
    gl = []
    for x in L:
        if x['k'] == 'f':
            g = glob(x['name'], x['group'])
            if g and g not in gl:
                gl.append(g)
    tier = len(mfg) + len(insg) + len(gl)
    parts = []
    if mfg:
        parts.append('%d mutual fund house%s' % (len(mfg), '' if len(mfg) == 1 else 's'))
    if insg:
        parts.append('%d insurer%s / pension fund%s' % (len(insg), '' if len(insg) == 1 else 's', '' if len(insg) == 1 else 's'))
    if gl:
        parts.append('%d global name%s (%s)' % (len(gl), '' if len(gl) == 1 else 's', ', '.join(gl)))
    tierWhy = ('%d large name%s: %s' % (tier, '' if tier == 1 else 's', ', '.join(parts))) if tier else 'No large mutual fund, insurer or global fund'
    weak = [x for x in L if x['k'] == 'f' and not glob(x['name'], x['group']) and not KNOWN.search(x['name'] + ' ' + x['group'])
            and SMALLFUND.search(x['name'] + ' ' + x['group'])]
    wcr = round(sum(x['cr'] for x in weak), 2)
    base = (tot[1] if tot else cr) or 0
    w = wcr / base * 100 if base else 0
    flags = max(6, min(18, int(math.floor(18 - 0.3 * w + 0.5))))
    if weak:
        names = []
        for x in weak:
            t = weakname(x)
            if t and t not in names:
                names.append(t)
        flagWhy = '%d small fund%s (%s) got ₹%s cr (%.2f%%); they may sell early.' % (
            len(weak), '' if len(weak) == 1 else 's', ', '.join(names), inr(wcr), w)
        flagWhy += ' The rest went to large institutions.' if w < 5 else ' The rest are known names.'
    else:
        flagWhy = 'No small or little-known funds in the list.'
    R = sorted(L, key=lambda x: -x['cr'])
    mfN = [x['name'] for x in R if x['k'] == 'm'][:8]
    fo = [x['name'] for x in R if x['k'] != 'm'][:5]
    sch = '%d AMC%s · %d scheme%s' % (len(mfg), '' if len(mfg) == 1 else 's', len(mfs), '' if len(mfs) == 1 else 's') if mfs else 'No mutual fund'
    return {
        'ok': ok_sh and ok_cr and not bad_rows,
        'check': {'rows': len(L), 'shares': sh, 'cr': cr, 'total_shares': tot[0] if tot else None, 'total_cr': tot[1] if tot else None,
                  'shares_match': ok_sh, 'cr_match': ok_cr, 'rows_off': bad_rows[:5]},
        'n': len(L), 'amt': tot[1] if tot else cr, 'mf': mf, 'ins': ins, 'schemes': sch, 'tier': tier, 'tierWhy': tierWhy,
        'flags': flags, 'flagWhy': flagWhy, 'weak_pct': round(w, 2),
        'rows': [[x['name'], x['k'], x['cr'], x['shares'], x['group']] for x in R],
        'mfN': mfN, 'fo': fo, 'more': max(0, len(L) - len(mfN) - len(fo)),
    }


def lockdates(page):
    t = {}
    for r in rows(page):
        j = ' '.join(r)
        m = re.search(r'lock-in period end date for (50% shares|remaining shares)', j)
        if m and len(r) >= 2:
            d = ddate(r[-1])
            if d:
                t['50' if '50' in m.group(1) else '100'] = d
    return [short(t.get('50')), short(t.get('100'))] if t else None


def main():
    old = load(OUT, {})
    prev = old.get('ipos') or {}
    nowt = int(now_ist().timestamp())
    today = now_ist().date()
    log, reads = [], 0
    dash = dashboard()
    if not dash:
        log.append('Chittorgarh dashboards did not answer (old file kept)')
    known = {k: (v.get('slug'), k, v.get('name'), v.get('board')) for k, v in prev.items()}
    for d in dash:
        known[d[1]] = d
    order = sorted(known.values(), key=lambda d: (d[1] in prev, -int(d[1])))   # never-read first, newest first
    out = dict(prev)
    for slug, cid, name, board in order:
        e = dict(prev.get(cid) or {})
        e.update(slug=slug, id=cid, name=name or e.get('name'), board=board or e.get('board'), key=key(name or e.get('name')))
        e['url'] = '%s/ipo_subscription/%s/%s/' % (CG, slug, cid)
        cl = ddate(e.get('close') or '') if e.get('close') else None
        try:
            cl = datetime.date.fromisoformat(e['close']) if e.get('close') else None
        except ValueError:
            cl = None
        if cl and (today - cl).days > 45:
            out.pop(cid, None)
            continue
        out[cid] = e
        if cl and (today - cl).days > 7:
            continue
        wait = WAIT_HAVE if e.get('found') else WAIT_NONE
        if nowt - int(e.get('t') or 0) < wait or reads >= MAX_READS:
            continue
        reads += 1
        try:
            p = parse(get(e['url']))
        except Exception as ex:
            log.append('%s: %s' % (name, ex))
            continue
        e['t'] = nowt
        if p.get('open'):
            e['open'], e['close'] = p['open'], p['close']
        if not p['found']:
            e['found'] = e.get('found', False)
            continue
        b = book(p)
        bid = datetime.date.fromisoformat(p['bid']) if p.get('bid') else None
        e.update(found=True, read=stamp(), date=short(bid), bid=p.get('bid'), price=p.get('price'),
                 lock30_shares=p.get('lock30_shares'), lock90_shares=p.get('lock90_shares'), **b)
        if not e.get('lock'):
            try:
                ld = lockdates(get('%s/ipo/%s/%s/' % (CG, slug, cid)))
                if ld:
                    e['lock'] = ld
            except Exception:
                pass
        if not b['ok']:
            log.append('%s: totals do not match (%s)' % (name, b['check']))
        print('%s: %d anchors, ₹%s cr, MF %.2f%%, ins %.2f%%, tier %d, flags %d, ok %s' % (
            name, b['n'], inr(b['amt']), b['mf'], b['ins'], b['tier'], b['flags'], b['ok']))
    save(OUT, {'updated': stamp(), 'src': 'chittorgarh.com anchor allocation tables', 'reads': reads, 'log': log, 'ipos': out})
    print('anchors: %d IPOs in file, %d with a book, %d pages read' % (len(out), sum(1 for v in out.values() if v.get('found')), reads))


if __name__ == '__main__':
    main()
