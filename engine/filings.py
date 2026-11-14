"""IPO filings straight from the stock exchange  ->  data/filings.json
Source: NSE's public RSS feeds (company announcements and offer documents). This is where a listed parent first tells
the market that a subsidiary's DRHP / RHP is filed, and where offer documents first appear.
The feed holds only the latest ~180 announcements, so every hit is kept in the file (60 days) and never lost."""
import re, sys, os, html, json, datetime
sys.path.insert(0, os.path.dirname(__file__))
from common import get, stamp, load, save, now_ist, IST

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, '..', 'data', 'filings.json')
FEEDS = [('NSE announcements', 'https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml'),
         ('NSE offer documents', 'https://nsearchives.nseindia.com/content/RSS/Offer_Documents.xml')]
KEY = re.compile(r'(?i)red\s+herring|\bD?RHP\b|\bprospectus\b|initial\s+public\s+off|\bIPO\b|price\s+band|anchor\s+invest')
SKIP = re.compile(r'(?i)\bCP-NI\b|commercial paper|disclosure document|information memorandum|\bNCD\b|debenture|rights issue|\bQIP\b|buy-?back|mutual fund|scheme')


def tag(x, name):
    m = re.search(r'(?is)<%s[^>]*>(.*?)</%s>' % (name, name), x)
    if not m:
        return ''
    t = re.sub(r'(?s)<!\[CDATA\[(.*?)\]\]>', r'\1', m.group(1))
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', t))).strip()


def when(s):
    for f in ('%d-%b-%Y %H:%M:%S', '%d-%b-%Y', '%a, %d %b %Y %H:%M:%S %Z'):
        try:
            return datetime.datetime.strptime(s.strip(), f).replace(tzinfo=IST)
        except Exception:
            pass
    return None


def kind(t):
    m = re.search(r'has filled\s+(\S+)\s+for its IPO', t)
    if m:
        c = m.group(1).upper()
        return 'DRHP' if 'DRHP' in c else 'RHP' if 'RHP' in c else 'Prospectus' if c.startswith('PROSP') else 'Advertisement' if c.startswith('ADV') else c[:14]
    if re.search(r'(?i)draft\s+red\s+herring|\bDRHP\b', t):
        return 'DRHP'
    if re.search(r'(?i)red\s+herring|\bRHP\b', t):
        return 'RHP'
    if re.search(r'(?i)price\s+band', t):
        return 'Price band'
    if re.search(r'(?i)anchor', t):
        return 'Anchor'
    return 'IPO'


def main():
    old = load(OUT, {})
    items = {x['url'] + '|' + x['text'][:60]: x for x in (old.get('items') or []) if x.get('company')}
    for x in items.values():
        x['kind'] = kind(x['company'] + ' ' + x['text'])
    parents = [p.lower() for p in load(os.path.join(HERE, 'watch.json'), {}).get('parents', [])]
    log, seen = [], {}
    for src, url in FEEDS:
        try:
            t = get(url, {'Accept': 'application/rss+xml, application/xml, text/xml'}, timeout=30)
        except Exception as e:
            log.append('%s: %s' % (src, e))
            continue
        its = re.findall(r'(?is)<item>(.*?)</item>', t)
        seen[src] = len(its)
        for x in its:
            co, link, desc, pub = tag(x, 'title'), tag(x, 'link'), tag(x, 'description'), tag(x, 'pubDate')
            text = re.sub(r'\s*\|\s*SUBJECT:.*$', '', desc).strip() or co
            both = co + ' ' + desc
            if not co or not KEY.search(both) or SKIP.search(both):
                continue
            d = when(pub)
            it = {'at': d.strftime('%Y-%m-%d %H:%M') if d else '', 'company': co, 'text': text[:300], 'url': link,
                  'kind': kind(both), 'src': src, 'watch': any(p in co.lower() for p in parents)}
            items.setdefault(link + '|' + text[:60], it)
    cut = (now_ist() - datetime.timedelta(days=60)).strftime('%Y-%m-%d')
    out = sorted([x for x in items.values() if not x['at'] or x['at'][:10] >= cut], key=lambda x: x['at'], reverse=True)[:300]
    save(OUT, {'updated': stamp(), 'src': 'nseindia.com RSS', 'feed_items': seen, 'log': log, 'items': out})
    print('filings: %d kept, feeds %s %s' % (len(out), seen, log))


if __name__ == '__main__':
    main()
