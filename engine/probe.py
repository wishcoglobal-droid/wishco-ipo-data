"""Temporary check: structure of the IPO Premium home page as seen from GitHub's servers."""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
from common import get, rows, stamp, save

out = {'at': stamp()}
try:
    t = get('https://www.ipopremium.in/', timeout=25)
    out['len'] = len(t)
    out['rows'] = rows(t)[:120]
    out['links'] = sorted(set(re.findall(r'href="(https://www\.ipopremium\.in/[^"#?]*)"', t)))[:200]
    out['heads'] = re.findall(r'(?is)<thead.*?</thead>', t)[:6]
    m = re.search(r'(?is)<tbody.*?</tbody>', t)
    out['tbody'] = m.group(0)[:6000] if m else ''
    out['ajax'] = re.findall(r'(?i)(?:ajax|url)\s*:\s*["\']([^"\']+)["\']', t)[:30]
except Exception as e:
    out['err'] = str(e)[:300]
for u in ['https://www.ipopremium.in/ipo', 'https://www.ipopremium.in/view/ipo', 'https://www.ipopremium.in/ipo-list']:
    try:
        t = get(u, timeout=20)
        out[u] = {'len': len(t), 'rows': rows(t)[:40]}
    except Exception as e:
        out[u] = {'err': str(e)[:120]}
save(os.path.join(os.path.dirname(__file__), '..', 'data', 'probe.json'), out)
