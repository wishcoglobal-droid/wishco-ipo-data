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
import json, os, re, sys, html, time, uuid, tempfile, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(__file__))
from common import get, rows, num, now_ist, load, save
import cards

D = os.path.join(os.path.dirname(__file__), '..', 'data')
STATE = os.path.join(D, 'alerts_state.json')
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
API = 'https://api.telegram.org/bot%s/' % TOKEN

RULES = [('filing', 'New DRHP / RHP filing'), ('new', 'New IPO'), ('price', 'Price band announced'),
         ('anchor', 'Anchor book in'), ('close', 'Closing day + hourly subscription'), ('allot', 'Allotment day'),
         ('list', 'Listing day'), ('gmp', 'GMP move 10%+ (hourly)'), ('stale', 'Data source stopped')]
LABEL = dict(RULES)
QUIETS = ['22-8', '23-7', '21-9', 'off']

# v2 (24 Nov 2026): every alert is the app's IPO card (picture) with buttons that open the app at that IPO's panel.
APP = {'test': 'https://script.google.com/macros/s/AKfycbxsm_JHDR5GYKF87p8gSRILZksrSn3G5BbPdNrc_Q_7HYxOW-njAKD-lN8Zb-SyufM0cg/exec?ch=test',
       'live': 'https://script.google.com/macros/s/AKfycbw6fGBtj_StnGtI9gV-fLZrSDVA3BuIs0uonzr3SgrZEG0UObt5BABfSDV-m8F1kSdlag/exec?ch=live'}
PANELS = [[('Application amount', 'inv'), ('Allotment chance', 'chn'), ('Profit', 'fr')],
          [('Subscription', 'sub'), ('GMP trend', 'gmp'), ('Key facts', 'kf')],
          [('Hold score', 'fh'), ('Anchor book', 'an'), ('News & RHP', 'rhp')]]


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


def tg_photo(chat, png, caption, kb=None):
    """sendPhoto with a file upload (multipart).  Returns message dict or None."""
    b = uuid.uuid4().hex
    parts = []
    fields = {'chat_id': str(chat), 'caption': caption[:1024], 'parse_mode': 'HTML'}
    if kb:
        fields['reply_markup'] = json.dumps({'inline_keyboard': kb})
    for k, v in fields.items():
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (b, k, v)).encode())
    with open(png, 'rb') as f:
        data = f.read()
    parts.append(('--%s\r\nContent-Disposition: form-data; name="photo"; filename="card.png"\r\nContent-Type: image/png\r\n\r\n' % b).encode() + data + b'\r\n')
    parts.append(('--%s--\r\n' % b).encode())
    req = urllib.request.Request(API + 'sendPhoto', data=b''.join(parts), headers={'Content-Type': 'multipart/form-data; boundary=' + b})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            j = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read().decode())
        except Exception:
            j = {'ok': False, 'description': str(e)}
    except Exception as e:
        j = {'ok': False, 'description': str(e)}
    if not j.get('ok'):
        print('telegram photo failed:', j.get('description'))
        return None
    return j.get('result')


def send(chat, text, kb=None, parse=None):
    p = {'chat_id': chat, 'text': text[:4000], 'disable_web_page_preview': 'true'}
    if parse:
        p['parse_mode'] = parse
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
    n = re.sub(r'\s*\((mainboard|sme|ipo)\)\s*', ' ', str(n or ''), flags=re.I).strip()
    return re.sub(r'\s+(Limited|Ltd\.?)\s*$', '', n, flags=re.I).strip()


def key(n):
    n = re.sub(r'\((mainboard|sme|ipo)\)', ' ', str(n or '').lower())
    n = re.sub(r'\b(limited|ltd|india|ipo|the)\b', '', n)
    return re.sub(r'[^a-z0-9]', '', n)


def oldkey(n):
    """v1 key (kept only to carry old state over to the new key)."""
    n = re.sub(r'\b(limited|ltd|india|ipo|the)\b', '', str(n or '').lower())
    return re.sub(r'[^a-z0-9]', '', n)


def price(i):
    lo, hi = i.get('low') or 0, i.get('high') or 0
    if not hi:
        return 'price band not announced yet'
    return ('price ₹%s (fixed)' % inr(hi)) if (lo == hi or not lo) else ('price ₹%s–%s' % (inr(lo), inr(hi)))


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
        '/ipo name — the IPO card with all buttons (no name = all open IPOs)\n'
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
            if d[:3] in ('rm:', 'mu:'):
                lst = 'remind' if d[:3] == 'rm:' else 'mute'
                ipos = load(os.path.join(D, 'ipos.json'), {})
                c = next((key(i['name']) for i in ipos.get('ipos', []) if key(i['name']).startswith(d[3:])), d[3:])
                L = st.setdefault(lst, [])
                on = c not in L
                st[lst] = (L + [c]) if on else [x for x in L if x != c]
                nm = next((short_name(i['name']) for i in ipos.get('ipos', []) if key(i['name']) == c), c)
                tg('editMessageReplyMarkup', chat_id=chat, message_id=cq['message']['message_id'],
                   reply_markup={'inline_keyboard': keyboard(st, c, nm)})
                out.append((chat, ('⏰ Reminder on for %s: card on close day morning + 2 hours before close.' if lst == 'remind' and on else
                                   'Reminder off for %s.' if lst == 'remind' else
                                   '🔕 %s muted: no more alerts for this IPO.' if on else '🔔 %s: alerts on again.') % nm, None))
                continue
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
        elif cmd == '/ipo':
            q = key(txt[len(txt.split()[0]):])
            ipos = load(os.path.join(D, 'ipos.json'), {})
            hits = [i for i in ipos.get('ipos', []) if (key(i['name']).startswith(q) if q else i.get('status') == 'open')][:5]
            for i in hits:
                st.setdefault('want_cards', []).append((chat, key(i['name'])))
            if not hits:
                out.append((chat, 'No IPO found. Try: /ipo matangi   (no name = all open IPOs)', None))
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
def match_ipo(ipos, name=None, text=None):
    """Find an ipos.json row by company name, or by a name written inside a filing text."""
    L = ipos.get('ipos', [])
    if name:
        c = key(name)
        for i in L:
            if key(i['name']) == c:
                return i
        for i in L:
            k = key(i['name'])
            if k and c and len(k) >= 8 and (k.startswith(c[:10]) or c.startswith(k[:10])):
                return i
    if text:
        t = key(html.unescape(text))
        for i in L:
            k = key(i['name'])
            if len(k) >= 8 and k[:12] in t:
                return i
    return None


def events(st, now):
    ev = []          # dicts: rule, k, t (text line), e (card headline), c (IPO key), now, sub
    today = now.date().isoformat()
    first = not st.get('seeded')
    ipos = load(os.path.join(D, 'ipos.json'), {})
    anchors = load(os.path.join(D, 'anchors.json'), {})
    filings = load(os.path.join(D, 'filings.json'), {})
    market = load(os.path.join(D, 'market.json'), {})
    snap = st.setdefault('snap', {})
    sent = st.setdefault('sent', {})
    gref = st.setdefault('gmp', {})
    mute = set(st.get('mute', []))
    remind = set(st.get('remind', []))

    def add(rule, k, text, now_=True, c=None, e=None, sub=None, force=False):
        if k in sent:
            return
        sent[k] = today
        if first or (c and c in mute):
            return
        ev.append({'rule': rule, 'k': k, 't': text, 'e': e or text, 'c': c, 'now': now_, 'sub': sub, 'force': force})

    # carry v1 state (old keys kept "(mainboard)" in the key) over to the new keys, so nothing is sent twice
    for i in ipos.get('ipos', []):
        c, o = key(i['name']), oldkey(i['name'])
        if c != o:
            if o in snap and c not in snap:
                snap[c] = snap.pop(o)
            if o in gref and c not in gref:
                gref[c] = gref.pop(o)
            for kk in list(sent):
                if kk.endswith('|' + o):
                    sent[kk[:-len(o)] + c] = sent.pop(kk)

    # new DRHP / RHP filings (exchange root source) -> on the IPO's card when the IPO is in the list
    for f in filings.get('items', []):
        if f.get('kind') not in ('DRHP', 'RHP', 'Prospectus', 'IPO'):
            continue
        k = 'filing|' + (f.get('url') or f.get('company', '') + f.get('at', ''))
        comp = short_name(f.get('company'))
        when = cards.dd(f.get('at'))
        i = match_ipo(ipos, text=f.get('text')) if f.get('watch') else match_ipo(ipos, name=f.get('company'))
        if f.get('watch') and i and key(i['name']) != key(f.get('company')):
            e = '%s (parent) disclosure on this IPO · %s · SH quota watch' % (comp, when)
            t = '📄 %s (parent) disclosure on %s IPO — %s' % (comp, short_name(i['name']), when)
        else:
            kind = {'IPO': 'IPO document', 'Prospectus': 'Prospectus'}.get(f.get('kind'), f.get('kind'))
            if i and i.get('status') == 'closed' and f.get('kind') in ('Prospectus', 'RHP'):
                kind = 'Final prospectus (IPO already closed)'
            e = '%s filed · %s' % (kind, when)
            t = '📄 %s filed: %s%s — %s' % (kind, comp, ' (parent quota watch)' if f.get('watch') else '', when)
        add('filing', k, t, c=key(i['name']) if i else None, e=e)

    anc = {}
    for v in (anchors.get('ipos') or {}).values():
        anc[key(v.get('name'))] = v

    for i in ipos.get('ipos', []):
        n, c = short_name(i['name']), key(i['name'])
        o = snap.get(c)
        det = i.get('det') or {}
        board = 'SME' if i.get('board') == 'SME' else 'Mainboard'
        if i.get('status') in ('open', 'upcoming') and o is None:
            add('new', 'new|' + c, '🆕 New IPO: %s (%s) · opens %s · closes %s · %s' % (
                n, board, ddmmm(i.get('open')), ddmmm(i.get('close')), price(i)),
                c=c, e='New IPO · %s · %s' % (board, price(i)))
        if i.get('high') and o is not None and not o.get('high'):
            lot = det.get('lot')
            add('price', 'price|' + c, '💰 %s: %s%s' % (n, price(i), (' · lot %s shares' % lot) if lot else ''),
                c=c, e='Price band announced · %s' % price(i))
        a = anc.get(c) or next((v for kk, v in anc.items() if kk and c and (kk.startswith(c[:12]) or c.startswith(kk[:12]))), None)
        if a and a.get('ok') and a.get('n'):
            add('anchor', 'anchor|' + c, '⚓ %s: anchor book ₹%s Cr · %s anchors · MF %s%% · insurers %s%%%s' % (
                n, inr(a.get('amt')), a.get('n'), inr(a.get('mf')), inr(a.get('ins') or 0),
                (' · ' + a['schemes']) if a.get('schemes') else ''),
                c=c, e='Anchor book in · ₹%s Cr · %s anchors · MF %s%%' % (inr(a.get('amt')), a.get('n'), inr(a.get('mf'))))
        if now.hour >= 8:
            if i.get('close') == today:
                add('close', 'closeday|' + c, '⏰ %s closes today (%s) · GMP ₹%s' % (n, board, inr(i.get('gmp'))),
                    c=c, e='Closes today', force=c in remind)
            if det.get('allot') == today:
                add('allot', 'allot|' + c, '🎯 %s: allotment today · GMP ₹%s' % (n, inr(i.get('gmp'))), c=c, e='Allotment today')
            lst = i.get('listing') or det.get('listing')
            if lst == today:
                add('list', 'list|' + c, '🔔 %s lists today · GMP ₹%s' % (n, inr(i.get('gmp'))), c=c, e='Lists today')
        if c in remind and i.get('close') == today and hm(now) >= 870:
            add('close', 'remind|' + c, '⏰ %s closes in about 2 hours' % n, c=c, e='Reminder · closes in about 2 hours', force=True)
        # closing-day subscription, every hour 10:00-17:15
        if i.get('close') == today and 600 <= hm(now) <= 1035 and a and a.get('url'):
            slot = 'sub|%s|%s|%d' % (c, today, now.hour)
            if slot not in sent and (st['rules'].get('close', True) or c in remind):
                s = subscription(a['url'])
                if s:
                    order = ['QIB', 'B-HNI', 'S-HNI', 'NII', 'Retail', 'Shareholder', 'Employee', 'Total']
                    if 'B-HNI' in s:
                        order.remove('NII')
                    add('close', slot, '📊 %s subscription %s — %s' % (
                        n, now.strftime('%H:%M'), ' · '.join('%s %sx' % (k, inr(s[k])) for k in order if k in s)),
                        c=c, e='Subscription %s · total %sx' % (now.strftime('%H:%M'), inr(s.get('Total'))), sub=s, force=c in remind)
                else:
                    print('subscription: no table for', n)
        # GMP move 10%+ (hourly round-up)
        g = i.get('gmp')
        if i.get('status') in ('open', 'upcoming', 'closed') and g is not None:
            ref = gref.get(c)
            if ref is None:
                gref[c] = g
            elif abs(g - ref) >= max(1, abs(ref) * 0.10):
                gref[c] = g
                pct = (' · %.1f%% of ₹%s' % (g / i['high'] * 100, inr(i['high']))) if i.get('high') else ''
                add('gmp', 'gmp|%s|%s|%s' % (c, today, inr(g)), '📈 %s: GMP ₹%s → ₹%s%s' % (n, inr(ref), inr(g), pct), False,
                    c=c, e='GMP ₹%s → ₹%s' % (inr(ref), inr(g)))
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
    cut = time.strftime('%Y-%m-%d', time.localtime(time.time() - 60 * 86400))
    st['sent'] = {k: v for k, v in sent.items() if v >= cut}
    return ev


# ---------------------------------------------------------------- cards
def fact_line(i, ex, a, lines, ipos_all):
    det = i.get('det') or {}
    parts = []
    if not i.get('high'):
        parts.append('Price band, lot and issue size not announced yet; a price-band alert comes when they are.')
    if ex and (ex.get('fin') or {}).get('fresh') == 0:
        parts.append('100% OFS: the money goes to the selling shareholder, not the company.')
    if any('parent' in x for x in lines):
        parts.append('Shareholder quota for the parent company\'s shareholders.')
    if any('Final prospectus' in x for x in lines):
        parts.append('IPO closed; final prospectus filed before listing on %s.' % cards.dd(i.get('listing')))
    m = (det.get('mins') or {}).get('r')
    if i.get('board') == 'SME' and m:
        parts.append('SME%s · %s minimum %d lots = %s · allotment by lottery.' % (
            ' fixed price' if (i.get('low') == i.get('high')) else '', m.get('label', 'Individual'), m['lots'], cards.inr(m['amount'])))
    if a and a.get('ok') and a.get('n'):
        parts.append('Anchor %s Cr · %s anchors · Indian MF %s%%.' % (cards.inr(a.get('amt')), a.get('n'), inr(a.get('mf'))))
    return ' '.join(parts[:2])


def keyboard(st, c, name):
    base = APP.get(st.get('app', 'test'), APP['test'])
    u = lambda p: base + '&ipo=' + urllib.parse.quote(c) + '&p=' + p
    kb = [[{'text': '📱 Open full card in app', 'web_app': {'url': u('detail')}}]]
    for row in PANELS:
        kb.append([{'text': lab, 'web_app': {'url': u(p)}} for lab, p in row])
    cc = c[:40]
    kb.append([{'text': ('✅ Reminder on' if c in st.get('remind', []) else '⏰ Remind on close day'), 'callback_data': 'rm:' + cc},
               {'text': ('🔔 Unmute' if c in st.get('mute', []) else '🔕 Mute this IPO'), 'callback_data': 'mu:' + cc}])
    return kb


def send_card(st, chat, i, lines, sub=None):
    """One IPO card picture + buttons.  Falls back to text when the picture can't be made."""
    ipos = load(os.path.join(D, 'ipos.json'), {})
    anchors = load(os.path.join(D, 'anchors.json'), {})
    extra = load(os.path.join(D, 'extra.json'), {})
    c, name = key(i['name']), short_name(i['name'])
    a = next((v for v in (anchors.get('ipos') or {}).values() if key(v.get('name')) == c or
              (key(v.get('name'))[:12] and c.startswith(key(v.get('name'))[:12]))), None)
    ex = next((v for v in (extra.get('ipos') or {}).values() if key(v.get('name'))[:10] == c[:10]), None)
    fact = fact_line(i, ex, a, lines, ipos)
    page = cards.card_html(i, name, lines, now_ist().date().isoformat(), sub=sub, anchor=a, extra=ex, fact=fact,
                           data_time=(ipos.get('updated') or '').replace(' 2026,', '').replace(' IST', ''))
    png = os.path.join(tempfile.mkdtemp(), 'card.png')
    cap = '<b>%s</b>\n%s' % (html.escape(name), '\n'.join('• ' + html.escape(x) for x in lines))
    kb = keyboard(st, c, name)
    if cards.render(page, png) and tg_photo(chat, png, cap, kb):
        return True
    return send(chat, cap + '\n' + html.escape(price(i)), kb, parse='HTML')


def deliver(st, items, now):
    """items = queue dicts.  Many items: one short list first, then one card per IPO."""
    ipos = load(os.path.join(D, 'ipos.json'), {})
    byc, loose, order = {}, [], []
    for q in items:
        c = q.get('c')
        if not c:   # v1 queue item: find the IPO from the text
            hit = next((i for i in ipos.get('ipos', []) if short_name(i['name']) and short_name(i['name']) in q['t']), None)
            c = key(hit['name']) if hit else None
            if hit and not q.get('e'):
                q['e'] = q['t'].split(': ', 1)[-1] if ': ' in q['t'] else q['t']
        row = next((i for i in ipos.get('ipos', []) if key(i['name']) == c), None) if c else None
        if row is None:
            loose.append(q['t'])
            continue
        if c not in byc:
            byc[c] = {'i': row, 'lines': [], 'sub': None}
            order.append(c)
        byc[c]['lines'].append(q.get('e') or q['t'])
        byc[c]['sub'] = q.get('sub') or byc[c]['sub']
    ok = True
    for chat in st['chats']:
        if len(items) > 1 or loose:
            head = 'WishCo IPO Alert · %s — %d update%s' % (now.strftime('%d %b %H:%M'), len(items), '' if len(items) == 1 else 's')
            body = [head] + ['• %s — %s' % (short_name(byc[c]['i']['name']), '; '.join(byc[c]['lines'])) for c in order] + ['• ' + t for t in loose]
            ok = send(chat, '\n'.join(body)) and ok
        for c in order:
            ok = send_card(st, chat, byc[c]['i'], byc[c]['lines'], byc[c]['sub']) is not False and ok
    return ok


def sample(st, now):
    """One-time sample of the new cards (24 Nov 2026), so the owner can test the buttons at once."""
    ipos = load(os.path.join(D, 'ipos.json'), {})
    want = [('encubeethicals', 'New IPO · Mainboard · dates tentative'), ('airprotechnology', 'New IPO · SME · fixed price'),
            ('crystalcropprotection', 'Final prospectus (IPO already closed) filed · 23 Nov'),
            ('mahanadicoalfields', 'Coal India (parent) disclosure on this IPO · 24 Nov · SH quota watch'),
            ('shreesiddhivinayakgreentechindustries', 'GMP ₹10 → ₹20 · opens tomorrow')]
    items = []
    for c, e in want:
        if any(key(i['name']) == c for i in ipos.get('ipos', [])):
            items.append({'t': e, 'e': e, 'c': c, 'now': True})
    done = {c for c, _ in want}
    st['queue'] = [q for q in st.get('queue', []) if q.get('c') or not any(
        short_name(i['name']) in q['t'] for i in ipos.get('ipos', []) if key(i['name']) in done)]
    for chat in st['chats']:
        send(chat, '🧪 TEST · new WishCo IPO alert cards\nEvery alert now comes as the app\'s IPO card. The buttons open the '
                   'IPO Desk app (TEST v3.11.16) right on that IPO\'s panel. First time only: sign in with your email code inside Telegram.')
    return deliver(st, items, now)


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
    st.setdefault('mute', [])
    st.setdefault('remind', [])
    st.setdefault('app', 'test')

    for chat, text, kb in commands(st, now):
        send(chat, text, kb)
    for chat, c in st.pop('want_cards', []):
        ipos = load(os.path.join(D, 'ipos.json'), {})
        row = next((i for i in ipos.get('ipos', []) if key(i['name']) == c), None)
        if row:
            send_card(st, chat, row, ['On request · %s' % now.strftime('%d %b %H:%M')])

    if st.get('chats') and not st.get('v2'):
        if sample(st, now):
            st['v2'] = now.strftime('%Y-%m-%d %H:%M')

    ev = events(st, now)
    ev = [e for e in ev if st['rules'].get(e['rule'], True) or e.get('force')]
    hour = now.strftime('%Y-%m-%d %H')
    for e in ev:
        st['queue'].append({'t': e['t'], 'e': e['e'], 'c': e['c'], 'now': e['now'], 'h': hour, 'sub': e.get('sub')})

    if not st.get('chats') or not st.get('on', True) or in_quiet(st, now):
        save(STATE, st)
        print('alerts: %d queued (chats %d, on %s, quiet %s)' % (len(st['queue']), len(st['chats']), st['on'], in_quiet(st, now)))
        return
    go = [q for q in st['queue'] if q['now'] or q['h'] != hour]
    if go and deliver(st, go, now):
        st['queue'] = [q for q in st['queue'] if q not in go]
    save(STATE, st)
    print('alerts: %d sent, %d waiting' % (len(go), len(st['queue'])))


if __name__ == '__main__':
    main()
