"""Pull public incident histories for GitHub, Datadog, Cloudflare, Google Cloud and AWS.

Sources (all public, no auth):
  GitHub, Datadog  statuspage.io  /history.json?page=N  (3 months per page, back to 2017/2018)
  Cloudflare       /api/v3/history?type=incident&per_page=100&cursor=...  (own API since 2025)
  Google Cloud     status.cloud.google.com/incidents.json is a rolling window; we union
                   Internet Archive snapshots of it back to 2019 and dedupe by incident id
  AWS              old status.aws.amazon.com/data.json had an `archive` list; union Internet
                   Archive snapshots (2018-2023). The current Health Dashboard only exposes
                   events in progress, so AWS ends where the old dashboard was retired.

Output: data/processed/incidents.csv  (provider,id,name,impact,start,end,duration_min,source)
"""
import gzip
import json
import re
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

from common import PROCESSED, RAW, dump_json, get_json, wayback_fetch, wayback_snapshots

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


# ---------------------------------------------------------------- statuspage.io (GitHub, Datadog)
def statuspage_history(host, provider, max_pages=60):
    rows = []
    seen = set()
    for page in range(1, max_pages + 1):
        d = get_json(f"https://{host}/history.json?page={page}")
        months = d.get("months") or []
        if not months:
            break
        for m in months:
            year = m["year"]
            for inc in m["incidents"]:
                if inc["code"] in seen:
                    continue
                seen.add(inc["code"])
                start, end = parse_statuspage_ts(inc["timestamp"], year)
                rows.append(dict(provider=provider, id=inc["code"], name=inc["name"],
                                 impact=inc["impact"], start=start, end=end, source=host))
        print(provider, page, months[-1]["name"], months[-1]["year"], len(rows), file=sys.stderr)
    dump_json(rows, RAW / f"{provider}_incidents.json")
    return rows


TS_RE = re.compile(r"([A-Z][a-z]{2}) (\d+), (\d{2}:\d{2}) - (?:([A-Z][a-z]{2}) (\d+), )?(\d{2}:\d{2}) ([A-Z]{2,4})")


def parse_statuspage_ts(s, year):
    s = re.sub(r"<[^>]+>", "", s)
    m = TS_RE.search(s)
    if not m:
        return None, None
    m1, d1, t1, m2, d2, t2, tz = m.groups()
    off = timedelta(hours=TZ_OFFSET_H.get(tz, 0))
    start = datetime(year, MONTHS[m1], int(d1), *map(int, t1.split(":")), tzinfo=timezone.utc) - off
    if m2:
        y2 = year + 1 if MONTHS[m2] < MONTHS[m1] else year
        end = datetime(y2, MONTHS[m2], int(d2), *map(int, t2.split(":")), tzinfo=timezone.utc) - off
    else:
        end = datetime(year, MONTHS[m1], int(d1), *map(int, t2.split(":")), tzinfo=timezone.utc) - off
    return start.isoformat(), end.isoformat()


TZ_OFFSET_H = {"UTC": 0, "EDT": -4, "EST": -5, "PDT": -7, "PST": -8, "CDT": -5, "CST": -6}


# ---------------------------------------------------------------- Cloudflare
def cloudflare_history():
    rows, cursor, seen = [], None, set()
    while True:
        url = "https://www.cloudflarestatus.com/api/v3/history?type=incident&per_page=100"
        if cursor:
            url += f"&cursor={cursor}"
        d = get_json(url)
        for inc in d["result"]:
            if inc["id"] in seen:
                continue
            seen.add(inc["id"])
            rows.append(dict(provider="cloudflare", id=inc["id"], name=inc["name"], impact=inc["impact"],
                             start=inc.get("starts_at") or inc["created_at"],
                             end=inc.get("ends_at") or inc.get("resolved_at") or inc["updated_at"],
                             source="cloudflarestatus.com/api/v3"))
        cursor = (d.get("result_info") or {}).get("next_cursor")
        print("cloudflare", len(rows), rows[-1]["start"] if rows else None, file=sys.stderr)
        if not cursor or not d["result"]:
            break
    dump_json(rows, RAW / "cloudflare_incidents.json")
    return rows


# ---------------------------------------------------------------- Google Cloud (Wayback union)
def gcp_history():
    url = "https://status.cloud.google.com/incidents.json"
    snaps = [s for s in wayback_snapshots(url, collapse="timestamp:6") if s[0] >= "2019"]
    # the file is a rolling window of only a few months, so take a snapshot every ~2 months;
    # if one is truncated in the archive, fall through to the next available one
    by_id, last = {}, ""
    for ts, _ in snaps:
        if last and int(ts[:6]) - int(last[:6]) < 2:
            continue
        try:
            data = wayback_fetch(ts, url).json()
        except Exception as e:  # noqa: BLE001
            print("gcp snapshot failed", ts, e, file=sys.stderr)
            continue
        last = ts
        for inc in data:
            key = inc.get("id") or inc.get("number")
            by_id[key] = inc
        print("gcp", ts, len(data), "total", len(by_id), file=sys.stderr)
    for inc in get_json(url):
        by_id[inc.get("id") or inc.get("number")] = inc
    dump_json(list(by_id.values()), RAW / "gcp_incidents_raw.json")
    rows = []
    for inc in by_id.values():
        rows.append(dict(provider="gcp", id=str(inc.get("id") or inc.get("number")),
                         name=(inc.get("external_desc") or "")[:200],
                         impact=(inc.get("severity") or inc.get("status_impact") or "").lower(),
                         start=inc.get("begin"), end=inc.get("end"),
                         source="status.cloud.google.com/incidents.json via web.archive.org"))
    dump_json(rows, RAW / "gcp_incidents.json")
    return rows


# ---------------------------------------------------------------- AWS (Wayback union of old dashboard)
def aws_history():
    url = "https://status.aws.amazon.com/data.json"
    snaps = [s for s in wayback_snapshots(url, collapse="timestamp:6") if "2016" <= s[0] < "2024"]
    by_key = {}
    for ts, _ in snaps:
        try:
            r = wayback_fetch(ts, url)
            raw = r.content
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            data = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            print("aws snapshot failed", ts, e, file=sys.stderr)
            continue
        arch = data.get("archive") or []
        for ev in arch:
            key = (ev.get("service"), ev.get("date"))
            by_key[key] = ev
        print("aws", ts, len(arch), "total", len(by_key), file=sys.stderr)
    dump_json(list(by_key.values()), RAW / "aws_incidents_raw.json")
    rows = []
    for ev in by_key.values():
        start = datetime.fromtimestamp(int(ev["date"]), tz=timezone.utc)
        rows.append(dict(provider="aws", id=f"{ev.get('service')}:{ev.get('date')}",
                         name=f"{ev.get('service_name')}: {ev.get('summary')}",
                         impact={1: "informational", 2: "degraded", 3: "disruption"}.get(
                             ev.get("status"), str(ev.get("status"))),
                         start=start.isoformat(), end=None,
                         source="status.aws.amazon.com/data.json via web.archive.org"))
    dump_json(rows, RAW / "aws_incidents.json")
    return rows


def cached(provider, fn):
    """Re-download only with --refresh; otherwise reuse data/raw/<provider>_incidents.json."""
    path = RAW / f"{provider}_incidents.json"
    if path.exists() and "--refresh" not in sys.argv:
        return json.loads(path.read_text())
    return fn()


def main():
    which = [a for a in sys.argv[1:] if not a.startswith("--")] or ["github", "datadog", "cloudflare", "gcp", "aws"]
    rows = []
    if "github" in which:
        rows += cached("github", lambda: statuspage_history("www.githubstatus.com", "github"))
    if "datadog" in which:
        rows += cached("datadog", lambda: statuspage_history("status.datadoghq.com", "datadog"))
    if "cloudflare" in which:
        rows += cached("cloudflare", cloudflare_history)
    if "gcp" in which:
        rows += cached("gcp", gcp_history)
    if "aws" in which:
        rows += cached("aws", aws_history)
    df = pd.DataFrame(rows)
    df["start"] = pd.to_datetime(df["start"], utc=True, errors="coerce", format="ISO8601")
    df["end"] = pd.to_datetime(df["end"], utc=True, errors="coerce", format="ISO8601")
    df["duration_min"] = (df["end"] - df["start"]).dt.total_seconds() / 60
    out = PROCESSED / "incidents.csv"
    if len(which) < 5 and out.exists():  # partial refresh: keep other providers
        old = pd.read_csv(out, parse_dates=["start", "end"])
        df = pd.concat([old[~old.provider.isin(which)], df])
    df.sort_values(["provider", "start"]).to_csv(out, index=False)
    print(df.groupby("provider").agg(n=("id", "count"), first=("start", "min"), last=("start", "max")))


if __name__ == "__main__":
    main()
