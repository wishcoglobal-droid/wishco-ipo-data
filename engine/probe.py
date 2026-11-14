"""Temporary check: official IPO sources (NSE, BSE, SEBI) as seen from GitHub's servers. Plain public pages only."""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
from common import get, rows, stamp, save

URLS = [
    ('nse_upcoming', 'https://www.nseindia.com/api/all-upcoming-issues?category=ipo', {'Accept': 'application/json', 'Referer': 'https://www.nseindia.com/market-data/all-upcoming-issues-ipo'}),
    ('nse_current', 'https://www.nseindia.com/api/ipo-current-issue', {'Accept': 'application/json', 'Referer': 'https://www.nseindia.com/market-data/all-upcoming-issues-ipo'}),
    ('nse_sme_upcoming', 'https://www.nseindia.com/api/all-upcoming-issues?category=sme', {'Accept': 'application/json'}),
    ('bse_page', 'https://www.bseindia.com/markets/PublicIssues/IPOIssues_new.aspx?id=1&Type=p', {}),
    ('bse_forth', 'https://www.bseindia.com/publicissue.html', {}),
    ('sebi_rhp', 'https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid=11', {}),
    ('sebi_drhp', 'https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid=10', {}),
    ('sebi_final', 'https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid=12', {}),
    ('chittorgarh_mcl', 'https://www.chittorgarh.com/ipo/mahanadi-coalfields-ipo/3247/', {}),
]
out = {'at': stamp(), 'r': {}}
for name, u, h in URLS:
    try:
        t = get(u, h, timeout=25)
        o = {'len': len(t), 'head': t[:2500]}
        if t.lstrip()[:1] not in '[{':
            rs = rows(t)
            o['rows'] = [r[:8] for r in rs[:25]]
            o['mcl'] = [t[max(0, m.start() - 200):m.start() + 500] for m in re.finditer(r'(?i)mahanadi', t)][:3]
            o['apis'] = sorted(set(re.findall(r'https://api\.bseindia\.com/[A-Za-z0-9_/.?=&%-]+', t)))[:20]
        out['r'][name] = o
    except Exception as e:
        out['r'][name] = {'err': str(e)[:200]}
save(os.path.join(os.path.dirname(__file__), '..', 'data', 'probe.json'), out)
