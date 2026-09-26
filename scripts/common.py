import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
MANUAL = ROOT / "data" / "manual"
CHARTS = ROOT / "charts"
for p in (RAW, PROCESSED, MANUAL, CHARTS):
    p.mkdir(parents=True, exist_ok=True)

UA = "ai-deflation-check research script (pvijeh@gmail.com)"
SESSION = requests.Session()
SESSION.headers["User-Agent"] = UA


def get(url, retries=4, timeout=90, **kw):
    last = None
    for i in range(retries):
        try:
            r = SESSION.get(url, timeout=timeout, **kw)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"{r.status_code} {url}")
            if r.status_code in (404, 400):
                raise last
        except (requests.RequestException, RuntimeError) as e:
            last = e
        time.sleep(2 * (i + 1))
    raise last


def get_json(url, **kw):
    return get(url, **kw).json()


def dump_json(obj, path):
    Path(path).write_text(json.dumps(obj, indent=1, sort_keys=True))


def wayback_snapshots(url, collapse="timestamp:6"):
    """Return list of (timestamp, original_url) 200-OK snapshots from the Internet Archive CDX index."""
    cdx = (
        "https://web.archive.org/cdx/search/cdx?url="
        + url
        + f"&output=json&fl=timestamp,original&filter=statuscode:200&collapse={collapse}"
    )
    rows = get_json(cdx, timeout=180)
    return [(r[0], r[1]) for r in rows[1:]]


def wayback_fetch(ts, url):
    return get(f"https://web.archive.org/web/{ts}id_/{url}", timeout=180)
