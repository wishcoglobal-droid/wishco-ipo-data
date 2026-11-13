"""One-off check: which IPO sources answer from GitHub's servers. Writes data/probe.json (first part of each answer)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from common import get, stamp, save

URLS = [
    'https://www.ipopremium.in/',
    'https://ipopremium.in/ipo',
    'https://www.investorgain.com/report/live-ipo-gmp/331/',
    'https://webnodejs.investorgain.com/cloud/report/data-read/331/1/11/2026/2026-27/0/all',
    'https://www.chittorgarh.com/report/ipo-subscription-status-live-bidding-data-bse-nse/21/',
    'https://webnodejs.chittorgarh.com/cloud/report/data-read/21/1/11/2026/2026-27/0/0',
    'https://webnodejs.chittorgarh.com/cloud/report/data-read/82/1/11/2026/2026-27/0/0',
    'https://www.chittorgarh.com/report/mainboard-ipo-list-in-india-bse-nse/83/',
    'https://www.nseindia.com/api/ipo-current-issue',
    'https://www.bseindia.com/markets/PublicIssues/IPOIssues_new.aspx?id=1&Type=p',
]
out = {'at': stamp(), 'r': []}
for u in URLS:
    try:
        t = get(u, timeout=20)
        out['r'].append({'url': u, 'ok': True, 'len': len(t), 'head': t[:1500]})
    except Exception as e:
        out['r'].append({'url': u, 'ok': False, 'err': str(e)[:200]})
save(os.path.join(os.path.dirname(__file__), '..', 'data', 'probe.json'), out)
print('\n'.join('%s  %s' % (x['url'], x.get('len') or x.get('err')) for x in out['r']))
