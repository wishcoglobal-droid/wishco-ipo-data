"""WishCo IPO Desk -- IPO card image for Telegram (owner OK 24 Nov 2026 21:05).

card_html(ipo, ...) builds the same card as the app's IPO tile (status, name, price, lot, issue, GMP, five dates,
subscription tiles, GMP x shares per category, fact line, Hold score / Anchor book, footnote, WishCo watermark).
render(html, path) turns it into a PNG with headless Chrome (installed on GitHub runners) and crops it with Pillow.
English only inside the picture (the runner has no Hindi font).  If Chrome is missing, render() returns False and the
alert goes as text.
"""
import datetime, html, os, re, shutil, subprocess, tempfile

MO = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()


def esc(s):
    return html.escape(str(s if s is not None else ''))


def dd(iso):
    try:
        y, m, d = [int(x) for x in str(iso)[:10].split('-')]
        return '%d %s' % (d, MO[m - 1])
    except Exception:
        return 'NA'


def day(iso):
    try:
        return datetime.date.fromisoformat(str(iso)[:10])
    except Exception:
        return None


def refund_day(listing):
    """Refund = working day before listing (T+3 cycle)."""
    d = day(listing)
    if not d:
        return None
    d -= datetime.timedelta(days=1)
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d.isoformat()


def inr(v, dec=2):
    if v is None:
        return 'NA'
    v = round(float(v), dec)
    neg, v = v < 0, abs(v)
    whole = int(v)
    frac = ('%.*f' % (dec, v - whole))[1:] if v != whole else ''
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r'(\d)(?=(\d\d)+$)', r'\1,', head)
        s = head + ',' + tail
    return ('-' if neg else '') + '₹' + s + frac


def price_txt(i):
    lo, hi = i.get('low') or 0, i.get('high') or 0
    if not hi:
        return 'Not announced'
    if lo == hi or not lo:
        return inr(hi) + ' (fixed)'
    return inr(lo) + '–' + inr(hi)[1:]


def status_tag(i, today):
    st, o, c = i.get('status'), i.get('open'), i.get('close')
    if st == 'closed':
        return 'cl', 'Closed %s · Listing %s' % (dd(c), dd(i.get('listing') or (i.get('det') or {}).get('listing')))
    if st == 'open':
        dc, dt = day(c), day(today)
        left = (dc - dt).days if dc and dt else None
        return 'op', 'Closes %s · %s' % (dd(c), 'closes today' if left == 0 else ('%d days left' % left if left else 'open'))
    t = 'Opens %s · Closes %s' % (dd(o), dd(c))
    if 'TENTATIVE' in str(i.get('exch') or '').upper():
        t += ' · tentative'
    return '', t


def exch_txt(i):
    e = str(i.get('exch') or '').upper()
    if i.get('board') == 'SME':
        return e if 'SME' in e else 'SME'
    return 'NSE · BSE' if e == 'MAINBOARD' else ('Exchange not yet known' if 'TENTATIVE' in e else e or 'NSE · BSE')


CSS = """
*{box-sizing:border-box}body{margin:0;background:#0e1621;font-family:Inter,'DejaVu Sans',sans-serif;color:#e9eef4}
.w{width:480px;padding:14px;position:relative;overflow:hidden}
.wm{position:absolute;left:-20px;top:42%;transform:rotate(-24deg);font:800 76px Inter,'DejaVu Sans',sans-serif;color:rgba(247,147,30,.08);white-space:nowrap;pointer-events:none}
.ev{font-weight:700;font-size:15px;margin:0 0 9px;color:#fff}.ev b{color:#f7931e}
.ct{background:#151b24;border:1px solid #2a3442;border-radius:14px;padding:12px;display:grid;gap:9px;position:relative}
.r1{display:flex;align-items:center;gap:6px}
.tag{font-size:13px;font-weight:700;padding:5px 9px;border-radius:8px;background:rgba(247,147,30,.18);color:#f7931e;flex:1}
.tag.cl{background:#26303c;color:#b8c2cf}.tag.op{background:rgba(60,207,122,.16);color:#3ccf7a}
.mk{width:30px;height:30px;border-radius:8px;background:#f7931e;color:#111;font-weight:900;display:flex;align-items:center;justify-content:center;font-size:15px}
.r2{display:flex;gap:10px;align-items:center}
.lg{width:42px;height:42px;border-radius:10px;background:#283445;display:flex;align-items:center;justify-content:center;font-weight:800;color:#f7931e;flex:none;font-size:16px}
.nm b{display:block;font-size:17px;line-height:1.2}.nm small{color:#8b98a8;font-size:12.5px;font-weight:600}
.ofs{display:inline-block;margin-left:6px;font-size:11px;font-weight:800;color:#111;background:#f2c94c;border-radius:5px;padding:1px 6px;vertical-align:2px}
.kv{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.kv div{background:#1d2531;border-radius:9px;padding:6px 9px}.kv span{display:block;font-size:12px;color:#8b98a8}.kv b{font-size:15px}
.src{font-size:11.5px;color:#8b98a8;margin-top:-3px}
.g5,.g4,.g3{display:grid;gap:4px;text-align:center}.g5{grid-template-columns:repeat(5,1fr)}.g4{grid-template-columns:repeat(4,1fr)}.g3{grid-template-columns:repeat(3,1fr)}
.g5 div,.g4 div,.g3 div{background:#1d2531;border-radius:8px;padding:5px 2px}
.g5 span,.g4 span,.g3 span{display:block;font-size:11px;color:#8b98a8}.g5 b,.g4 b{font-size:13.5px}
.o b{color:#f7931e}.bl b{color:#4aa3ff}.up b{color:#3ccf7a}.yw b{color:#f2c94c}.dn b{color:#ef5b5b}
.g3 b{font-size:14px;color:#3ccf7a}.g3 b.mu{color:#8b98a8}.g3 small{display:block;font-size:10.5px;color:#8b98a8}
.fact{background:rgba(242,201,76,.13);color:#f5dc8c;border-radius:9px;padding:7px 10px;font-size:13px;line-height:1.4}
.two{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.two div{border:1px solid #2a3442;background:#1d2531;border-radius:10px;padding:8px;text-align:center;font-weight:600;font-size:13.5px}
.lt{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;background:#55606e}.lt.g{background:#3ccf7a}.lt.y{background:#f2c94c}.lt.r{background:#ef5b5b}
.fn{font-size:11px;color:#8b98a8;display:flex;justify-content:space-between}
"""


def initials(n):
    w = [x for x in re.split(r'\s+', n) if x[:1].isalpha()]
    return ''.join(x[0].upper() for x in w[:2]) or 'IPO'


def sub_cls(v):
    if v is None:
        return ''
    return 'up' if v >= 3 else ('yw' if v >= 1 else 'dn')


def card_html(i, name, lines, today, sub=None, anchor=None, extra=None, fact=None, data_time=''):
    """i = row of ipos.json; lines = event lines (plain text); sub = {'QIB':..,'B-HNI':..,...}; anchor = anchors.json row."""
    det = i.get('det') or {}
    cls, tag = status_tag(i, today)
    gmp, hi = i.get('gmp'), i.get('high') or 0
    gtxt = (inr(gmp) + (' (%.1f%%)' % (gmp / hi * 100) if hi else '')) if gmp and gmp > 0 else 'No GMP yet'
    listing = i.get('listing') or det.get('listing')
    ofs = bool(extra and (extra.get('fin') or {}).get('fresh') == 0)
    sub = sub or {}
    retail = 'Indiv.' if i.get('board') == 'SME' else 'Retail'
    subcells = [('QIB', sub.get('QIB')), ('B-HNI', sub.get('B-HNI', sub.get('NII'))), ('S-HNI', sub.get('S-HNI')), (retail, sub.get('Retail'))]
    mins = det.get('mins') or {}
    lab = {'r': retail, 's': 'S-HNI', 'b': 'B-HNI'}
    gains = ''
    if mins:
        cells = []
        for k in ('r', 's', 'b'):
            m = mins.get(k)
            if not m:
                continue
            g = '<b>%s</b>' % inr(gmp * m['shares']) if gmp and gmp > 0 else '<b class="mu">No GMP</b>'
            cells.append('<div><span>%s · %d lot%s · %s</span>%s<small>GMP × %s sh</small></div>' % (
                lab[k], m['lots'], '' if m['lots'] == 1 else 's', inr(m['amount']), g, '{:,}'.format(m['shares'])))
        gains = '<div class="g3">%s</div>' % ''.join(cells)
    a_light = ''
    if anchor and anchor.get('ok'):
        a_light = 'g' if (anchor.get('mf') or 0) >= 40 else 'y'
    lot = det.get('lot')
    total = sub.get('Total')
    return ('<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">'
            '<style>%s</style></head><body><div class="w" id="w"><div class="wm">WishCo · WishCo</div>' % CSS +
            ''.join('<div class="ev">%s</div>' % ev_html(t) for t in lines) +
            '<div class="ct">'
            '<div class="r1"><span class="tag %s">%s</span><span class="mk">W</span></div>' % (cls, esc(tag)) +
            '<div class="r2"><div class="lg">%s</div><div class="nm"><b>%s%s</b><small>%s · %s</small></div></div>' % (
                esc(initials(name)), esc(name), '<span class="ofs">100% OFS</span>' if ofs else '',
                esc(str(i.get('board') or '').upper()), esc(exch_txt(i))) +
            '<div class="kv"><div><span>Price band</span><b>%s</b></div><div><span>Lot size</span><b>%s</b></div>'
            '<div><span>Issue size</span><b>%s</b></div><div><span>GMP*</span><b>%s</b></div></div>' % (
                esc(price_txt(i)), ('{:,} shares'.format(lot)) if lot else 'NA',
                (inr(det['issue_cr']) + ' Cr') if det.get('issue_cr') else 'NA', esc(gtxt)) +
            '<div class="src">GMP source: IPO Premium · %s</div>' % esc(data_time) +
            '<div class="g5"><div><span>Open</span><b>%s</b></div><div class="o"><span>Close</span><b>%s</b></div>'
            '<div><span>Allot</span><b>%s</b></div><div class="bl"><span>Refund</span><b>%s</b></div><div><span>Listing</span><b>%s</b></div></div>' % (
                dd(i.get('open')), dd(i.get('close')), dd(det.get('allot')), dd(refund_day(listing)), dd(listing)) +
            '<div class="g4">%s</div>' % ''.join('<div class="%s"><span>%s</span><b>%s</b></div>' % (
                sub_cls(v), k, ('%sx' % inr(v)[1:]) if v is not None else ('in app' if i.get('status') == 'closed' else '—')) for k, v in subcells) +
            (('<div class="src">Total subscription %sx</div>' % inr(total)[1:]) if total is not None else '') +
            gains +
            ('<div class="fact">%s</div>' % esc(fact) if fact else '') +
            '<div class="two"><div><span class="lt%s"></span>Hold score</div><div><span class="lt %s"></span>Anchor book</div></div>' % (
                ' g' if extra and extra.get('fin') else '', a_light) +
            '<div class="fn"><span>* Indicative, not investment advice</span><span>WishCo IPO Desk</span></div>'
            '</div></div></body></html>')


def ev_html(t):
    """'New IPO · Mainboard' -> first part bold orange."""
    p = esc(t).split(' · ', 1)
    return '<b>%s</b>%s' % (p[0], (' · ' + p[1]) if len(p) > 1 else '')


def chrome():
    for c in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser'):
        p = shutil.which(c)
        if p:
            return p
    return None


def render(page, out_png):
    """HTML -> cropped PNG. True on success."""
    exe = chrome()
    if not exe:
        print('cards: no Chrome on this machine')
        return False
    d = tempfile.mkdtemp()
    src = os.path.join(d, 'card.html')
    with open(src, 'w', encoding='utf-8') as f:
        f.write(page)
    raw = os.path.join(d, 'raw.png')
    cmd = [exe, '--headless=new', '--no-sandbox', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=2',
           '--window-size=480,1600', '--virtual-time-budget=4000', '--default-background-color=0e1621ff',
           '--screenshot=' + raw, 'file://' + src]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    except Exception as e:
        print('cards: chrome failed', e)
        return False
    if not os.path.exists(raw):
        return False
    try:
        from PIL import Image
        im = Image.open(raw).convert('RGB')
        w, h = im.size
        bg = im.getpixel((w - 2, h - 2))
        px = im.load()
        bottom = h - 1
        while bottom > 50:
            row_bg = all(sum(abs(a - b) for a, b in zip(px[x, bottom], bg)) < 12 for x in range(0, w, 6))
            if not row_bg:
                break
            bottom -= 1
        im.crop((0, 0, w, min(h, bottom + 28))).save(out_png, optimize=True)
    except Exception as e:
        print('cards: crop skipped', e)
        shutil.copy(raw, out_png)
    return True
