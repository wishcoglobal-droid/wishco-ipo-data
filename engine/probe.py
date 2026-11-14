"""Temporary check: the stock exchanges' public RSS feeds of company announcements, as seen from GitHub's servers."""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
from common import get, stamp, save

FEEDS = [
    ('nse_announcements', 'https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml'),
    ('nse_offer_docs', 'https://nsearchives.nseindia.com/content/RSS/Offer_Documents.xml'),
    ('bse_notices', 'https://www.bseindia.com/data/xml/notices.xml'),
]
out = {'at': stamp(), 'r': {}}
for name, u in FEEDS:
    try:
        t = get(u, {'Accept': 'application/rss+xml, application/xml, text/xml'}, timeout=30)
        items = re.findall(r'(?is)<item>(.*?)</item>', t)
        o = {'len': len(t), 'items': len(items), 'head': t[:600]}
        o['first'] = [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' | ', x))[:300] for x in items[:3]]
        o['hits'] = [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' | ', x))[:500] for x in items if re.search(r'(?i)red herring|prospectus|coal india|mahanadi|initial public', x)][:12]
        out['r'][name] = o
    except Exception as e:
        out['r'][name] = {'err': str(e)[:200]}
save(os.path.join(os.path.dirname(__file__), '..', 'data', 'probe.json'), out)
