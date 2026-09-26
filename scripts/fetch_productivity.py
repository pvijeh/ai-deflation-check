"""Difference-based productivity tests: does AI show up where it should, relative to where it shouldn't?

Three panels, all designed so both sides face the same macro shocks (rates, tariffs, commodities):
  1. BLS labor productivity by detailed industry (output per hour, real): AI-exposed vs unexposed.
  2. BLS producer price indexes: AI-exposed service industries vs unexposed, as ratios.
  3. OECD real GDP per hour worked: US (heavy AI capex) vs euro area, UK, Japan, Germany, Canada.

Sources: BLS public API v1 (no key), OECD SDMX (DSD_PDB@DF_PDB). Government-produced series; see FINDINGS.
"""
import io
import sys

import pandas as pd

from common import PROCESSED, RAW, SESSION, dump_json, get

BLS_API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"

# BLS industry labor productivity, index 2017=100, annual. Exposure = share of work that is
# reading/writing/analysis/code (judgement call, listed so it can be argued with).
PRODUCTIVITY = {
    "exposed": {
        "IPUJN5112__L000000000": "Software publishers",
        "IPUKN52211_L000000000": "Commercial banking",
        "IPUMN541211L000000000": "CPA offices",
        "IPUMN541213L000000000": "Tax preparation",
        "IPUMN54131_L000000000": "Architectural services",
        "IPUMN54133_L000000000": "Engineering services",
        "IPUMN54181_L000000000": "Advertising agencies",
        "IPUPN56131_L000000000": "Employment placement",
        "IPUPN5615__L000000000": "Travel agencies",
        "IPUJN511___L000000000": "Publishing (ex internet)",
    },
    "unexposed": {
        "IPUIN484___L000000000": "Truck transportation",
        "IPUTN7225__L000000000": "Restaurants",
        "IPUTN721___L000000000": "Accommodation",
        "IPUUN8111__L000000000": "Auto repair",
        "IPUHN4451__L000000000": "Grocery stores",
        "IPUCN2211__L000000000": "Electric power",
        "IPUIN493___L000000000": "Warehousing",
        "IPUIN492___L000000000": "Couriers",
        "IPUHN447___L000000000": "Gasoline stations",
        "IPUHN441___L000000000": "Motor vehicle dealers",
    },
}

# BLS PPI (what sellers receive), monthly, by industry.
PPI = {
    "exposed": {
        "PCU511210511210": "Software publishers",
        "PCU518210518210": "Data processing & hosting",
        "PCU541211541211": "CPA offices",
        "PCU54111-54111-": "Law offices",
        "PCU54161-54161-": "Management consulting",
        "PCU54133-54133-": "Engineering services",
        "PCU541810541810": "Advertising agencies",
        "PCU5613--5613--": "Employment services",
    },
    "unexposed": {
        "PCU484---484---": "Truck transportation",
        "PCU7211--7211--": "Hotels",
        "PCU622---622---": "Hospitals",
        "PCU2211--2211--": "Electric power",
        "PCU5241--5241--": "Insurance carriers",
    },
}

OECD_URL = (
    "https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_PDB@DF_PDB,2.0/"
    "{areas}.A.GDPHRS._T.XDC_H.LR.N._Z._Z?startPeriod=2010&dimensionAtObservation=AllDimensions"
)
OECD_AREAS = ["USA", "EA20", "GBR", "JPN", "DEU", "FRA", "CAN"]


def bls(series_ids, windows=((2007, 2016), (2017, 2026))):
    """BLS API v1: no key, max 25 series and 10 years per call, 25 calls/day."""
    out = []
    for i in range(0, len(series_ids), 25):
        chunk = series_ids[i : i + 25]
        for start, end in windows:
            out += _bls_call(chunk, start, end)
    return pd.DataFrame(out)


def _bls_call(chunk, start, end):
    out = []
    r = SESSION.post(
        BLS_API,
        json={"seriesid": chunk, "startyear": str(start), "endyear": str(end)},
        timeout=120,
    )
    r.raise_for_status()
    j = r.json()
    if j["status"] != "REQUEST_SUCCEEDED":
        raise RuntimeError(j)
    dump_json(j, RAW / f"bls_{chunk[0]}_{start}.json")
    for s in j["Results"]["series"]:
        for d in s["data"]:
            if d["period"] == "M13":
                continue
            m = 6 if d["period"].startswith("A") else int(d["period"][1:])
            out.append(dict(series_id=s["seriesID"], date=pd.Timestamp(int(d["year"]), m, 1),
                            value=float(d["value"])))
    return out


def main():
    rows = []
    for kind, groups in (("productivity", PRODUCTIVITY), ("ppi", PPI)):
        ids = [s for g in groups.values() for s in g]
        df = bls(ids)
        for grp, m in groups.items():
            for sid, name in m.items():
                sub = df[df.series_id == sid]
                for _, r in sub.iterrows():
                    rows.append(dict(panel=kind, group=grp, series_id=sid, name=name,
                                     date=r.date.date(), value=r.value,
                                     source=f"BLS {sid}"))
    csv = get(OECD_URL.format(areas="+".join(OECD_AREAS)), headers={"Accept": "text/csv"}).text
    (RAW / "oecd_gdp_per_hour.csv").write_text(csv)
    o = pd.read_csv(io.StringIO(csv))
    for _, r in o.iterrows():
        rows.append(dict(panel="oecd_gdp_per_hour", group=r.REF_AREA, series_id="GDPHRS",
                         name=r.REF_AREA, date=pd.Timestamp(int(r.TIME_PERIOD), 6, 1).date(),
                         value=r.OBS_VALUE, source="OECD DSD_PDB@DF_PDB GDPHRS XDC_H LR"))
    out = pd.DataFrame(rows).sort_values(["panel", "group", "series_id", "date"])
    out.to_csv(PROCESSED / "productivity.csv", index=False)
    print(out.groupby(["panel", "group"]).size(), file=sys.stderr)


if __name__ == "__main__":
    main()
