"""Temporary check: public pages that publish grey-market Kostak and Subject-to-Sauda rates. Plain page reads only."""
import sys, os, re, json
sys.path.insert(0, os.path.dirname(__file__))
from common import get, rows, stamp, save, load

out = {'at': stamp(), 'r': {}}
ip = load(os.path.join(os.path.dirname(__file__), '..', 'data', 'ipos.json'), {}).get('ipos', [])
urls = [('ipowatch', 'https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/'),
        ('investorgain_gmp', 'https://www.investorgain.com/report/live-ipo-gmp/331/')]
for x in ip:
    if x.get('status') in ('open', 'upcoming') and x.get('url'):
        urls.append(('ipp_' + re.sub(r'\W+', '', x['name'])[:12], x['url']))
for name, u in urls[:6]:
    try:
        t = get(u, timeout=25)
        rs = rows(t)
        hit = [r[:9] for r in rs if re.search(r'(?i)kostak|sauda|subject', ' '.join(r))][:6]
        idx = [i for i, r in enumerate(rs) if re.search(r'(?i)kostak|sauda|subject', ' '.join(r))]
        near = [r[:9] for r in rs[idx[0]:idx[0] + 8]] if idx else []
        out['r'][name] = {'len': len(t), 'nrows': len(rs), 'hit': hit, 'near': near, 'first': [r[:9] for r in rs[:4]]}
    except Exception as e:
        out['r'][name] = {'err': str(e)[:200]}
save(os.path.join(os.path.dirname(__file__), '..', 'data', 'probe.json'), out)
