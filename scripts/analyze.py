"""Build tables and charts from data/processed + data/manual. Writes charts/*.png and data/processed/summary_*.csv."""
import sys

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from common import CHARTS, MANUAL, PROCESSED  # noqa: E402

AI_LINE = pd.Timestamp("2022-11-30")  # ChatGPT public release; the "AI era" cut used throughout
plt.rcParams.update({"figure.dpi": 130, "axes.grid": True, "grid.alpha": 0.3, "axes.spines.top": False,
                     "axes.spines.right": False})


def ai_line(ax):
    ax.axvline(AI_LINE, color="k", ls="--", lw=0.8)
    ax.text(AI_LINE, ax.get_ylim()[1], " ChatGPT", va="top", fontsize=7)


def cagr(s, start, end):
    s = s.dropna()
    a = s[s.index >= pd.Timestamp(start)]
    b = s[s.index <= pd.Timestamp(end)]
    if a.empty or b.empty:
        return float("nan")
    v0, v1 = a.iloc[0], b.iloc[-1]
    yrs = (b.index[-1] - a.index[0]).days / 365.25
    return (v1 / v0) ** (1 / yrs) - 1 if yrs > 0 and v0 > 0 else float("nan")


# ---------------------------------------------------------------- 1. reliability
def incidents():
    df = pd.read_csv(PROCESSED / "incidents.csv")
    for c in ("start", "end"):
        df[c] = pd.to_datetime(df[c], utc=True, format="ISO8601")
    df["year"] = df["start"].dt.year
    df = df[df["year"] >= 2015]
    df = df[~df["name"].str.contains("maintenance", case=False, na=False)]
    # drop the current partial year from rate comparisons; AWS archive (old status.aws.amazon.com feed)
    # ends March 2023, so its 2023 is partial too
    full = df[df["year"] < pd.Timestamp.today().year]
    full = full[~((full.provider == "aws") & (full.year >= 2023))]
    # Google's incidents.json shrank from ~360 to ~20 entries during 2025 (feed/scope change, see README)
    full = full[~((full.provider == "gcp") & (full.year >= 2025))]
    by = full.pivot_table(index="year", columns="provider", values="id", aggfunc="count")
    by.to_csv(PROCESSED / "summary_incidents_per_year.csv")

    # duration statistics: only incidents with an end time, 5 min..7 days
    d = full[(full.duration_min > 5) & (full.duration_min < 7 * 24 * 60)]
    dur = d.groupby(["provider", "year"]).duration_min.median().unstack(0)
    dur.to_csv(PROCESSED / "summary_incident_median_duration.csv")
    hours = d.groupby(["provider", "year"]).duration_min.sum().unstack(0) / 60
    hours.to_csv(PROCESSED / "summary_incident_hours_per_year.csv")

    # statuspage: major/critical; gcp: high; aws old dashboard: 2=degradation 3=disruption
    major = full[full["impact"].astype(str).str.lower().isin(
        ["major", "critical", "high", "disruption", "degraded", "2", "3"])]
    mj = major.pivot_table(index="year", columns="provider", values="id", aggfunc="count").fillna(0)
    mj.to_csv(PROCESSED / "summary_major_incidents_per_year.csv")

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
    by.plot(ax=axes[0], marker="o", ms=3, title="Status-page incidents per year (excl. maintenance)")
    mj.plot(ax=axes[1], marker="o", ms=3, title="Major/critical incidents per year")
    dur.plot(ax=axes[2], marker="o", ms=3, title="Median incident duration (minutes)")
    for ax in axes:
        ax.axvline(2022.9, color="k", ls="--", lw=0.8)
        ax.set_xlabel("")
    fig.tight_layout()
    fig.savefig(CHARTS / "1_incidents.png")

    pre = full[(full.year >= 2019) & (full.year <= 2022)].groupby("provider").id.count() / 4
    post_df = full[full.year >= 2023]
    post = post_df.groupby("provider").id.count() / post_df.groupby("provider").year.nunique()
    tbl = pd.DataFrame({"incidents_per_year_2019_2022": pre, "incidents_per_year_2023_on": post})
    tbl["change"] = tbl.iloc[:, 1] / tbl.iloc[:, 0] - 1
    pre_h = hours.loc[2019:2022].mean()
    post_h = hours.loc[2023:].mean()
    tbl["incident_hours_per_year_2019_2022"] = pre_h
    tbl["incident_hours_per_year_2023_on"] = post_h
    tbl["hours_change"] = post_h / pre_h - 1
    tbl.to_csv(PROCESSED / "summary_incidents_pre_post.csv")
    print("\n== incidents per year, pre vs post ChatGPT ==\n", tbl.round(2).to_string())
    return tbl


# ---------------------------------------------------------------- 2. prices
def prices():
    df = pd.read_csv(PROCESSED / "prices_monthly.csv", parse_dates=["date"])
    wide = df.pivot_table(index="date", columns="series", values="value")
    rows = []
    for s in wide.columns:
        ser = wide[s]
        rows.append(dict(series=s,
                         cagr_2015_2019=cagr(ser, "2015-01-01", "2019-12-31"),
                         cagr_2019_2022=cagr(ser, "2019-12-01", "2022-11-30"),
                         cagr_2022_11_on=cagr(ser, "2022-11-01", "2030-01-01"),
                         last=ser.dropna().index[-1].date()))
    tbl = pd.DataFrame(rows).set_index("series")
    tbl.to_csv(PROCESSED / "summary_price_growth.csv")
    print("\n== annualised price growth (non-CPI series) ==\n", (tbl.iloc[:, :3] * 100).round(1).to_string())

    # streaming
    st = pd.read_csv(MANUAL / "streaming_prices.csv", parse_dates=["effective_date"])
    idx = pd.date_range("2015-01-01", "2026-09-01", freq="MS")
    basket = {}
    for (svc, plan), g in st.groupby(["service", "plan"]):
        basket[f"{svc}:{plan}"] = g.set_index("effective_date").usd_per_month.reindex(
            idx.union(g.effective_date)).ffill().reindex(idx)
    basket = pd.DataFrame(basket)
    # equal-weight index of services that existed at the start of each window, rebased to 100 at 2019-12
    core = basket[["netflix:standard", "spotify:premium_individual", "hulu:with_ads",
                   "youtube_premium:individual", "amazon_prime:annual_div_12"]].dropna()
    core_idx = (core / core.loc["2019-12-01"] * 100).mean(axis=1)
    core_idx.to_csv(PROCESSED / "summary_streaming_index.csv", header=["equal_weight_index_2019_12=100"])
    print("\n== streaming: 5-service equal-weight list price index (Dec 2019=100) ==")
    for d in [core_idx.index[0], "2019-12-01", "2022-11-01", "2024-12-01", core_idx.index[-1]]:
        print(f"  {pd.Timestamp(d).date()}  {core_idx.loc[d]:.1f}")
    print(f"  CAGR 2019-12..2022-11: {cagr(core_idx, '2019-12-01', '2022-11-30') * 100:.1f}%   "
          f"2022-11..now: {cagr(core_idx, '2022-11-01', '2030-01-01') * 100:.1f}%")

    fig, axes = plt.subplots(2, 3, figsize=(15, 7.5))
    ax = axes.flat
    w = wide.loc["2015":]

    def rebase(cols, ax, title, base="2019-12-01"):
        sub = w[cols].dropna(how="all")
        for c in cols:
            s = sub[c].dropna()
            b = s[s.index >= pd.Timestamp(base)].iloc[0]
            ax.plot(s.index, s / b * 100, label=c.replace("_", " "), lw=1.2)
        ax.set_title(title, fontsize=10)
        ax.legend(fontsize=6)
        ax.axhline(100, color="grey", lw=0.6)
        ai_line(ax)

    rebase(["zillow_zhvi_us", "zillow_zori_us", "case_shiller_us_home_price"], ax[0], "Housing (Dec 2019 = 100)")
    rebase(["fao_food_price_index", "fao_meat_price_index", "fao_dairy_price_index", "fao_cereals_price_index"],
           ax[1], "FAO food price indices (Dec 2019 = 100)")
    rebase(["wb_energy_index", "wb_food_index", "wb_metals_index", "wb_fertilizer_index"], ax[2],
           "World Bank commodity indices (Dec 2019 = 100)")
    rebase(["ppi_software_publishers", "ppi_data_processing_hosting"], ax[3],
           "Producer prices received by software / hosting sellers (Dec 2019 = 100)")
    e = w[["eia_electricity_residential_c_per_kwh", "eia_electricity_commercial_c_per_kwh"]].dropna()
    e.plot(ax=ax[4], marker="o", title="US retail electricity, cents/kWh (EIA)", fontsize=8)
    ax[4].legend(["residential", "commercial"], fontsize=7)
    ai_line(ax[4])
    for c in core.columns:
        ax[5].step(core.index, core[c], where="post", lw=1, label=c.split(":")[0])
    ax[5].plot(core_idx.index, core_idx / 100 * core.loc["2019-12-01"].mean(), "k", lw=2, label="equal-weight avg")
    ax[5].set_title("Streaming list prices, $/month", fontsize=10)
    ax[5].legend(fontsize=6)
    ai_line(ax[5])
    fig.tight_layout()
    fig.savefig(CHARTS / "2_prices.png")
    return tbl


# ---------------------------------------------------------------- 3. software vendors
def vendors():
    df = pd.read_csv(PROCESSED / "sec_software_panel.csv")
    df = df[(df.fy >= 2015) & (df.fy <= 2025)]
    # balanced-ish panel: companies reporting every year 2019..2025
    have = df[df.fy.between(2019, 2025)].groupby("ticker").fy.nunique()
    keep = have[have == 7].index
    p = df[df.ticker.isin(keep)]
    print(f"\n== SEC panel: {len(keep)} companies with FY2019-2025 data: {', '.join(sorted(keep))}")

    def agg(g):
        return pd.Series({
            "revenue_$bn": g.revenue.sum() / 1e9,
            "gross_margin_agg": g.gross_profit.sum() / g.revenue[g.gross_profit.notna()].sum(),
            "rd_pct_agg": g.rd.sum() / g.revenue[g.rd.notna()].sum(),
            "sm_pct_agg": g.sm.sum() / g.revenue[g.sm.notna()].sum(),
            "op_margin_agg": g.op_income.sum() / g.revenue[g.op_income.notna()].sum(),
            "sbc_pct_agg": g.sbc.sum() / g.revenue[g.sbc.notna()].sum(),
            "gross_margin_median": g.gross_margin.median(),
            "rd_pct_median": g.rd_pct.median(),
            "sm_pct_median": g.sm_pct.median(),
            "op_margin_median": g.op_margin.median(),
            "sbc_pct_median": g.sbc_pct.median(),
            "n": len(g),
        })

    yr = p.groupby("fy").apply(agg)
    yr.to_csv(PROCESSED / "summary_sec_panel_by_year.csv")
    print((yr * 100).round(1).drop(columns=["revenue_$bn", "n"]).assign(n=yr.n.astype(int)).to_string())

    ex = p[~p.ticker.isin(["MSFT", "ORCL"])]
    yr_ex = ex.groupby("fy").apply(agg)
    yr_ex.to_csv(PROCESSED / "summary_sec_panel_by_year_ex_msft_orcl.csv")
    print("\n-- same, excluding Microsoft and Oracle --")
    print((yr_ex * 100).round(1).drop(columns=["revenue_$bn", "n"]).assign(n=yr_ex.n.astype(int)).to_string())

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
    for k, ax in zip(["gross_margin", "rd_pct", "sm_pct"], axes):
        ax.plot(yr.index, yr[f"{k}_median"] * 100, "o-", label="median company")
        ax.plot(yr_ex.index, yr_ex[f"{k}_agg"] * 100, "s-", label="revenue-weighted, ex MSFT/ORCL")
        ax.plot(yr.index, yr[f"{k}_agg"] * 100, "^-", label="revenue-weighted, all")
        ax.set_title({"gross_margin": "Gross margin %", "rd_pct": "R&D % of revenue",
                      "sm_pct": "Sales & marketing % of revenue"}[k], fontsize=10)
        ax.axvline(2022.9, color="k", ls="--", lw=0.8)
        ax.legend(fontsize=7)
    fig.suptitle(f"{len(keep)} US-listed software companies, FY2015-2025 (SEC XBRL 10-K)", fontsize=10)
    fig.tight_layout()
    fig.savefig(CHARTS / "3_vendor_costs.png")

    # SaaS list prices
    sp = pd.read_csv(MANUAL / "saas_list_prices.csv", parse_dates=["effective_date"])
    first = sp.sort_values("effective_date").groupby(["vendor", "plan"]).first()
    last = sp.sort_values("effective_date").groupby(["vendor", "plan"]).last()
    t = pd.DataFrame({"first_date": first.effective_date.dt.date, "first_price": first.usd_per_user_month,
                      "last_date": last.effective_date.dt.date, "last_price": last.usd_per_user_month})
    t["change"] = t.last_price / t.first_price - 1
    t.to_csv(PROCESSED / "summary_saas_list_prices.csv")
    print("\n== SaaS list prices, first vs latest observed ==\n", t.to_string())

    # LLM token prices: cheapest frontier-class and cheapest overall per quarter
    llm = pd.read_csv(MANUAL / "llm_token_prices.csv", parse_dates=["effective_date"])
    llm["blend"] = llm.usd_per_1m_input * 0.75 + llm.usd_per_1m_output * 0.25
    fig, ax = plt.subplots(figsize=(7, 4))
    for v, g in llm.groupby("vendor"):
        ax.scatter(g.effective_date, g.blend, label=v, s=18)
    ax.set_yscale("log")
    ax.set_title("LLM API price per 1M tokens (75/25 in/out blend), all released models", fontsize=10)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(CHARTS / "4_llm_prices.png")
    return yr, yr_ex, t


# ---------------------------------------------------------------- 4. AI spend vs goods prices
BASE_FY = 2022  # last pre-ChatGPT fiscal year; capex above this level is treated as the AI buildout


def ai_spend():
    df = pd.read_csv(PROCESSED / "ai_spend.csv")
    w = df.pivot(index="fy", columns="series", values="value_usd_bn")
    capex_cols = [c for c in w.columns if c.startswith("capex:")]
    last = int(w[capex_cols].dropna().index.max())  # last FY with all five reported
    t = w.loc[BASE_FY - 3:last, capex_cols].copy()
    t["capex_5"] = t.sum(axis=1)
    t["capex_incremental"] = t["capex_5"] - t.loc[BASE_FY, "capex_5"]
    t["nvda_revenue"] = w["revenue:NVDA"]
    for d in ("pce_goods", "pce_total", "gdp", "inv_info_equipment"):
        t[d] = w[d]
        t[f"incremental_pct_{d}"] = t["capex_incremental"] / w[d] * 100
    t.round(2).to_csv(PROCESSED / "summary_ai_spend_breakeven.csv")
    print("\nAI capex vs goods spending ($bn, %):")
    cols = ["capex_5", "capex_incremental", "nvda_revenue", "pce_goods", "incremental_pct_pce_goods",
            "incremental_pct_pce_total", "incremental_pct_gdp", "incremental_pct_inv_info_equipment"]
    print(t[cols].round(1).to_string())

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4))
    ax = axes[0]
    (w.loc[2015:last, capex_cols].rename(columns=lambda c: c[6:])).plot.bar(stacked=True, ax=ax, width=0.8)
    ax.set_title("Capex, five largest AI builders ($bn, fiscal years)", fontsize=10)
    ax.legend(fontsize=7, ncol=2)
    ax.set_xlabel("")
    ax = axes[1]
    ax.plot(w.loc[2015:last].index, w.loc[2015:last, "revenue:NVDA"], marker="o")
    ax.set_title("NVIDIA revenue ($bn) - the hardware receipt side", fontsize=10)
    ax = axes[2]
    ax.bar(t.index, t["incremental_pct_pce_goods"], color="C3")
    ax.axhline(0, color="k", lw=0.8)
    ax.set_title(f"Capex above FY{BASE_FY} as % of US spending on goods\n= goods-price drop needed to offset it",
                 fontsize=10)
    ax.set_ylabel("%")
    fig.tight_layout()
    fig.savefig(CHARTS / "5_ai_spend.png")
    return t


# ---------------------------------------------------------------- 5. productivity differences
def _group_index(df, base_year):
    """Median of a group's series, each rebased to base_year = 100. Balanced: only series that run
    to the group's last date, so the index does not shift when laggard series drop out."""
    w = df.pivot_table(index="date", columns="series_id", values="value")
    w = w.loc[:, w.iloc[-1].notna()]
    base = w[w.index.year == base_year].mean()
    return (w / base * 100).median(axis=1)


def productivity():
    df = pd.read_csv(PROCESSED / "productivity.csv", parse_dates=["date"])
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4))
    summary = []

    # panel 1: BLS labour productivity, exposed vs unexposed, 2019 = 100
    p = df[df.panel == "productivity"]
    ax = axes[0]
    for grp, c in (("exposed", "C3"), ("unexposed", "C0")):
        g = _group_index(p[p.group == grp], 2019)
        g = g[g.index.year >= 2010]
        n = p[(p.group == grp) & (p.date == p.date.max())].series_id.nunique()
        ax.plot(g.index, g.values, marker="o", ms=3, color=c, label=f"AI-{grp} (n={n})")
        for y in (2019, 2022, 2025):
            summary.append(dict(panel="bls_labor_productivity", group=grp, year=y,
                                value=g[g.index.year == y].iloc[0]))
    ai_line(ax)
    ax.legend(fontsize=8)
    ax.set_title("Output per hour, BLS detailed industries\nmedian of group, 2019 = 100", fontsize=10)

    # panel 2: PPI exposed / unexposed ratio
    q = df[df.panel == "ppi"]
    ax = axes[1]
    ex, un = _group_index(q[q.group == "exposed"], 2019), _group_index(q[q.group == "unexposed"], 2019)
    ratio = (ex / un * 100).dropna()
    ratio = ratio[ratio.index.year >= 2010]
    ax.plot(ratio.index, ratio.values, color="C1")
    ax.axhline(100, color="k", lw=0.6)
    ai_line(ax)
    ax.set_title("Producer prices, AI-exposed services / unexposed\n"
                 "ratio, 2019 = 100 (falls if AI cuts exposed prices)", fontsize=10)
    for y in (2019, 2022):
        summary.append(dict(panel="ppi_ratio_exposed_over_unexposed", group="ratio", year=y,
                            value=ratio[ratio.index.year == y].mean()))
    summary.append(dict(panel="ppi_ratio_exposed_over_unexposed", group="ratio", year=ratio.index[-1].year,
                        value=ratio.iloc[-1]))

    # panel 3: OECD GDP per hour, 2019 = 100
    o = df[df.panel == "oecd_gdp_per_hour"]
    ax = axes[2]
    for area in ("USA", "EA20", "GBR", "JPN", "DEU", "CAN"):
        s = o[o.group == area].set_index("date").value
        s = s / s[s.index.year == 2019].iloc[0] * 100
        s = s[s.index.year >= 2015]
        ax.plot(s.index, s.values, marker="o", ms=3, lw=2.2 if area == "USA" else 1, label=area)
        for y in (2019, 2022, 2025):
            summary.append(dict(panel="oecd_gdp_per_hour", group=area, year=y, value=s[s.index.year == y].iloc[0]))
    ai_line(ax)
    ax.legend(fontsize=7, ncol=2)
    ax.set_title("Real GDP per hour worked, OECD\n2019 = 100", fontsize=10)
    fig.tight_layout()
    fig.savefig(CHARTS / "6_productivity.png")

    s = pd.DataFrame(summary).round(2)
    s.to_csv(PROCESSED / "summary_productivity.csv", index=False)
    print(s.pivot_table(index=["panel", "group"], columns="year", values="value"), file=sys.stderr)
    return s


if __name__ == "__main__":
    incidents()
    prices()
    vendors()
    ai_spend()
    productivity()
    print("\ncharts ->", CHARTS, file=sys.stderr)
