"""Shared helpers. Standard library only."""
import gzip, json, re, urllib.request, datetime, os

UA = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
    'Accept': 'text/html,application/json;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-IN,en;q=0.9',
    'Accept-Encoding': 'gzip',
}
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def get(url, headers=None, timeout=25):
    h = dict(UA); h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
        if r.headers.get('Content-Encoding') == 'gzip':
            b = gzip.decompress(b)
        return b.decode('utf-8', 'replace')


def rows(html):
    """HTML tables -> list of rows (list of cell texts)."""
    h = re.sub(r'(?is)<script.*?</script>|<style.*?</style>', '', html)
    h = re.sub(r'(?i)</(td|th)>', '\x01', h)
    h = re.sub(r'(?i)</tr>', '\x02', h)
    h = re.sub(r'(?i)<br\s*/?>', ' ', h)
    h = re.sub(r'<[^>]+>', '', h).replace('&nbsp;', ' ').replace('&amp;', '&')
    out = []
    for r in h.split('\x02'):
        c = [re.sub(r'\s+', ' ', x).strip() for x in r.split('\x01')]
        c = [x for x in c if x != '']
        if len(c) > 1:
            out.append(c)
    return out


def num(s):
    if s is None:
        return None
    t = re.sub(r'[,₹\s%+]', '', str(s)).replace('−', '-').replace('–', '-')
    try:
        v = float(t)
    except ValueError:
        return None
    return v if v == v and abs(v) != float('inf') else None


def now_ist():
    return datetime.datetime.now(IST)


def stamp():
    return now_ist().strftime('%d %b %Y, %H:%M') + ' IST'


def r2(v):
    return round(v * 100) / 100


def load(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write('\n')
