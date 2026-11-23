"""WishCo IPO Desk -- Telegram alerts (owner 23 Nov 2026).  Standard library only.

Runs in the GitHub workflow after the data steps.  Reads data/ipos.json, data/anchors.json, data/filings.json and
data/market.json, finds what changed since the last run and sends it to the owner's Telegram.

Bot token:  GitHub secret TELEGRAM_BOT_TOKEN (never written in this repo).  No token -> nothing is sent, nothing fails.
Chat:       the first person who sends /start to the bot becomes the owner; only the owner's chats get alerts.
Settings:   in Telegram itself -- /settings shows buttons to switch each alert on/off, quiet hours, pause.
            The bot answers at its next run (the workflow runs about every 15 minutes in the day).

Alerts (each event once):
  now   : new DRHP/RHP filing, new IPO, price band, anchor book, closing day (morning + subscription every hour
          10:00-17:15), allotment day, listing day, data source stopped
  hourly: GMP move of 10%+ since the last GMP alert (one round-up message)
Quiet hours (default 22-8, owner may change in /settings): messages wait and go out together after the quiet time.  /test always goes at once.
"""
import json, os, re, sys, html, time, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(__file__))
from common import get, rows, num, now_ist, load, save

D = os.path.join(os.path.dirname(__file__), '..', 'data')
STATE = os.path.join(D, 'alerts_state.json')
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
API = 'https://api.telegram.org/bot%s/' % TOKEN

RULES = [('filing', 'New DRHP / RHP filing'), ('new', 'New IPO'), ('price', 'Price band announced'),
         ('anchor', 'Anchor book in'), ('close', 'Closing day + hourly subscription'), ('allot', 'Allotment day'),
         ('list', 'Listing day'), ('gmp', 'GMP move 10%+ (hourly)'), ('stale', 'Data source stopped')]
LABEL = dict(RULES)
QUIETS = ['22-8', '23-7', '21-9', 'off']


# ---------------------------------------------------------------- Telegram
def tg(method, **params):
    data = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items()}).encode()
    req = urllib.request.Request(API + method, data=data)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {'ok': False, 'description': str(e)}
    except Exception as e:
        return {'ok': False, 'description': str(e)}


def send(chat, text, kb=None):
    p = {'chat_id': chat, 'text': text[:4000], 'disable_web_page_preview': 'true'}
    if kb:
        p['reply_markup'] = {'inline_keyboard': kb}
    r = tg('sendMessage', **p)
    if not r.get('ok'):
        print('telegram send failed:', r.get('description'))
    return r.get('ok', False)


# ---------------------------------------------------------------- helpers
def hm(t):
    return t.hour * 60 + t.minute


def in_quiet(st, t):
    q = st.get('quiet', '22-8')
    if q == 'off':
        return False
    a, b = [int(x) for x in q.split('-')]
    h = t.hour
    return (a <= h or h < b) if a > b else (a <= h < b)


def short_name(n):
    return re.sub(r'\s+(Limited|Ltd\.?)\s*$', '', str(n or ''), flags=re.I).strip()


def key(n):
    n = re.sub(r'\b(limited|ltd|india|ipo|the)\b', '', str(n or '').lower())
    return re.sub(r'[^a-z0-9]', '', n)


def inr(v):
    if v is None:
        return 'NA'
    v = round(float(v), 2)
    return ('%d' % v) if v == int(v) else ('%.2f' % v)


def ddmmm(iso):
    try:
        y, m, d = [int(x) for x in iso.split('-')]
        return '%d %s' % (d, 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()[m - 1])
    except Exception:
        return iso or 'NA'


def settings_text(st):
    on = st.get('on', True)
    lines = ['⚙️ WishCo IPO Alerts — Telegram Settings',
             'Alerts: ' + ('ON ✅' if on else 'PAUSED ⏸'),
             'Quiet hours: ' + (st.get('quiet') if st.get('quiet') != 'off' else 'off') + ' (messages wait till morning)', '']
    for k, lab in RULES:
        lines.append(('✅ ' if st['rules'].get(k, True) else '❌ ') + lab)
    lines += ['', 'Tap a button to switch. The bot answers within about 15 minutes.']
    return '\n'.join(lines)


def settings_kb(st):
    kb = [[{'text': ('✅ ' if st['rules'].get(k, True) else '❌ ') + lab, 'callback_data': 'r:' + k}] for k, lab in RULES]
    kb.append([{'text': '🌙 Quiet: ' + st.get('quiet', '22-8'), 'callback_data': 'q'},
               {'text': '⏸ Pause' if st.get('on', True) else '▶️ Resume', 'callback_data': 'p'}])
    kb.append([{'text': '🔔 Send test', 'callback_data': 't'}])
    return kb


HELP = ('WishCo IPO Desk alerts\n'
        '/settings — switch alerts on/off, quiet hours, pause\n'
        '/status — what is being watched now\n'
        '/test — send a test alert\n'
        '/pause  /resume — stop or restart all alerts')


# ---------------------------------------------------------------- commands from Telegram
def commands(st, now):
    """Read new messages / button taps.  Returns list of (chat, text, kb) answers to send at once."""
    out = []
    r = tg('getUpdates', offset=st.get('offset', 0), timeout=0, allowed_updates=['message', 'callback_query'])
    if not r.get('ok'):
        print('getUpdates:', r.get('description'))
        return out
    for u in r.get('result', []):
        st['offset'] = u['update_id'] + 1
        if 'callback_query' in u:
            cq = u['callback_query']
            uid, chat = cq['from']['id'], cq['message']['chat']['id']
            tg('answerCallbackQuery', callback_query_id=cq['id'])
            if uid != st.get('owner'):
                continue
            d = cq.get('data', '')
            if d.startswith('r:') and d[2:] in LABEL:
                st['rules'][d[2:]] = not st['rules'].get(d[2:], True)
            elif d == 'q':
                q = st.get('quiet', '22-8')
                st['quiet'] = QUIETS[(QUIETS.index(q) + 1) % len(QUIETS)] if q in QUIETS else '22-8'
            elif d == 'p':
                st['on'] = not st.get('on', True)
            elif d == 't':
                out.append((chat, test_text(now), None))
                continue
            out.append((chat, settings_text(st), settings_kb(st)))
            continue
        m = u.get('message') or {}
        txt = (m.get('text') or '').strip()
        if not txt.startswith('/'):
            continue
        cmd = txt.split()[0].split('@')[0].lower()
        uid, chat = (m.get('from') or {}).get('id'), m['chat']['id']
        if cmd == '/start' and not st.get('owner'):
            st['owner'] = uid
        if uid != st.get('owner'):
            out.append((chat, 'This is a private WishCo bot.', None))
            continue
        if chat not in st['chats']:
            st['chats'].append(chat)
        if cmd == '/start':
            out.append((chat, '✅ WishCo IPO alerts are set up for this chat.\n\n' + HELP, None))
            out.append((chat, settings_text(st), settings_kb(st)))
        elif cmd in ('/settings', '/setting'):
            out.append((chat, settings_text(st), settings_kb(st)))
        elif cmd == '/test':
            out.append((chat, test_text(now), None))
        elif cmd == '/pause':
            st['on'] = False
            out.append((chat, '⏸ Alerts paused. Send /resume to start again.', None))
        elif cmd == '/resume':
            st['on'] = True
            out.append((chat, '▶️ Alerts are on again.', None))
        elif cmd == '/status':
            out.append((chat, status_text(st), None))
        elif cmd == '/stop':
            st['chats'] = [c for c in st['chats'] if c != chat]
            out.append((chat, 'This chat will get no more alerts. Send /start to add it again.', None))
        else:
            out.append((chat, HELP, None))
    return out


def test_text(now):
    return 'WishCo IPO Alert · %s\n• Test message — Telegram alerts are working.' % now.strftime('%d %b %H:%M')


def status_text(st):
    ipos = load(os.path.join(D, 'ipos.json'), {})
    act = [i for i in ipos.get('ipos', []) if i.get('status') in ('open', 'upcoming')]
    lines = ['Watching now (%s):' % (ipos.get('updated') or 'NA')]
    for i in act[:15]:
        lines.append('• %s (%s) %s · %s–%s · GMP ₹%s' % (short_name(i['name']), i.get('board'), i.get('status'),
                                                      ddmmm(i.get('open')), ddmmm(i.get('close')), inr(i.get('gmp'))))
    lines.append('Queued (quiet hours): %d' % len(st.get('queue', [])))
    return '\n'.join(lines)


# ---------------------------------------------------------------- subscription on closing day
CATS = [('QIB', r'^QIB'), ('B-HNI', r'^(bNII|b ?HNI|Big)|above'), ('S-HNI', r'^(sNII|s ?HNI|Small)|below'),
        ('NII', r'^(NII|HNI|Non.?Institutional)'), ('Retail', r'^(Retail|RII|Individual)'),
        ('Shareholder', r'^Share ?holder'), ('Employee', r'^Employee'), ('Total', r'^Total')]


def subscription(url):
    """{'QIB': 1.2, ..., 'Total': 3.4} from a Chittorgarh subscription page, first table that has the categories."""
    try:
        page = get(url)
    except Exception as e:
        print('subscription read failed:', e)
        return {}
    got = {}
    for r in rows(page):
        name = html.unescape(r[0]).strip()
        for lab, rx in CATS:
            if lab in got or not re.search(rx, name, re.I):
                continue
            v = None
            for c in r[1:3]:
                c = c.strip()
                if re.fullmatch(r'[\d,]*\.?\d+\s*x?', c, re.I):
                    v = num(c.rstrip('xX'))
                    break
            if v is not None:
                got[lab] = v
            break
    return got if 'Total' in got else {}


# ---------------------------------------------------------------- events
def events(st, now):
    ev = []          # (rule, key, text, immediate)
    today = now.date().isoformat()
    first = not st.get('seeded')
    ipos = load(os.path.join(D, 'ipos.json'), {})
    anchors = load(os.path.join(D, 'anchors.json'), {})
    filings = load(os.path.join(D, 'filings.json'), {})
    market = load(os.path.join(D, 'market.json'), {})
    snap = st.setdefault('snap', {})
    sent = st.setdefault('sent', {})

    def add(rule, k, text, now_=True):
        if k in sent:
            return
        sent[k] = today
        if not first:
            ev.append((rule, k, text, now_))

    # new DRHP / RHP filings (exchange root source)
    for f in filings.get('items', []):
        if f.get('kind') not in ('DRHP', 'RHP', 'Prospectus', 'IPO'):
            continue
        k = 'filing|' + (f.get('url') or f.get('company', '') + f.get('at', ''))
        kind = f.get('kind') if f.get('kind') != 'IPO' else 'IPO document'
        add('filing', k, '📄 %s filed: %s%s — %s' % (kind, short_name(f.get('company')),
                                                    ' (parent quota watch)' if f.get('watch') else '', (f.get('at') or '')[:10]))

    anc = {}
    for v in (anchors.get('ipos') or {}).values():
        anc[key(v.get('name'))] = v

    for i in ipos.get('ipos', []):
        n, c = short_name(i['name']), key(i['name'])
        o = snap.get(c)
        det = i.get('det') or {}
        board = 'SME' if i.get('board') == 'SME' else 'Mainboard'
        if i.get('status') in ('open', 'upcoming') and o is None:
            add('new', 'new|' + c, '🆕 New IPO: %s (%s) · opens %s · closes %s%s' % (
                n, board, ddmmm(i.get('open')), ddmmm(i.get('close')),
                (' · price ₹%s–%s' % (inr(i['low']), inr(i['high']))) if i.get('high') else ''))
        if i.get('high') and o is not None and not o.get('high'):
            lot = det.get('lot')
            add('price', 'price|' + c, '💰 %s: price band ₹%s–%s%s' % (n, inr(i.get('low')), inr(i['high']),
                                                                       (' · lot %s shares' % lot) if lot else ''))
        a = anc.get(c) or next((v for kk, v in anc.items() if kk and c and (kk.startswith(c[:12]) or c.startswith(kk[:12]))), None)
        if a and a.get('ok') and a.get('n'):
            add('anchor', 'anchor|' + c, '⚓ %s: anchor book ₹%s Cr · %s anchors · MF %s%% · insurers %s%%%s' % (
                n, inr(a.get('amt')), a.get('n'), inr(a.get('mf')), inr(a.get('ins') or 0),
                (' · ' + a['schemes']) if a.get('schemes') else ''))
        # dated events, sent on the day (from 08:00)
        if now.hour >= 8:
            if i.get('close') == today:
                add('close', 'closeday|' + c, '⏰ %s closes today (%s) · GMP ₹%s' % (n, board, inr(i.get('gmp'))))
            allot = det.get('allot')
            if allot == today:
                add('allot', 'allot|' + c, '🎯 %s: allotment today · GMP ₹%s' % (n, inr(i.get('gmp'))))
            lst = i.get('listing') or det.get('listing')
            if lst == today:
                add('list', 'list|' + c, '🔔 %s lists today · GMP ₹%s%s' % (
                    n, inr(i.get('gmp')), (' (%.1f%% on ₹%s)' % (i['gmp'] / i['high'] * 100, inr(i['high'])))
                    if i.get('high') and i.get('gmp') is not None else ''))
        # closing-day subscription, every hour 10:00-17:15
        if i.get('close') == today and 600 <= hm(now) <= 1035 and a and a.get('url'):
            slot = 'sub|%s|%s|%d' % (c, today, now.hour)
            if slot not in sent and st['rules'].get('close', True):
                s = subscription(a['url'])
                if s:
                    order = ['QIB', 'B-HNI', 'S-HNI', 'NII', 'Retail', 'Shareholder', 'Employee', 'Total']
                    if 'B-HNI' in s:
                        order.remove('NII')
                    add('close', slot, '📊 %s subscription %s — %s' % (
                        n, now.strftime('%H:%M'), ' · '.join('%s %sx' % (k, inr(s[k])) for k in order if k in s)))
                else:
                    print('subscription: no table for', n)
        # GMP move 10%+ (hourly round-up)
        g = i.get('gmp')
        if i.get('status') in ('open', 'upcoming', 'closed') and g is not None:
            ref = st.setdefault('gmp', {}).get(c)
            if ref is None:
                st['gmp'][c] = g
            elif abs(g - ref) >= max(1, abs(ref) * 0.10):
                st['gmp'][c] = g
                pct = (' · %.1f%% of ₹%s' % (g / i['high'] * 100, inr(i['high']))) if i.get('high') else ''
                add('gmp', 'gmp|%s|%s|%s' % (c, today, inr(g)), '📈 %s: GMP ₹%s → ₹%s%s' % (n, inr(ref), inr(g), pct), False)
        snap[c] = {'high': i.get('high'), 'status': i.get('status')}

    # data source stopped (07:00-23:00): IPO list not updated for 60 min, market for 90 min
    if 7 <= now.hour < 23:
        for nm, obj, mins in (('IPO list (IPO Premium)', ipos, 60), ('Market data', market, 90)):
            u = obj.get('updated') or ''
            try:
                t = time.mktime(time.strptime(u.replace(' IST', ''), '%d %b %Y, %H:%M'))
                age = (time.mktime(now.replace(tzinfo=None).timetuple()) - t) / 60
            except Exception:
                age = 0
            if age > mins:
                add('stale', 'stale|%s|%s' % (nm, today), '⚠️ %s has not updated since %s' % (nm, u))

    st['seeded'] = True
    # keep "sent" small: drop keys older than 60 days
    cut = time.strftime('%Y-%m-%d', time.localtime(time.time() - 60 * 86400))
    st['sent'] = {k: v for k, v in sent.items() if v >= cut}
    return ev


# ---------------------------------------------------------------- main
def main():
    if not TOKEN:
        print('alerts: TELEGRAM_BOT_TOKEN not set — nothing sent')
        return
    now = now_ist()
    st = load(STATE, {})
    st.setdefault('rules', {k: True for k, _ in RULES})
    for k, _ in RULES:
        st['rules'].setdefault(k, True)
    st.setdefault('chats', [])
    st.setdefault('queue', [])
    st.setdefault('quiet', '22-8')
    st.setdefault('on', True)

    for chat, text, kb in commands(st, now):
        send(chat, text, kb)

    ev = events(st, now)
    ev = [e for e in ev if st['rules'].get(e[0], True)]
    hour = now.strftime('%Y-%m-%d %H')
    for rule, k, text, immediate in ev:
        st['queue'].append({'t': text, 'now': immediate, 'h': hour})

    if not st.get('chats') or not st.get('on', True) or in_quiet(st, now):
        save(STATE, st)
        print('alerts: %d queued (chats %d, on %s, quiet %s)' % (len(st['queue']), len(st['chats']), st['on'], in_quiet(st, now)))
        return
    # immediate items go now; hourly round-up items go once the hour they were found in is over
    go = [q for q in st['queue'] if q['now'] or q['h'] != hour]
    if go:
        body = 'WishCo IPO Alert · %s\n' % now.strftime('%d %b %H:%M') + '\n'.join('• ' + q['t'] for q in go)
        if all(send(chat, body) for chat in st['chats']):
            st['queue'] = [q for q in st['queue'] if q not in go]
    save(STATE, st)
    print('alerts: %d sent, %d waiting' % (len(go), len(st['queue'])))


if __name__ == '__main__':
    main()
