"""How much is being spent on AI, and how big a goods-price drop would offset it.

Spend (SEC XBRL 10-K, fiscal years keyed by period end):
  capex   MSFT, GOOGL, AMZN, META, ORCL  PaymentsToAcquirePropertyPlantAndEquipment (AMZN: ...ProductiveAssets)
  NVDA    total revenue (near-all data-center since FY2024) as a cross-check on the hardware side

Denominators (BEA via FRED, nominal, billions USD, annual average of monthly/quarterly SAAR):
  DGDSRC1  personal consumption expenditures: goods
  PCEC     personal consumption expenditures: total
  GDP      gross domestic product
  Y033RC1Q027SBEA  private fixed investment: information processing equipment

Output: data/processed/ai_spend.csv (long: series, fy, value_usd_bn, source)
"""

import io
import json
import sys
import time

import pandas as pd

from common import PROCESSED, RAW, dump_json, get, get_json
from fetch_sec import annual_series

CAPEX = {
    "MSFT": "Microsoft", "GOOGL": "Alphabet", "AMZN": "Amazon", "META": "Meta", "ORCL": "Oracle",
}
CAPEX_TAGS = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"]
REV_TAGS = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"]
FRED = {
    "pce_goods": "DGDSRC1",
    "pce_total": "PCEC",
    "gdp": "GDP",
    "inv_info_equipment": "Y033RC1Q027SBEA",
}


def facts_for(t, cik):
    path = RAW / f"sec_{t}.json"
    if path.exists() and "--refresh" not in sys.argv:
        return json.loads(path.read_text())
    facts = get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    dump_json(facts, path)
    time.sleep(0.15)
    return facts


def fred_annual(series_id):
    csv = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}").text
    (RAW / f"fred_{series_id}.csv").write_text(csv)
    s = pd.read_csv(io.StringIO(csv), index_col=0, na_values=".", parse_dates=True).iloc[:, 0]
    return s.groupby(s.index.year).mean()


def main():
    tickers = get_json("https://www.sec.gov/files/company_tickers.json")
    cik = {v["ticker"]: f"{v['cik_str']:010d}" for v in tickers.values()}
    rows = []
    for t, name in CAPEX.items():
        facts = facts_for(t, cik[t])
        for fy, (v, _) in annual_series(facts, CAPEX_TAGS).items():
            rows.append(dict(series=f"capex:{t}", company=name, fy=fy, value_usd_bn=v / 1e9,
                             source="SEC XBRL companyfacts, 10-K cash-flow statement"))
    for fy, (v, _) in annual_series(facts_for("NVDA", cik["NVDA"]), REV_TAGS).items():
        rows.append(dict(series="revenue:NVDA", company="NVIDIA", fy=fy, value_usd_bn=v / 1e9,
                         source="SEC XBRL companyfacts, 10-K"))
    for name, sid in FRED.items():
        for y, v in fred_annual(sid).items():
            rows.append(dict(series=name, company="", fy=int(y), value_usd_bn=v,
                             source=f"BEA via FRED {sid}, annual mean of SAAR, nominal"))
    df = pd.DataFrame(rows)
    df = df[df.fy >= 2015].sort_values(["series", "fy"])
    df.to_csv(PROCESSED / "ai_spend.csv", index=False)
    print(df.pivot(index="fy", columns="series", values="value_usd_bn").round(1).to_string(), file=sys.stderr)


if __name__ == "__main__":
    main()
