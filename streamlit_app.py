# streamlit_app.py
# Streamlit aplikacija – turistične regije Slovenije (v4)
# - Skupni pogled: regije kot poligoni (dissolve občin) + barvanje
# - Posamezna regija: občine (meje občin)
# - Dodano: pri posamezni regiji prikaz "delež Slovenije" za izbran indikator

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

try:
    import folium
except Exception:
    folium = None

try:
    import geopandas as gpd
except Exception:
    gpd = None

st.sidebar.write("geopandas:", "OK" if gpd is not None else "MISSING")
st.sidebar.write("folium:", "OK" if folium is not None else "MISSING")

import shapely
import geopandas
import pyproj
st.sidebar.write("versions:", {
    "streamlit": st.__version__,
    "geopandas": geopandas.__version__,
    "shapely": shapely.__version__,
    "pyproj": pyproj.__version__,
})


DATA_XLSX_DEFAULT = "Skupna tabela občine.xlsx"
GEOJSON_DEFAULT = "si.json"
SLO_BOUNDS = [[41.00, 10.38], [49.88, 18.61]]

AGG_RULES = {
    'Površina območja (km2)': ("sum", None),
    'Število prebivalcev (H2/2024)': ("sum", None),
    'Povprečna starost prebivalcev': ("wmean", 'Število prebivalcev (H2/2024)'),
    'Naravni prirast /1000 prebival.': ("wmean", 'Število prebivalcev (H2/2024)'),
    'Prenočitve turistov SKUPAJ': ("sum", None),
    'Prenočitve turistov Domači': ("sum", None),
    'Prenočitve turistov\tTuji': ("sum", None),
    'Prenočitve - povprečno število prenočitev na mesec': ("sum", None),
    'Delež tujih prenočitev': ("wmean", 'Prenočitve turistov SKUPAJ'),
    'Prihodi turistov SKUPAJ': ("sum", None),
    'Prihodi turistov Domači': ("sum", None),
    'Prihodi turistov Tuji': ("sum", None),
    'PDB turistov\tSKUPAJ': ("wmean", 'Prihodi turistov SKUPAJ'),
    'PDB turistov\tDomači': ("wmean", 'Prihodi turistov Domači'),
    'PDB turistov\tTuji': ("wmean", 'Prihodi turistov Tuji'),
    'Nastanitvene kapacitete - Nedeljive enote': ("sum", None),
    'Nastanitvene kapacitete - vsa ležišča': ("sum", None),
    'Nastanitvene kapacitete - stalna ležišča': ("sum", None),
    'Struktura nastanitvenih kapacitet - Sobe (nedeljive enote)\t- Hoteli in podobni obrati': ("sum", None),
    'Struktura nastanitvenih kapacitet - Sobe (nedeljive enote)\t- Kampi': ("sum", None),
    'Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Druge vrste kapacitet': ("sum", None),
    'Struktura nastanitvenih kapacitet - Stalna ležišča - Hoteli in podobni obrati': ("sum", None),
    'Struktura nastanitvenih kapacitet - Stalna ležišča - Kampi': ("sum", None),
    'Struktura nastanitvenih kapacitet - Stalna ležišča - Druge vrste kapacitet': ("sum", None),
    'Delež stalnih ležišč v Hotelih ipd.': ("wmean", 'Nastanitvene kapacitete - stalna ležišča'),
    'Povprečna letna zasedenost staln. ležišč': ("wmean", 'Nastanitvene kapacitete - stalna ležišča'),
    'Ocenjena povp. Letna zased. sob (nedeljivih enot)': ("wmean", 'Nastanitvene kapacitete - Nedeljive enote'),
    'Pritisk turizma na družbeni prostor (število stalnih ležišč / 100 prebivalcev)': ("wmean", 'Število prebivalcev (H2/2024)'),
    'Gostota turizma': ("wmean", 'Površina območja (km2)'),
    "Intenzivnost turizma (število nočitev na dan / 100 prebivalcev)": ("wmean", "Število prebivalcev (H2/2024)"),
    "Delovno aktivni v  turizmu (OECD/WTO)": ("sum", None),
    "Število zaposl. in samozaposl. v aktivnih podjetjih v Gostinstvu (I)": ("sum", None),
    "Zaposleni v Gostinstvu (I) v registr.podjetjih in s.p.": ("sum", None),
    "Zaposleni v nastan.dejav. (I55) v registr.podjetjih in s.p.": ("sum", None),
    "Vsi delovni aktivni na območju": ("sum", None),
    "Delež delovno aktivnih v turizmu (OECD/WTO)": ("wmean", "Vsi delovni aktivni na območju"),
    "Število vseh vrst podjetij na območju": ("sum", None),
    "Prihodek (v 1000 EUR) vseh podjetij na območju": ("sum", None),
    "Število reg. podjetij in s.p.  v Gostinstvu (I)": ("sum", None),
    "Prihodki reg.podjetij in s.p. v Gostinstvu (I)": ("sum", None),
    "Dodana vrednost reg.podjetij v Gostinstvu (I)": ("sum", None),
    "Dodana vrednost/zaposl. reg.podjetij Gostinstvu (I)": ("wmean", "Zaposleni v Gostinstvu (I) v registr.podjetjih in s.p."),
    "Ocenjeni stroški dela v reg. podj. v Gostinski (I) dejavnosti": ("sum", None),
    "Stroški dela na zaposl. na leto v reg. podj. v Gostinski (I) dejavnosti": ("wmean", "Zaposleni v Gostinstvu (I) v registr.podjetjih in s.p."),
    "Delež stroškov dela v prihodkih v reg. podj. v Gostinstvu (I)": ("wmean", "Prihodki reg.podjetij in s.p. v Gostinstvu (I)"),
    "Delež stroškov dela v dod vredn. v reg. podj. v Gostinstvu (I)": ("wmean", "Dodana vrednost reg.podjetij v Gostinstvu (I)"),
    "EBITDA v reg.podjetjih in s.p. v Gostinstvu (I)": ("sum", None),
    "EBITDA marža v reg.podjetjih in s.p. v Gostinstvu (I)": ("wmean", "Prihodki reg.podjetij in s.p. v Gostinstvu (I)"),
    "Čisti dobiček/izguba v reg. podj. in s.p. v Gostinstvu (I)": ("sum", None),
    "Sredstva v reg. Podjetjih in s.p. v Gostinstvu (I)": ("sum", None),
    "Kapital v reg. Podjetjih in s.p. v Gostinstvu (I)": ("sum", None),
    "Donosnost sredstev v reg. podjetjih in s.p. v Gostinstvu (I)": ("wmean", "Sredstva v reg. Podjetjih in s.p. v Gostinstvu (I)"),
    "Donosnost kapitala v reg. podjetjih in s.p. v Gostinstvu (I)": ("wmean", "Kapital v reg. Podjetjih in s.p. v Gostinstvu (I)"),
    "Dobičkovnost prihodkov v podjetjih in s.p. v Gostinstvu (I)": ("wmean", "Prihodki reg.podjetij in s.p. v Gostinstvu (I)"),
    "Število reg. podjetij in s.p. v nastanitveni dejav. (I 55)": ("sum", None),
    "Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)": ("sum", None),
    "Dodana vrednost reg.podjetij v nastanitveni dejav. (I 55)": ("sum", None),
    "Dodana vrednost/zaposl. V reg.podjetjih v nast.dejav. (I 55)": ("wmean", " Zaposleni v nastan.dejav. (I55) v registr.podjetjih in s.p."),
    "Ocenjeni stroški dela v reg. podj. v nastan.gost. (I 55) dejavnosti": ("sum", None),
    "Stroški dela na zaposl. na leto v reg. podj. v nast.gost. (I 55) dejavnosti": ("wmean", " Zaposleni v nastan.dejav. (I55) v registr.podjetjih in s.p."),
    "Delež stroškov dela v prihodkih v reg. podj. v nast.gost.dej. (I 55)": ("wmean", "Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"),
    "Delež stroškov dela v dod vredn. v reg. podj. v nast.gost.dej. (I 55)": ("wmean", "Dodana vrednost reg.podjetij v nastanitveni dejav. (I 55)"),
    "EBITDA v reg.podjetjih in s.p. v nastanitveni dejav. (I 55)": ("sum", None),
    "EBITDA marža v reg.podjetjih v nastanitveni dejav. (I 55)": ("wmean", "Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"),
    "Čisti dobiček/izguba v reg. podj. v nastanitveni dejav. (I 55)": ("sum", None),
    "Sredstva v reg. Podjetjih in s.p. v nastanitveni dejav. (I 55)": ("sum", None),
    "Kapital v reg. Podjetjih in s.p. v nastanitveni dejav. (I 55)": ("sum", None),
    "Donosnost sredstev v nastanitveni dejav. (I 55)": ("wmean", "Sredstva v reg. Podjetjih in s.p. v nastanitveni dejav. (I 55)"),
    "Donosnost kapitala v nastanitveni dejav. (I 55)": ("wmean", "Kapital v reg. Podjetjih in s.p. v nastanitveni dejav. (I 55)"),
    "Dobičkovnost prihodkov v nastanitveni dejav. (I 55)": ("wmean", "Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"),
    "Celotni prihodki v nastan. dejav. na prenočitev": ("wmean", "Prenočitve turistov SKUPAJ"),
    "Ocenjeni prihodki iz nast. dejav. na prenočitev": ("wmean", "Prenočitve turistov SKUPAJ"),
    "Ocenjeni prihodki iz nastan. dej. na razpoložljivo sobo (enoto)": ("wmean", 'Nastanitvene kapacitete - Nedeljive enote'),
    "Ocenjeni prihodki iz nast.dej. na prodano sobo (ned.enoto)": ("wmean", "Prenočitve turistov SKUPAJ"),
    "Poraba el.energije (MWh) Dejavnost Gostinstvo (I)": ("sum", None),
    "Poraba el.energ. v kWh na realiz. 1000 EUR prihodka v Gostinstvu (I)": ("wmean", "Prihodki reg.podjetij in s.p. v Gostinstvu (I)"),
    "Število kmetijskih  gospodarstev": ("sum", None),
    "Ocena skupne ekonomske velikosti kmetij.gospodarstev": ("sum", None),
    "Skupaj neto prejeti dohodek povp. na prebivalca": ("wmean", "Število prebivalcev (H2/2024)"),
    "Neto prejeti dohodek iz dela, povp. na preb.": ("wmean", "Število prebivalcev (H2/2024)"),
    "Neto prejeti dohodek iz premoženja, kapitala, idr.povp. na preb.": ("wmean", "Število prebivalcev (H2/2024)"),
    "Povprečna mesečna neto  plača/zaposl. osebo (EUR)": ("wmean", "Vsi delovni aktivni na območju"),
    "Povprečna neto plača izplačana na zaposl. osebo v Gostinstvu (I)": ("wmean", "Število zaposl. in samozaposl. v aktivnih podjetjih v Gostinstvu (I)"),
    "Indeks neto plača v Gostinstvu (I) /pvp. plača v vseh dejavnostih": ("wmean", "Vsi delovni aktivni na območju"),
    "Število izdanih gradbenih dovoljenj/1000 prebivalcev": ("wmean", "Število prebivalcev (H2/2024)"),
    "Število počitniških stanovanj": ("sum", None),
    "Delež naseljenih stanovanj od vseh razp.": ("mean", None),
    "Komunalni odpadki, zbrani  z javnim odvozom (kg/prebivalca)": ("wmean", "Število prebivalcev (H2/2024)"),
    "Štev.dijakov in študentov višjih strok. in visokošolsk.progr./1000 preb.": ("wmean", "Število prebivalcev (H2/2024)"),
    "Število vseh stanovanj": ("sum", None),
    "Delež naseljenih stanovanj": ("wmean", "Število vseh stanovanj"),
    "GINI Indeks - sezonskost prenočitev": ("wmean", 'Prenočitve - povprečno število prenočitev na mesec'),
    "Delež vseh prenočitev - Domači trg": ("wmean", "Prenočitve turistov SKUPAJ"),
    "Delež vseh prenočitev - DACH trgi": ("wmean", "Prenočitve turistov SKUPAJ"),
    "Delež vseh prenočitev - Italijanski trg": ("wmean", "Prenočitve turistov SKUPAJ"),
    "Delež vseh prenočitev - Vzh.evropski trgi (PL,CZ,HU,SK,LIT,LTV,EST,RU,UKR)": ("wmean", "Prenočitve turistov SKUPAJ"),
    "Delež vseh prenočitev - Drugi zah.in sev. evropski trgi (ES,P, F,Benelux, Skandinavske države)": ("wmean", "Prenočitve turistov SKUPAJ"),
    "Delež vseh prenočitev - Prekomorski trgi (ZDA, VB, CAN, AU, Azija)": ("wmean", "Prenočitve turistov SKUPAJ"),
    "Delež vseh prenočitev - Trgi JV Evrope": ("wmean", "Prenočitve turistov SKUPAJ"),
    "Delež vseh prenočitev - Vsi drugi tuji trgi": ("wmean", "Prenočitve turistov SKUPAJ"),
}


def find_excel_file():
    # 1) poskusi točno ime
    p = Path.cwd() / DATA_XLSX_DEFAULT
    if p.exists():
        return p

    # 2) fallback: vzorec (deluje tudi pri šumnikih/normalizaciji)
    candidates = list(Path.cwd().glob("*.xlsx"))
    if not candidates:
        return None

    # če jih je več, izberi tistega, ki vsebuje "Skupna" ali "tabela"
    for c in candidates:
        if "skupna" in c.name.lower() and "tabela" in c.name.lower():
            return c

    # sicer vzemi prvega
    return candidates[0]

def _safe_str(x):
    return "" if x is None or (isinstance(x, float) and np.isnan(x)) else str(x)

def normalize_name(s: str) -> str:
    s = _safe_str(s).strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("\u2013", "-").replace("\u2014", "-").replace("–", "-").replace("—", "-")
    s = re.sub(r"\s*-\s*", " - ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def is_rate_like(col: str) -> bool:
    c = col.lower()
    keywords = [
        "%", "delež", "/1000", "povpre", "indeks", "stopnja", "na 1", "na 1000", "na preb",
        "kg/preb", "€/preb", "na km2", "gostota", "marža", "povprečna letna zasedenost", "cenjena povp", "donosnost", "dobičkovnost"
    ]
    return any(k in c for k in keywords)

def is_percent_like(col: str) -> bool:
    c = col.lower()

    # stvari, ki so *deleži/indeksi* 
    positive = ["delež", "marža", "%", "stopnja", "povprečna letna zasedenost", "ocenjena povp", "donosnost", "dobičkovnost"]

    # stvari, ki so rate-i in jih *ne* želiš kot %
    negative = ["/1000", "na 1000", "na 1", "na preb", "kg/preb", "€/preb", "na km2", "gostota"]

    return any(k in c for k in positive) and not any(k in c for k in negative)


def parse_numeric(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    s = s.replace({"nan": "", "None": ""})
    s = s.str.replace("\u00a0", "", regex=False).str.replace(" ", "", regex=False)

    def conv(x):
        if x == "" or x == "-" or str(x).lower() == "nan":
            return np.nan
        x2 = re.sub(r"[^0-9\-,\.]", "", str(x))
        # SI: 1.234,56 -> 1234.56
        if "," in x2 and x2.rfind(",") > x2.rfind("."):
            x2 = x2.replace(".", "")
            x2 = x2.replace(",", ".")
        else:
            parts = x2.split(".")
            if len(parts) > 2:
                x2 = x2.replace(".", "")
            x2 = x2.replace(",", "")
        try:
            return float(x2)
        except Exception:
            return np.nan

    return s.apply(conv)

def format_si_number(x, decimals=None):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    try:
        x = float(x)
        if decimals is None:
            if abs(x - round(x)) < 1e-9:
                decimals = 0
            else:
                decimals = 1
        fmt = f"{{:,.{decimals}f}}".format(x)
        fmt = fmt.replace(",", "X").replace(".", ",").replace("X", ".")
        return fmt
    except Exception:
        return str(x)

def format_pct(x, decimals=1):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    try:
        return format_si_number(float(x), decimals) + " %"
    except Exception:
        return "—"
    
def format_indicator_value_tables(indicator: str, x):
    # deleži/indeksi so v podatkih v obliki 0.45 -> prikaz 45 %
    if is_percent_like(indicator):
        
        return round(x, 3)
    # vse ostalo ostane normalno število
    return round(x, 2)

def format_indicator_value_map(indicator: str, x):
    # deleži/indeksi so v podatkih v obliki 0.45 -> prikaz 45 %
    if is_percent_like(indicator):
        return format_pct(float(x) * 100.0, 1)
    #GINI indeks izjema
    if "GINI" in indicator:
        return round(x,2)
    # vse ostalo ostane normalno število
    return format_si_number(x)

def strip_diacritics(s: str) -> str:
    return (s.replace("č","c").replace("š","s").replace("ž","z")
             .replace("Č","C").replace("Š","S").replace("Ž","Z"))

def canon_col(s: str) -> str:
    s = normalize_name(s)
    s = strip_diacritics(s).lower()
    s = re.sub(r"[^a-z0-9 ]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s
   
def find_col(df: pd.DataFrame, wanted: list[str]) -> str | None:
    mapping = {canon_col(c): c for c in df.columns}
    for w in wanted:
        if w in mapping:
            return mapping[w]
    for cc, orig in mapping.items():
        for w in wanted:
            if w in cc:
                return orig
    return None

def load_excel(path_or_buffer) -> pd.DataFrame:
    df0 = pd.read_excel(path_or_buffer, header=0)
    c_ob = find_col(df0, ["obcine", "obcina"])
    c_reg = find_col(df0, ["turisticna regija", "turisticne regije", "turisticna"])
    if c_ob and c_reg:
        return df0
    raw = pd.read_excel(path_or_buffer, header=None)
    if raw.shape[0] < 2:
        return df0
    cols = raw.iloc[0].tolist()
    df1 = raw.iloc[1:].copy()
    df1.columns = cols
    return df1

def try_load_geojson(path: Path):
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None



def aggregate_indicator_with_rules(df: pd.DataFrame, indicator: str, agg_rules: dict):
    if "Celotni prihodki v nastan. dejav. na prenočitev" in indicator :

        values1 = sum(df["Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"].astype(float))
        values2 = sum(df['Prenočitve turistov SKUPAJ'])


        
        return values1/values2

    if "Ocenjeni prihodki iz nast. dejav. na prenočitev" in indicator :

        values1 = sum(df["Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"].astype(float)) * 0.8
        values2 = sum(df['Prenočitve turistov SKUPAJ'])
  

        
        return values1/values2

    if "Ocenjeni prihodki iz nast.dej. na prodano sobo (ned.enoto)" in indicator:

        values1 = sum(df["Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"] * 0.8)
        
        hoteli = sum(df['Struktura nastanitvenih kapacitet - Sobe (nedeljive enote)\t- Hoteli in podobni obrati'])
        druge_enote = sum(df['Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Druge vrste kapacitet'])
        kampi = sum(df['Struktura nastanitvenih kapacitet - Sobe (nedeljive enote)\t- Kampi'])

        vse_enote = hoteli + druge_enote + kampi

        hoteli_zasedenost = 1.6* (hoteli/vse_enote)
        kampi_zasedenost = 2.5* (kampi/vse_enote)
        druge_zasedenost = 2 * (druge_enote/vse_enote)
        
        values2 = sum(df["Prenočitve turistov SKUPAJ"])/ (hoteli_zasedenost + kampi_zasedenost + druge_zasedenost)
           
        return values1/values2
    
    if "Ocenjeni prihodki iz nastan. dej. na razpoložljivo sobo (enoto)" in indicator:
        
        values1 = sum(df["Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"] * 0.8)
        
        hoteli = sum(df['Struktura nastanitvenih kapacitet - Sobe (nedeljive enote)\t- Hoteli in podobni obrati'])
        druge_enote = sum(df['Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Druge vrste kapacitet'])
        kampi = sum(df['Struktura nastanitvenih kapacitet - Sobe (nedeljive enote)\t- Kampi'])

        values2 = (hoteli + druge_enote) * 365 + kampi * 153

        return values1/values2

    if indicator not in agg_rules:
    
        return df[indicator].sum(skipna=True)
    
    rule, weight_col = agg_rules[indicator]

    values = df[indicator].astype(float)

    if rule == "sum":
        return float(values.sum(skipna=True))
    if rule == "mean":
        return float(values.mean(skipna=True))
    if rule == "wmean":
        
        if weight_col is None or weight_col not in df.columns:
            return float(values.mean(skipna=True))
        
        weights = df[weight_col].astype(float)
        mask = (~values.isna()) & (~weights.isna()) & (weights > 0)

        if not mask.any():
            
            return np.nan
        
        return float(np.average(values[mask], weights= weights[mask]))
    
    return float(values.sum(skipna = True))



def compute_region_aggregates1(num_df, regions, indicator_cols, agg_rules, group_col:str):
    out = pd.DataFrame({group_col : regions})

    for ind in indicator_cols:
        out[ind] = [aggregate_indicator_with_rules(
            num_df[num_df[group_col] == r],
            ind,
            agg_rules
        )
        for r in regions]
    
    return out

def get_geojson_name_prop(geojson_obj, candidates=("name","NAME","Občina","OBČINA")):
    sample_props = None
    for feat in geojson_obj.get("features", [])[:15]:
        sample_props = feat.get("properties", {})
        if sample_props:
            break
    if not sample_props:
        return None
    for c in candidates:
        if c in sample_props:
            return c
    return list(sample_props.keys())[0]



@st.cache_data(show_spinner=False)
def build_region_geojson_from_municipalities(geojson_obj: dict, name_prop: str, muni_to_region: dict, group_col:str) -> dict | None:
    if gpd is None or geojson_obj is None:
        return None
    try:
        gdf = gpd.GeoDataFrame.from_features(geojson_obj.get("features", []))
        if gdf.empty:
            return None
        if gdf.crs is None:
            gdf = gdf.set_crs(4326)

        gdf["__obcina__"] = gdf[name_prop].apply(normalize_name)
        gdf[group_col] = gdf["__obcina__"].map(muni_to_region)
        gdf = gdf[gdf[group_col].notna()].copy()
        if gdf.empty:
            return None

        reg_gdf = gdf.dissolve(by=group_col, as_index=False)
        try:
            reg_gdf["geometry"] = reg_gdf["geometry"].simplify(tolerance=0.0005, preserve_topology=True)
        except Exception:
            pass

        return json.loads(reg_gdf.to_json())
    except Exception:
        return None

def _palette(val, vmin, vmax):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "#cccccc"
    if vmax == vmin:
        return "#3182bd"
    q = (val - vmin) / (vmax - vmin)
    bins = [0.2, 0.4, 0.6, 0.8]
    colors = ["#deebf7", "#9ecae1", "#6baed6", "#3182bd", "#08519c"]
    idx = sum(q > b for b in bins)
    return colors[idx]



def make_localized_column_config(df: pd.DataFrame):
    cfg = {}
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]):
            if is_percent_like(c):
                cfg[c] = st.column_config.NumberColumn(format="percent")
            else:
                cfg[c] = st.column_config.NumberColumn(format="localized")
    return cfg

@st.cache_data(show_spinner=False)
def render_map_regions(regions_geojson: dict, region_to_value: dict, indicator_label: str,group_col: str, height=680):
    if folium is None or regions_geojson is None:
        st.info("Zemljevid ni na voljo (manjka folium ali GeoJSON).")
        return

    # kopija, da ne spreminjamo originalnega geojson-a
    gj = json.loads(json.dumps(regions_geojson))

    # dodamo vrednost v properties za tooltip
    for feat in gj.get("features", []):
        props = feat.get("properties", {}) or {}
        reg = props.get(group_col)
        val = region_to_value.get(reg, np.nan)
        props["_vrednost_fmt"] = format_indicator_value_map(indicator_label,val)
        feat["properties"] = props

    m = folium.Map(location=[45.65, 14.82], tiles="cartodbpositron",zoom_start= 8, max_bounds=True, min_zoom= 7)


    m.options['maxBounds'] = SLO_BOUNDS
    m.options['maxBoundsViscosity'] = 0.7

    vals = [v for v in region_to_value.values() if v is not None and not (isinstance(v, float) and np.isnan(v))]
    vmin = float(np.nanmin(vals)) if vals else 0.0
    vmax = float(np.nanmax(vals)) if vals else 1.0

    def style_fn(feature):
        reg = feature.get("properties", {}).get(group_col)
        val = region_to_value.get(reg, np.nan)
        return {"fillColor": _palette(val, vmin, vmax), "color": "#111111", "weight": 2.2, "fillOpacity": 0.70}

    layer = folium.GeoJson(
        gj,
        name="Turistične regije",
        style_function=style_fn,
        tooltip=folium.GeoJsonTooltip(
            fields=[group_col, "_vrednost_fmt"],
            aliases=["Regija:", f"{indicator_label}:"],
            sticky=True
        )
    ).add_to(m)

    bounds = layer.get_bounds()
    m.fit_bounds(bounds, padding= (40, 40), max_zoom=8)

    st.components.v1.html(m._repr_html_(), height=height, scrolling=False)

@st.cache_data(show_spinner=False)
def render_map_municipalities(
    geojson_obj,
    name_prop: str,
    muni_in_region: set,
    muni_to_value: dict,
    indicator_label: str = "Vrednost",
    height=680
):
    
    if folium is None or geojson_obj is None:
        st.info("Zemljevid ni na voljo (manjka folium ali GeoJSON).")
        return

    # kopija geojson-a
    gj_all = json.loads(json.dumps(geojson_obj))

    # razdeli feature-je na: v regiji / izven regije
    feats_in = []
    feats_out = []

    # pripravimo vrednosti za barvno lestvico (samo znotraj regije)
    vals = [
        v for k, v in muni_to_value.items()
        if k in muni_in_region and v is not None and not (isinstance(v, float) and np.isnan(v))
    ]
    vmin = float(np.nanmin(vals)) if vals else 0.0
    vmax = float(np.nanmax(vals)) if vals else 1.0

    for feat in gj_all.get("features", []):
        props = feat.get("properties", {}) or {}
        nm = normalize_name(props.get(name_prop, ""))

        if nm in muni_in_region:
            val = muni_to_value.get(nm, np.nan)
            props["_indikator"] = indicator_label
            props["_vrednost_fmt"] = format_indicator_value_map(indicator_label,val)
            feat["properties"] = props
            feats_in.append(feat)
        else:
            feats_out.append(feat)
    
    gj_in = {"type": "FeatureCollection", "features": feats_in}
    gj_out = {"type": "FeatureCollection", "features": feats_out}

    m = folium.Map(location=[45.65, 14.82], tiles="cartodbpositron", max_bounds=True, min_zoom= 7)
    

    m.options['maxBounds'] = SLO_BOUNDS
    m.options['maxBoundsViscosity'] = 0.7

    # 1) IZVEN REGIJE (brez tooltipa)
    def style_out(feature):
        return {"fillColor": "#e0e0e0", "color": "#aaaaaa", "weight": 0.4, "fillOpacity": 0.25}

    folium.GeoJson(
        gj_out,
        name="Občine (izven regije)",
        style_function=style_out
    ).add_to(m)

    # 2) V REGIJI (s tooltipom)
    def style_in(feature):
        props = feature.get("properties", {}) or {}
        nm = normalize_name(props.get(name_prop, ""))
        val = muni_to_value.get(nm, np.nan)
        return {"fillColor": _palette(val, vmin, vmax), "color": "#111111", "weight": 0.9, "fillOpacity": 0.75}

    layer = folium.GeoJson(
        gj_in,
        name="Občine (v regiji)",
        style_function=style_in,
        tooltip=folium.GeoJsonTooltip(
            fields=[name_prop, "_vrednost_fmt"],
            aliases=["Občina:", f"{indicator_label}:"],
            sticky=True
        )
    ).add_to(m)

    bounds = layer.get_bounds()
    m.fit_bounds(bounds, padding= (40, 40), max_zoom=9)
    st.components.v1.html(m._repr_html_(), height=height, scrolling=False)
   


@st.cache_data(show_spinner=False)
def load_geojson_from_upload_or_file(uploaded, default_path: Path):
    if uploaded is not None:
        return json.load(uploaded)
    return try_load_geojson(default_path)



# ---------------------------
# UI
# ---------------------------
st.set_page_config(page_title="Upravljanje turističnih destinacij Slovenije – ključni podatki in kazalniki", layout="wide", initial_sidebar_state="collapsed")

col_left, col_center, col_right = st.columns([1, 6, 3])

with col_left:
    st.image("top _left_logo.jpg")

with col_center:
    ""

with col_right:
    st.image("Top_right_logo.jpg", width= 350)

st.title("Upravljanje turističnih destinacij Slovenije – ključni podatki in kazalniki")

st.markdown("***Podatki se nanašajo na leto 2024***")

with st.sidebar:
    st.header("Nastavitve")
    xlsx_file = st.file_uploader("Naloži Excel (če ne uporabiš privzetega)", type=["xlsx"])
    geojson_file = st.file_uploader("Naloži GeoJSON občin (opcijsko)", type=["json", "geojson"])
    st.divider()
    dashboard_mode = st.checkbox("Dashboard način (več indikatorjev)", value=True)


# Load data
if xlsx_file is not None:
    df = load_excel(xlsx_file)
else:
    default_path = find_excel_file()
    if not default_path.exists():
        st.error(f"Ne najdem privzetega Excela: {default_path.name}. Naloži Excel v stranski vrstici.")
        st.stop()
    df = load_excel(default_path)

if "Občine" not in df.columns or "Turistična regija" not in df.columns:
    st.error("V Excelu ne najdem stolpcev 'Občine' in/ali 'Turistična regija'.")
    st.stop()

df = df.copy()
df["__obcina_norm__"] = df["Občine"].apply(normalize_name)

meta_cols = {"Občine", "Turistična regija", "__obcina_norm__", "Vodilne destinacije", "Perspektivne destinacije", "Makro destinacije"}
indicator_cols = [c for c in df.columns if c not in meta_cols]

pop_candidates = [c for c in indicator_cols if "prebival" in c.lower() and "število" in c.lower()]
pop_col = pop_candidates[0] if pop_candidates else None

geojson_obj = load_geojson_from_upload_or_file(
    geojson_file,
    Path(__file__).parent / GEOJSON_DEFAULT
)
name_prop = get_geojson_name_prop(geojson_obj) if geojson_obj else None

# Kandidati za poglede (zavihki)
VIEW_CANDIDATES = [
    ("Turistične regije", ["turisticna regija", "turisticne regije"]),
    ("Vodilne destinacije", ["vodilna destinacija", "vodilne destinacije"]),
    ("Makrodestinacije", ["makrodestinacija", "makrodestinacije", "makro destinacije"]),
    ("Regijske destinacije", ["regijska destinacija", "regijske destinacije"]),
    ("Perspektivne destinacije", ["perspektivna destinacija", "perspektivne destinacije"]),
]

views = []

for title, wanted in VIEW_CANDIDATES:
    col = find_col(df, wanted)
    if col is not None:
        views.append((title, col))

view_labels = [v[0] for v in views]
selected_view_label = st.selectbox("Pogled", view_labels, index=0)



def render_view(view_title: str, group_col: str):
    st.caption(f"**Pogled:** {view_title}")

    meta = meta_cols | {group_col}
    indicator_cols = [c for c in df.columns if c not in meta]

    #Za regijo
    df_regions = df[df[group_col].notna()].copy()
    regions = sorted(df_regions[group_col].dropna().unique().tolist())
    regions_with_all = ["Vsa območja"] + regions

    num_df = df_regions.copy()
    
    for c in indicator_cols:
        num_df[c] = parse_numeric(num_df[c])
    

    #za Celotno slovenijo
    df_temp = df[df["Turistična regija"].notna()].copy()

    df_slo_total = df_temp.copy()

    for c in indicator_cols:
        df_slo_total[c] = parse_numeric(df_slo_total[c])




    # mapping občina -> regija (normalizirano)
    muni_to_region = {normalize_name(o): r for o, r in zip(df_regions["Občine"], df_regions[group_col])}

    # dropdowni
    top_left, top_right = st.columns([1.2, 1])
    with top_left:
        selected_region = st.selectbox(group_col, regions_with_all, index=0, key=f"sel_group_{group_col}")
    with top_right:
        map_indicator = st.selectbox("Indikator za zemljevid", indicator_cols, index=0, key=f"sel_ind_{group_col}")

    dash_inds = []
    if dashboard_mode:
        default_inds = indicator_cols[:0] if len(indicator_cols) >= 4 else indicator_cols
        dash_inds = st.multiselect("Indikatorji za dashboard (do 6)", indicator_cols, default=default_inds, max_selections=6, placeholder= "Izberi indikator", key=f"dash_{group_col}")

    # agregati regij
    agg_needed = [map_indicator] + [i for i in dash_inds if i != map_indicator]
    region_agg = compute_region_aggregates1(num_df, regions, agg_needed, AGG_RULES, group_col=group_col)
    region_to_value_map = dict(zip(region_agg[group_col], region_agg[map_indicator]))

    # regijski geojson (dissolve)
    regions_geojson = None
    if selected_region == "Vsa območja" and geojson_obj and name_prop:
        regions_geojson = build_region_geojson_from_municipalities(geojson_obj, name_prop, muni_to_region, group_col=group_col)

    # KPI / pregled
    if selected_region == "Vsa območja":
        st.subheader("Primerjava območij")
        cols_to_show = [group_col] + agg_needed
        show_df = region_agg[cols_to_show].copy()
        for c in cols_to_show[1:]:
            show_df[c] = show_df[c].apply(lambda x: format_indicator_value_tables(c, x))
            

        show_df = show_df.sort_values(cols_to_show[1], ascending=False, na_position="last" )

        st.dataframe(
            show_df,
            use_container_width=True,
            height=260,
            hide_index=True,
            column_config = make_localized_column_config(show_df),
            )
        
    else:
        st.subheader("Povzetek izbrane regije")
        
        reg_df = num_df[num_df[group_col] == selected_region].copy()
        reg_total = aggregate_indicator_with_rules(reg_df, map_indicator, AGG_RULES)

        # "Slovenija total" – smiselno le za seštevne indikatorje
        sl_total = aggregate_indicator_with_rules(df_slo_total, map_indicator, AGG_RULES)
        
        share_si = np.nan
        if (not is_rate_like(map_indicator)) and sl_total and not np.isnan(sl_total) and sl_total != 0:
            share_si = (reg_total / sl_total) * 100.0

        # KPI: prvi je indikator + delež SLO
        left_kpi, right_kpi = st.columns([1.2, 1])
        with left_kpi:
            if not np.isnan(share_si): 
                st.metric(map_indicator, f"{format_si_number(reg_total)}", f"Delež Slovenije: {format_pct(share_si, 1)}")
            else:
                st.metric(map_indicator, f"{format_indicator_value_map(map_indicator, reg_total)}")
        with right_kpi:
            st.caption("Opomba: »Delež Slovenije« je prikazan za indikatorje, kjer se vrednosti seštevajo (ne za stopnje/indekse).")

        # dodatni KPI-ji (dashboard)
        if dashboard_mode and dash_inds:
            kpi_cols = st.columns(min(6, len(dash_inds)))
            for idx, ind in enumerate(dash_inds[:6]):

                # vrednost regije
                v_reg = float(region_agg.loc[region_agg[group_col] == selected_region, ind].iloc[0])

                # total Slovenije za ta indikator
                v_slo = aggregate_indicator_with_rules(df_slo_total, ind, AGG_RULES)

                # delež Slovenije (samo za seštevne indikatorje)
                share = np.nan
                if (not is_rate_like(ind)) and v_slo and not np.isnan(v_slo) and v_slo != 0:
                    share = (v_reg / v_slo) * 100.0

                # prikaz
                if not np.isnan(share):
                    kpi_cols[idx].metric(
                        ind,
                        format_si_number(v_reg),
                        f"Delež Slovenije: {format_pct(share, 1)}"
                    )
                else:
                    kpi_cols[idx].metric(ind, format_indicator_value_map(ind, v_reg))

    st.markdown("---")
    st.subheader("Zemljevid in razčlenitev")
    st.caption("Skupni pogled: Skupni podatki za posamezna območja. Posamezno območje: meje občin ter deleži znotraj območja. Dodan je tudi delež Občine glede na območje (kjer je smiselno).")

    map_col, table_col = st.columns([2.2, 1.0], gap="large")

    with map_col:
        if geojson_obj is None or name_prop is None:
            st.info("Za zemljevid naloži občinski GeoJSON (npr. `si.json`).")
        else:
            if selected_region == "Vsa območja":
                if regions_geojson is None:

                    st.warning("Ne uspem sestaviti poligonov regij (dissolve). Prikazujem občine obarvane po regijski vrednosti.")
                    muni_region_val = {m: region_to_value_map.get(r, np.nan) for m, r in muni_to_region.items()}
                    render_map_municipalities(geojson_obj, name_prop, set(muni_to_region.keys()), muni_region_val,indicator_label=map_indicator, height=680)
                else:
                    render_map_regions(regions_geojson, region_to_value_map,indicator_label=map_indicator,group_col=group_col, height=780)
            else:
                reg_df = num_df[num_df[group_col] == selected_region].copy()
                muni_in_region = set(reg_df["__obcina_norm__"].tolist())
                muni_to_value = {normalize_name(o): float(v) for o, v in zip(reg_df["Občine"], reg_df[map_indicator])}
                render_map_municipalities(geojson_obj, name_prop, muni_in_region, muni_to_value,indicator_label=map_indicator, height=780)

    with table_col:
        if selected_region == "Vsa območja":
            st.markdown(f"**Tabela območij** \n \n **:blue[{map_indicator}]**")
            t = region_agg[[group_col, map_indicator]].copy()
            t = t.sort_values(map_indicator, ascending=False, na_position="last")
            t[map_indicator] = t[map_indicator].apply(lambda x: format_indicator_value_tables(map_indicator, x))
            cfg = make_localized_column_config(t)
            
            old_key= next(iter(cfg))
            cfg["Vrednost"] = cfg.pop(old_key)


            t = t.rename(columns={map_indicator: "Vrednost"})

            st.dataframe(
                t,
                use_container_width=True,
                height=680,
                hide_index=True,
                column_config = cfg,
                )
        else:
            st.markdown(f"**Tabela občin znotraj območja** \n \n **:blue[{map_indicator}]**")
            reg_df = num_df[num_df[group_col] == selected_region].copy()
            reg_total = aggregate_indicator_with_rules(reg_df, map_indicator, AGG_RULES)
            
            cfg_df = pd.DataFrame({
                "Občina": reg_df["Občine"].astype(str),
                map_indicator: reg_df[map_indicator].astype(float).apply(lambda x: format_indicator_value_tables(map_indicator, x))
            })
            
            cfg = make_localized_column_config(cfg_df)
            
            old_key= next(iter(cfg))
            cfg["Vrednost"] = cfg.pop(old_key)

            tbl = pd.DataFrame({
                "Občina": reg_df["Občine"].astype(str),
                "Vrednost": reg_df[map_indicator].astype(float).apply(lambda x: format_indicator_value_tables(map_indicator, x))
            })
            if (reg_total and not np.isnan(reg_total) and reg_total != 0 and not is_rate_like(map_indicator)):
                tbl["Delež v regiji (%)"] = round(((tbl["Vrednost"] / reg_total) * 100.0), 1)
            else:
                pass

            tbl = tbl.sort_values("Vrednost", ascending=False, na_position="last")

            st.dataframe(
                tbl,
                use_container_width=True,
                height=680,
                hide_index=True,
                column_config = cfg,
                )
        st.caption("Opomba: »Delež v regiji (%)« je prikazan za indikatorje, kjer se vrednosti seštevajo (ne za stopnje/indekse).")



title, group_col = next(v for v in views if v[0] == selected_view_label)
render_view(title, group_col)

st.image("footer_logo.jpg", width= 200)

st.caption("Viri podatkov: SURS, AJPES, Narodna Banka Slovenije, Slovenska Turistična Organizacija, Lastna obdelava, izračuni in dodatne ocene manjkajočih podatkov - Hosting Management & Consulting d.o.o.")
st.caption("Naročnik projekta: Ministrstvo za gospodarstvo turizem in šport RS")
st.caption("Izvajalec projekta: Hosting Management & Consulting d.o.o., December 2025")
st.markdown("---")