"""Buyback alert cards on Telegram                                   WishCo IPO Desk, 25 Nov 2026

Reads data/buybacks.json and sends a picture card (same look as the IPO alert cards) with buttons that open the app's
Buyback section at that buyback (?bb=<id>).  Uses the same bot, chats, quiet hours and ON/OFF switch as alerts.py;
the "Buyback" rule in /settings turns these off.
Events: new buyback announced · record date fixed · entitlement ratio announced · last day to buy tomorrow / today ·
tender opens · tender closes today · money paid.  Open-market buybacks: announced and buying starts only.
First run: no flood — everything already known is marked as sent; a short sample (cards for buybacks you can still act
on) is sent once so the buttons can be tried."""
import os, sys, html, json, tempfile, urllib.parse
sys.path.insert(0, os.path.dirname(__file__))
from common import load, save, now_ist
import alerts, cards

D = os.path.join(os.path.dirname(__file__), '..', 'data')
BB = os.path.join(D, 'buybacks.json')
ST = os.path.join(D, 'bb_alerts_state.json')
BB_CH = 'live'   # Buyback LIVE from 27 Nov 2026 (LIVE v3.11.14.2)
MO = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()


def dd(s):
    if not s:
        return 'NA'
    y, m, d = s[:10].split('-')
    return '%d %s' % (int(d), MO[int(m) - 1])


def inr(v):
    if v is None:
        return 'NA'
    s = ('%d' % round(abs(v))) if abs(v - round(v)) < 1e-9 else ('%.2f' % abs(v))
    i, _, f = s.partition('.')
    if len(i) > 3:
        h, t = i[:-3], i[-3:]
        g = []
        while len(h) > 2:
            g.insert(0, h[-2:]); h = h[:-2]
        if h:
            g.insert(0, h)
        i = ','.join(g + [t])
    return ('−' if v < 0 else '') + '₹' + i + ('.' + f if f else '')


def short(n):
    import re
    return re.sub(r'\s+(Ltd\.?|Limited)$', '', n or '').rstrip('.')


def prem(x):
    return (x['price'] - x['mp']) / x['mp'] * 100 if x.get('mp') and x.get('price') else None


def events(x, today, tomorrow):
    """(event key, text) for this buyback today."""
    out = []
    if x.get('type') == 'open':
        if x.get('open') == today:
            out.append(('open', 'Company starts buying on the exchange today'))
        return out
    if x.get('lastBuy') == tomorrow:
        out.append(('buy1', 'Last day to buy is TOMORROW (%s)' % dd(x['lastBuy'])))
    if x.get('lastBuy') == today:
        out.append(('buy0', 'Last day to buy is TODAY'))
    if x.get('open') == today:
        out.append(('open', 'Tender opens today · closes %s' % dd(x.get('close'))))
    if x.get('close') == today:
        out.append(('close', 'Tender closes today'))
    if x.get('settle') == today:
        out.append(('settle', 'Money for accepted shares paid today'))
    return out


HIST_SMALL = [57.57, 46.82, 35.18, 65.33, 100, 100, 19.13, 40.75, 35.13, 32.1, 62.27, 82.66, 48.55, 100]   # small-shareholder acceptance %, past buybacks (ipoguru.in)


def typical(x):
    """Net per PAN after 20.8% tax: max small-shareholder shares, typical (median) acceptance, rest sold 5% lower."""
    mp, bp = x.get('mp'), x.get('price')
    if x.get('type') != 'tender' or not mp or not bp:
        return None
    h = sorted(HIST_SMALL)
    med = (h[len(h) // 2 - 1] + h[len(h) // 2]) / 2 if len(h) % 2 == 0 else h[len(h) // 2]
    n = int(200000 // (mp * 1.02))
    r = x.get('ratioS')
    acc_pct = max(med, r[0] / r[1] * 100 if r else 0)
    acc = min(n, int(n * acc_pct / 100 + 1e-9))
    net = acc * (bp - mp) - (n - acc) * mp * 0.05
    after = net - (net * 0.208 if net > 0 else 0)
    return acc_pct, n, after, after / (n * mp) * 100


def card_html(x, lines, today):
    p = prem(x)
    pc = '#3ccf7a' if (p or 0) >= 0 else '#ef5b5b'
    rat = lambda r: ('%d : %d' % tuple(r)) if r else 'not yet'
    if x.get('type') == 'open':
        rows = [('Buying starts', x.get('open')), ('Buying ends', x.get('close'))]
        tag = 'Open market buyback'
    else:
        rows = [('Last day to buy', x.get('lastBuy')), ('Record date', x.get('record')), ('Tender opens', x.get('open')),
                ('Tender closes', x.get('close')), ('Acceptance', x.get('accept')), ('Money paid', x.get('settle'))]
        tag = 'Tender offer buyback'
    g = ''.join('<div><span>%s</span><b style="color:%s">%s</b></div>' % (k, '#3ccf7a' if v and v <= today else ('#e9eef4' if v else '#8b98a8'), dd(v)) for k, v in rows)
    kv = [('Buyback price' + (' (max)' if x.get('type') == 'open' else ''), inr(x.get('price'))),
          ('Market price', inr(x.get('mp'))), ('Premium', ('%+.2f%%' % p) if p is not None else 'NA'),
          ('Size', ('₹%.2f cr' % x['amt']) if x.get('amt') else 'NA')]
    kvh = ''.join('<div><span>%s</span><b%s>%s</b></div>' % (k, ' style="color:%s"' % pc if k == 'Premium' else '', html.escape(v)) for k, v in kv)
    ratio = '' if x.get('type') == 'open' else (
        '<div class="two"><div>Small (≤ ₹2 L) <b>%s</b></div><div>General <b>%s</b></div></div>' % (rat(x.get('ratioS')), rat(x.get('ratioG'))))
    ev = ''.join('<div class="ev">%s</div>' % cards.ev_html(t) for t in lines)
    t = typical(x)
    fact = ('<div class="fact">Typical case (past buybacks): %.1f%% of tendered shares accepted → buy %d shares, net %s per PAN after tax (%+.2f%%), rest sold 5%% lower</div>'
            % (t[0], t[1], inr(round(t[2])), t[3])) if t else ''
    return ('<!doctype html><html><head><meta charset="utf-8"><style>%s</style></head><body><div class="w"><div class="wm">WishCo</div>%s'
            '<div class="ct"><div class="r1"><span class="tag op">%s</span><span class="mk">W</span></div>'
            '<div class="r2"><div class="lg">BB</div><div class="nm"><b>%s</b><small>%s</small></div></div>'
            '<div class="kv">%s</div><div class="g3" style="grid-template-columns:repeat(3,1fr)">%s</div>%s%s'
            '<div class="fn"><span>Estimate · not advice</span><span>WishCo IPO Desk · Buyback</span></div></div></div></body></html>'
            ) % (cards.CSS, ev, tag, html.escape(short(x['name'])), html.escape(x.get('listing') or ''), kvh, g, ratio, fact)


def keyboard(x):
    u = alerts.APP[BB_CH] + '&bb=' + urllib.parse.quote(str(x['id']))
    return [[{'text': '📱 Open in app · calculator', 'web_app': {'url': u}}],
            [{'text': '🌐 Source page', 'url': x.get('url') or 'https://www.chittorgarh.com/'}]]


def send(chat, x, lines, today):
    cap = '<b>%s</b> · Buyback\n%s' % (html.escape(short(x['name'])), '\n'.join('• ' + html.escape(t) for t in lines))
    png = os.path.join(tempfile.mkdtemp(), 'bb.png')
    if cards.render(card_html(x, lines, today), png) and alerts.tg_photo(chat, png, cap, keyboard(x)):
        return True
    return alerts.send(chat, cap + '\nPrice %s · market %s' % (inr(x.get('price')), inr(x.get('mp'))), keyboard(x), parse='HTML')


def main():
    if not alerts.TOKEN:
        print('bbalerts: no token')
        return
    now = now_ist()
    today = now.date().isoformat()
    import datetime
    tomorrow = (now.date() + datetime.timedelta(days=1)).isoformat()
    ast = load(alerts.STATE, {})
    chats = ast.get('chats', [])
    st = load(ST, {})
    sent = set(st.get('sent', []))
    bb = load(BB, {}).get('items', [])
    first = not st.get('started')
    q = []
    for x in bb:
        i = x['id']
        k = 'new:%d' % i
        if k not in sent:
            sent.add(k)
            if not first:
                p = prem(x)
                q.append((x, ['New buyback · %s · %s%s' % ('open market' if x.get('type') == 'open' else 'tender offer',
                                                            inr(x.get('price')), (' (%+.1f%% vs market)' % p) if p is not None else '')]))
        for f, label in (('record', 'Record date fixed · %s · buy by %s'), ('ratioS', 'Entitlement ratio announced')):
            k = '%s:%d' % (f, i)
            if x.get(f) and k not in sent:
                sent.add(k)
                if not first and x.get('type') == 'tender':
                    t = label % (dd(x['record']), dd(x.get('lastBuy'))) if f == 'record' else \
                        label + ' · small %d : %d' % tuple(x['ratioS']) + (' · general %d : %d' % tuple(x['ratioG']) if x.get('ratioG') else '')
                    q.append((x, [t]))
        for ek, t in events(x, today, tomorrow):
            k = '%s:%d:%s' % (ek, i, today)
            if k not in sent:
                sent.add(k)
                q.append((x, [t]))
    merged = {}
    for x, ls in q:
        merged.setdefault(x['id'], [x, []])[1].extend(ls)
    if first:
        # one sample so the owner sees the cards: buybacks you can still act on (buy window or tender open)
        for x in bb:
            if x.get('type') != 'tender':
                continue
            if (not x.get('record')) or (x.get('lastBuy') and x['lastBuy'] >= today) or (x.get('open') and x['open'] <= today <= (x.get('close') or '')) or x.get('record') == today:
                merged.setdefault(x['id'], [x, ['Sample · buyback alerts are on']])
        st['started'] = now.strftime('%Y-%m-%d %H:%M')
    on = ast.get('on', True) and ast.get('rules', {}).get('buyback', True) and not alerts.in_quiet(ast, now)
    wait = st.get('wait', [])
    if on and chats:
        todo = [(v[0], v[1]) for v in merged.values()] + [(next((x for x in bb if x['id'] == w['id']), None), w['lines']) for w in wait]
        todo = [t for t in todo if t[0]]
        for chat in chats:
            if first and todo:
                alerts.send(chat, '🧪 TEST · Buyback alert cards\nNew buybacks, record dates, last day to buy and tender dates now come here. '
                                  'The button opens the app\'s Buyback section with the profit calculator.')
            for x, ls in todo:
                send(chat, x, ls, today)
        st['wait'] = []
    else:
        st['wait'] = (wait + [{'id': v[0]['id'], 'lines': v[1]} for v in merged.values()])[-30:]
    st['sent'] = sorted(sent)[-2000:]
    save(ST, st)
    print('bbalerts: %d cards, on %s' % (len(merged), on))


if __name__ == '__main__':
    main()
