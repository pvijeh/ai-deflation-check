"""Software-vendor cost structure from SEC XBRL company facts (annual, 10-K).

Panel: US-listed software/SaaS companies with >=8 fiscal years of filings.
Metrics per fiscal year: revenue, cost of revenue, gross margin, R&D, S&M (or SG&A when
S&M is not broken out), operating income.

Output: data/processed/sec_software_panel.csv
"""
import json
import sys
import time

import pandas as pd

from common import PROCESSED, RAW, dump_json, get_json

PANEL = {
    "MSFT": "Microsoft", "ORCL": "Oracle", "CRM": "Salesforce", "ADBE": "Adobe", "NOW": "ServiceNow",
    "INTU": "Intuit", "WDAY": "Workday", "SNOW": "Snowflake", "DDOG": "Datadog", "CRWD": "CrowdStrike",
    "ZS": "Zscaler", "OKTA": "Okta", "TEAM": "Atlassian", "HUBS": "HubSpot", "TWLO": "Twilio",
    "ZM": "Zoom", "MDB": "MongoDB", "NET": "Cloudflare", "PANW": "Palo Alto Networks", "SHOP": "Shopify",
    "DOCU": "DocuSign", "PLTR": "Palantir", "ADSK": "Autodesk", "PTC": "PTC",
    "DBX": "Dropbox", "BOX": "Box", "ESTC": "Elastic", "GTLB": "GitLab", "PATH": "UiPath",
    "S": "SentinelOne", "BILL": "Bill.com", "APPF": "AppFolio", "PCTY": "Paylocity",
    "VEEV": "Veeva", "TYL": "Tyler Technologies", "MANH": "Manhattan Associates", "DT": "Dynatrace",
    "FTNT": "Fortinet",
}

# Oracle tags only a component of cost of revenue (hardware) as CostOfRevenue in some years; no total is tagged
NO_GROSS_MARGIN = {"ORCL"}

# XBRL tags in preference order
TAGS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
                "SalesRevenueServicesNet"],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfServices", "CostOfGoodsSold"],
    "gross_profit": ["GrossProfit"],
    "rd": ["ResearchAndDevelopmentExpense",
           "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
           "ResearchAndDevelopmentExpenseSoftwareExcludingAcquiredInProcessCost"],
    "sm": ["SellingAndMarketingExpense"],
    "sga": ["SellingGeneralAndAdministrativeExpense"],
    "ga": ["GeneralAndAdministrativeExpense"],
    "op_income": ["OperatingIncomeLoss"],
    "sbc": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
}


def annual_series(facts, tags):
    """fiscal year -> value, from 10-K FY facts with ~12-month duration.
    Companies switch tags over time (e.g. Revenues -> RevenueFromContractWithCustomer... after ASC 606),
    so the union is taken, earlier tags in the list winning on conflicts."""
    out = {}
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        found = {}
        units = usgaap.get(tag, {}).get("units", {}).get("USD", [])
        for f in units:
            if f.get("form") not in ("10-K", "10-K/A", "20-F") or f.get("fp") != "FY":
                continue
            start, end = pd.Timestamp(f["start"]), pd.Timestamp(f["end"])
            if not (330 <= (end - start).days <= 380):
                continue
            # XBRL "fy" is the filing's year, also on prior-year comparatives; key by period end instead
            fy = end.year
            # prefer the most recently filed value for the same fiscal year (restatements)
            if fy not in found or f["filed"] > found[fy][1]:
                found[fy] = (f["val"], f["filed"], end)
        for fy, v in found.items():
            out.setdefault(fy, v)
    return {fy: (v, end) for fy, (v, _, end) in out.items()}


def main():
    tickers = get_json("https://www.sec.gov/files/company_tickers.json")
    cik = {v["ticker"]: f"{v['cik_str']:010d}" for v in tickers.values()}
    rows = []
    for t, name in PANEL.items():
        if t not in cik:
            print("no CIK for", t, file=sys.stderr)
            continue
        path = RAW / f"sec_{t}.json"
        if path.exists() and "--refresh" not in sys.argv:
            facts = json.loads(path.read_text())
        else:
            facts = get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik[t]}.json")
            dump_json(facts, path)
            time.sleep(0.15)  # SEC fair-use limit: 10 req/s
        series = {k: annual_series(facts, tags) for k, tags in TAGS.items()}
        fys = sorted(set().union(*[s.keys() for s in series.values()]))
        for fy in fys:
            r = {"ticker": t, "company": name, "fy": fy}
            for k, s in series.items():
                if fy in s:
                    r[k] = s[fy][0]
                    r["fy_end"] = s[fy][1].date()
            rows.append(r)
        print(t, len(fys), "fiscal years", file=sys.stderr)
    df = pd.DataFrame(rows)
    df["gross_profit"] = df["gross_profit"].fillna(df["revenue"] - df["cost_of_revenue"])
    df.loc[df.ticker.isin(NO_GROSS_MARGIN), ["gross_profit", "cost_of_revenue"]] = float("nan")
    df["gross_margin"] = df["gross_profit"] / df["revenue"]
    df["rd_pct"] = df["rd"] / df["revenue"]
    df["sm_pct"] = df["sm"] / df["revenue"]
    df["sga_pct"] = df["sga"].fillna(df["sm"] + df["ga"]) / df["revenue"]
    df["op_margin"] = df["op_income"] / df["revenue"]
    df["sbc_pct"] = df["sbc"] / df["revenue"]
    df = df[df["revenue"].notna() & (df["revenue"] > 0)]
    df.sort_values(["ticker", "fy"]).to_csv(PROCESSED / "sec_software_panel.csv", index=False)
    print(df.groupby("ticker").fy.agg(["min", "max", "count"]).to_string(), file=sys.stderr)


if __name__ == "__main__":
    main()
