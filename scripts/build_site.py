"""Pack the processed tables into docs/data.js for the GitHub Pages site (docs/index.html)."""

import json

import pandas as pd

from common import MANUAL, PROCESSED, ROOT

DOCS = ROOT / "docs"
REBASE = "2019-12-01"
PRICE_SERIES = {
    "housing": ["zillow_zhvi_us", "zillow_zori_us", "case_shiller_us_home_price"],
    "food": ["fao_food_price_index", "fao_meat_price_index", "fao_dairy_price_index", "fao_cereals_price_index"],
    "commodities": ["wb_energy_index", "wb_food_index", "wb_metals_index", "wb_precious_metals_index",
                    "wb_fertilizer_index"],
    "software_ppi": ["ppi_software_publishers", "ppi_data_processing_hosting"],
}


def records(df):
    return json.loads(df.to_json(orient="records", date_format="iso"))


def rebased(wide, cols):
    w = wide[cols].dropna(how="all")
    w = w[w.index >= "2015-01-01"]
    base = w.loc[REBASE]
    return (w / base * 100).round(2)


def main():
    out = {}
    p = pd.read_csv(PROCESSED / "prices_monthly.csv", parse_dates=["date"])
    p["date"] = p["date"].dt.to_period("M").dt.to_timestamp()
    wide = p.groupby(["date", "series"]).value.mean().unstack()
    out["prices"] = {}
    for group, cols in PRICE_SERIES.items():
        r = rebased(wide, cols)
        out["prices"][group] = {"dates": [d.strftime("%Y-%m") for d in r.index],
                                "series": {c: r[c].where(r[c].notna(), None).tolist() for c in cols}}
    elec = wide[["eia_electricity_residential_c_per_kwh", "eia_electricity_commercial_c_per_kwh"]].dropna()
    out["electricity"] = {"years": [d.year for d in elec.index],
                          "residential": elec.iloc[:, 0].tolist(), "commercial": elec.iloc[:, 1].tolist()}
    s = pd.read_csv(PROCESSED / "summary_streaming_index.csv", index_col=0)
    out["streaming_index"] = {"dates": s.index.tolist(), "values": s.iloc[:, 0].round(1).tolist()}
    out["streaming_prices"] = records(pd.read_csv(MANUAL / "streaming_prices.csv"))
    out["saas"] = records(pd.read_csv(PROCESSED / "summary_saas_list_prices.csv").round(2))
    llm = pd.read_csv(MANUAL / "llm_token_prices.csv")
    llm["blend"] = (llm.usd_per_1m_input * 0.75 + llm.usd_per_1m_output * 0.25).round(3)
    out["llm"] = records(llm)

    out["price_growth"] = records(pd.read_csv(PROCESSED / "summary_price_growth.csv").round(3))
    for name in ("incidents_per_year", "major_incidents_per_year", "incident_hours_per_year",
                 "incident_median_duration"):
        df = pd.read_csv(PROCESSED / f"summary_{name}.csv")
        df["year"] = df["year"].astype(int)
        out[name] = records(df.round(1))
    out["incidents_pre_post"] = records(pd.read_csv(PROCESSED / "summary_incidents_pre_post.csv").round(2))
    for name in ("sec_panel_by_year", "sec_panel_by_year_ex_msft_orcl"):
        out[name] = records(pd.read_csv(PROCESSED / f"summary_{name}.csv").round(4))
    a = pd.read_csv(PROCESSED / "ai_spend.csv")
    out["ai_spend"] = records(a.pivot(index="fy", columns="series", values="value_usd_bn").round(2).reset_index())
    out["ai_breakeven"] = records(pd.read_csv(PROCESSED / "summary_ai_spend_breakeven.csv").round(2))
    pr = pd.read_csv(PROCESSED / "productivity.csv", parse_dates=["date"])
    out["productivity"] = {}
    for panel, by in (("productivity", "group"), ("ppi", "group"), ("oecd_gdp_per_hour", "group")):
        sub = pr[pr.panel == panel]
        out["productivity"][panel] = {}
        for grp, g in sub.groupby(by):
            w = g.pivot_table(index="date", columns="series_id", values="value")
            w = w.loc[:, w.iloc[-1].notna()]
            idx = (w / w[w.index.year == 2019].mean() * 100).median(axis=1)
            idx = idx[idx.index.year >= 2010].dropna()
            out["productivity"][panel][grp] = {"n": int(w.shape[1]),
                                                "dates": [d.strftime("%Y-%m") for d in idx.index],
                                                "values": idx.round(2).tolist()}
    out["generated"] = pd.Timestamp.today().strftime("%Y-%m-%d")

    DOCS.mkdir(exist_ok=True)
    (DOCS / "data.js").write_text("window.DATA = " + json.dumps(out, separators=(",", ":")) + ";\n")
    print("docs/data.js", (DOCS / "data.js").stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
