"""Non-CPI price series. Nothing here comes from the BLS Consumer Price Index.

  Housing      Zillow ZHVI (home values) and ZORI (asking rents), US aggregate row
               S&P CoreLogic Case-Shiller national index (via FRED mirror)
  Food         FAO Food Price Index (world commodity prices, 2014-16=100)
               World Bank Commodity Price Data ("pink sheet"): food, energy, metals, fertilizer
  Electricity  EIA Electric Power Monthly table 5.3, average retail price by sector (cents/kWh)
  Software     BLS Producer Price Index (what sellers receive, not what consumers pay):
                 PCU511210511210  Software publishers
                 PCU5182105182101 Data processing, hosting and related services
  Streaming, SaaS list prices, LLM token prices: hand-compiled with sources in data/manual/*.csv

Output: data/processed/prices_monthly.csv (long format: series, date, value, source)
"""
import io
import re
import sys

import pandas as pd

from common import PROCESSED, RAW, get

OUT = []


def add(series, s, source, note=""):
    s = s.dropna()
    df = pd.DataFrame({"series": series, "date": pd.to_datetime(s.index), "value": s.values,
                       "source": source, "note": note})
    OUT.append(df)
    print(f"{series:40s} {df.date.min().date()} .. {df.date.max().date()}  n={len(df)}", file=sys.stderr)


def fred(series_id, name, source):
    csv = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}").text
    (RAW / f"fred_{series_id}.csv").write_text(csv)
    df = pd.read_csv(io.StringIO(csv), index_col=0, na_values=".")
    add(name, df.iloc[:, 0], source)


def zillow():
    for name, url in [
        ("zillow_zhvi_us", "https://files.zillowstatic.com/research/public_csvs/zhvi/Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv"),
        ("zillow_zori_us", "https://files.zillowstatic.com/research/public_csvs/zori/Metro_zori_uc_sfrcondomfr_sm_month.csv"),
    ]:
        txt = get(url).text
        (RAW / f"{name}.csv").write_text(txt)
        df = pd.read_csv(io.StringIO(txt))
        us = df[df["RegionName"] == "United States"].iloc[0]
        s = us[[c for c in df.columns if re.match(r"\d{4}-\d{2}-\d{2}", c)]].astype(float)
        add(name, s, url)


def fao():
    page = get("https://www.fao.org/worldfoodsituation/foodpricesindex/en/").text
    m = re.search(r'href="(https://www\.fao\.org/media/docs/[^"]*food_price_indices_data\.csv[^"]*)"', page)
    url = m.group(1).replace("&amp;", "&")
    txt = get(url).text
    (RAW / "fao_ffpi.csv").write_text(txt)
    rows = re.findall(r"^(\d{4}-\d{2}),([\d.]+),([\d.]+),([\d.]+),([\d.]+),([\d.]+),([\d.]+)", txt, re.M)
    df = pd.DataFrame(rows, columns=["date", "food", "meat", "dairy", "cereals", "oils", "sugar"])
    df["date"] = pd.to_datetime(df["date"], format="%Y-%m")
    df = df.set_index("date").astype(float)
    for c in df.columns:
        add(f"fao_{c}_price_index", df[c], url, "nominal, 2014-2016=100")


def worldbank_pink_sheet():
    page = get("https://www.worldbank.org/en/research/commodity-markets").text
    url = re.search(r'href="(https://thedocs\.worldbank\.org/[^"]*CMO-Historical-Data-Monthly\.xlsx)"', page).group(1)
    content = get(url).content
    (RAW / "worldbank_cmo_monthly.xlsx").write_bytes(content)
    raw = pd.read_excel(io.BytesIO(content), sheet_name="Monthly Indices", header=None)
    first = raw.index[raw[0].astype(str).str.match(r"\d{4}M\d{2}")][0]
    # header labels are spread over several rows (a tree); take whichever cell is filled per column
    hdr = raw.iloc[:first].astype(str).replace("nan", None).bfill().iloc[0]
    hdr = hdr.str.replace(r"\s*\*+", "", regex=True).str.replace(r"\s+", " ", regex=True).str.strip()
    df = raw.iloc[first:].copy()
    df.columns = hdr.values
    df.index = pd.to_datetime(df.iloc[:, 0].str.replace("M", "-"), format="%Y-%m")
    wanted = {"Energy": "wb_energy_index", "Food": "wb_food_index", "Metals & Minerals": "wb_metals_index",
              "Fertilizers": "wb_fertilizer_index", "Agriculture": "wb_agriculture_index",
              "Non-energy": "wb_non_energy_index", "Precious Metals": "wb_precious_metals_index"}
    for c in df.columns:
        if c in wanted:
            add(wanted[c], pd.to_numeric(df[c], errors="coerce"), url, "nominal US$, 2010=100")


def eia_electricity():
    url = "https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=table_5_03"
    html = get(url).text
    (RAW / "eia_table_5_03.html").write_text(html)
    t = re.sub(r"<[^>]+>", " ", html)
    t = re.sub(r"&nbsp;", " ", t)
    t = re.sub(r"\s+", " ", t)
    # annual totals: "2016 12.55 10.43 6.76 9.63 10.27"
    ann = re.findall(r" (20\d\d) (\d+\.\d+) (\d+\.\d+) (\d+\.\d+) (\d+\.\d+) (\d+\.\d+)", t)
    seen = {}
    this_year = str(pd.Timestamp.today().year)
    for y, res, com, ind, tr, allsec in ann:
        if y < this_year:  # current year only appears as a year-to-date comparison
            seen.setdefault(y, (float(res), float(com), float(allsec)))
    s = pd.Series({pd.Timestamp(f"{y}-12-31"): v[0] for y, v in seen.items()})
    add("eia_electricity_residential_c_per_kwh", s, url, "annual average")
    s = pd.Series({pd.Timestamp(f"{y}-12-31"): v[1] for y, v in seen.items()})
    add("eia_electricity_commercial_c_per_kwh", s, url, "annual average")


def main():
    zillow()
    fred("CSUSHPINSA", "case_shiller_us_home_price", "S&P CoreLogic Case-Shiller via fred.stlouisfed.org")
    fao()
    worldbank_pink_sheet()
    eia_electricity()
    fred("PCU511210511210", "ppi_software_publishers", "BLS PPI via fred.stlouisfed.org (Dec 1997=100)")
    fred("PCU5182105182101", "ppi_data_processing_hosting", "BLS PPI via fred.stlouisfed.org")
    df = pd.concat(OUT)
    df.to_csv(PROCESSED / "prices_monthly.csv", index=False)


if __name__ == "__main__":
    main()
