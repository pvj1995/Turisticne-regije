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




DATA_XLSX_DEFAULT = "Skupna tabela občine.xlsx"
GEOJSON_DEFAULT = "si.json"
SLO_BOUNDS = [[43.00, 11.38], [47.88, 17.61]]

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
        "kg/preb", "€/preb", "na km2", "gostota"
    ]
    return any(k in c for k in keywords)

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

def aggregate_indicator(df: pd.DataFrame, indicator: str, pop_col: str | None):
    v = df[indicator].astype(float)
    if is_rate_like(indicator):
        if pop_col and pop_col in df.columns:
            w = df[pop_col].astype(float)
            mask = (~v.isna()) & (~w.isna()) & (w > 0)
            if mask.any():
                return float(np.average(v[mask], weights=w[mask]))
        return float(v.mean(skipna=True))
    else:
        return float(v.sum(skipna=True))

def compute_region_aggregates(num_df: pd.DataFrame, regions: list[str], indicator_cols: list[str], pop_col: str | None):
    out = pd.DataFrame({"Turistična regija": regions})
    for ind in indicator_cols:
        out[ind] = [aggregate_indicator(num_df[num_df["Turistična regija"] == r], ind, pop_col) for r in regions]
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
def build_region_geojson_from_municipalities(geojson_obj: dict, name_prop: str, muni_to_region: dict) -> dict | None:
    if gpd is None or geojson_obj is None:
        return None
    try:
        gdf = gpd.GeoDataFrame.from_features(geojson_obj.get("features", []))
        if gdf.empty:
            return None
        if gdf.crs is None:
            gdf = gdf.set_crs(4326)

        gdf["__obcina__"] = gdf[name_prop].apply(normalize_name)
        gdf["Turistična regija"] = gdf["__obcina__"].map(muni_to_region)
        gdf = gdf[gdf["Turistična regija"].notna()].copy()
        if gdf.empty:
            return None

        reg_gdf = gdf.dissolve(by="Turistična regija", as_index=False)
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

def render_map_regions(regions_geojson: dict, region_to_value: dict, indicator_label: str, height=680):
    if folium is None or regions_geojson is None:
        st.info("Zemljevid ni na voljo (manjka folium ali GeoJSON).")
        return

    # kopija, da ne spreminjamo originalnega geojson-a
    gj = json.loads(json.dumps(regions_geojson))

    # dodamo vrednost v properties za tooltip
    for feat in gj.get("features", []):
        props = feat.get("properties", {}) or {}
        reg = props.get("Turistična regija")
        val = region_to_value.get(reg, np.nan)
        props["_vrednost_fmt"] = format_si_number(val)
        feat["properties"] = props

    m = folium.Map(location=[45.65, 14.82], zoom_start=8, tiles="cartodbpositron", min_zoom=8, max_bounds=True)

    m.options['maxBounds'] = SLO_BOUNDS
    m.options['maxBoundsViscosity'] = 1.0

    vals = [v for v in region_to_value.values() if v is not None and not (isinstance(v, float) and np.isnan(v))]
    vmin = float(np.nanmin(vals)) if vals else 0.0
    vmax = float(np.nanmax(vals)) if vals else 1.0

    def style_fn(feature):
        reg = feature.get("properties", {}).get("Turistična regija")
        val = region_to_value.get(reg, np.nan)
        return {"fillColor": _palette(val, vmin, vmax), "color": "#111111", "weight": 2.2, "fillOpacity": 0.70}

    folium.GeoJson(
        gj,
        name="Turistične regije",
        style_function=style_fn,
        tooltip=folium.GeoJsonTooltip(
            fields=["Turistična regija", "_vrednost_fmt"],
            aliases=["Regija:", f"{indicator_label}:"],
            sticky=True
        )
    ).add_to(m)

    st.components.v1.html(m._repr_html_(), height=height, scrolling=False)

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
            props["_vrednost_fmt"] = format_si_number(val)
            feat["properties"] = props
            feats_in.append(feat)
        else:
            feats_out.append(feat)

    gj_in = {"type": "FeatureCollection", "features": feats_in}
    gj_out = {"type": "FeatureCollection", "features": feats_out}

    m = folium.Map(location=[45.65, 14.82], zoom_start=8, tiles="cartodbpositron", min_zoom=8, max_bounds=True)
    
    m.options['maxBounds'] = SLO_BOUNDS
    m.options['maxBoundsViscosity'] = 1.0

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

    folium.GeoJson(
        gj_in,
        name="Občine (v regiji)",
        style_function=style_in,
        tooltip=folium.GeoJsonTooltip(
            fields=[name_prop, "_vrednost_fmt"],
            aliases=["Občina:", f"{indicator_label}:"],
            sticky=True
        )
    ).add_to(m)

    st.components.v1.html(m._repr_html_(), height=height, scrolling=False)



# ---------------------------
# UI
# ---------------------------
st.set_page_config(page_title="Turistične regije – interaktivni pregled", layout="wide", initial_sidebar_state="collapsed")
st.title("Turistične regije Slovenije – interaktivni pregled")

with st.sidebar:
    st.header("Nastavitve")
    xlsx_file = st.file_uploader("Naloži Excel (če ne uporabiš privzetega)", type=["xlsx"])
    geojson_file = st.file_uploader("Naloži GeoJSON občin (opcijsko)", type=["json", "geojson"])
    st.divider()
    dashboard_mode = st.checkbox("Dashboard način (več indikatorjev)", value=False)


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

meta_cols = {"Občine", "Turistična regija", "__obcina_norm__"}
indicator_cols = [c for c in df.columns if c not in meta_cols]

pop_candidates = [c for c in indicator_cols if "prebival" in c.lower() and "število" in c.lower()]
pop_col = pop_candidates[0] if pop_candidates else None

df_regions = df[df["Turistična regija"].notna()].copy()
regions = sorted(df_regions["Turistična regija"].dropna().unique().tolist())
regions_with_all = ["Vse regije"] + regions

num_df = df_regions.copy()

for c in indicator_cols:
    num_df[c] = parse_numeric(num_df[c])

# GeoJSON občin
if geojson_file is not None:
    try:
        geojson_obj = json.load(geojson_file)
    except Exception:
        geojson_obj = None
else:
    geojson_obj = try_load_geojson(Path(__file__).parent / GEOJSON_DEFAULT)

name_prop = get_geojson_name_prop(geojson_obj) if geojson_obj else None

# mapping občina -> regija (normalizirano)
muni_to_region = {normalize_name(o): r for o, r in zip(df_regions["Občine"], df_regions["Turistična regija"])}

# dropdowni
top_left, top_right = st.columns([1.2, 1])
with top_left:
    selected_region = st.selectbox("Turistična regija", regions_with_all, index=0)
with top_right:
    map_indicator = st.selectbox("Indikator za zemljevid", indicator_cols, index=0 if indicator_cols else None)

dash_inds = []
if dashboard_mode:
    default_inds = indicator_cols[:0] if len(indicator_cols) >= 4 else indicator_cols
    dash_inds = st.multiselect("Indikatorji za dashboard (do 6)", indicator_cols, default=default_inds, max_selections=6, placeholder= "Izberi indikator")

# agregati regij
agg_needed = [map_indicator] + [i for i in dash_inds if i != map_indicator]
region_agg = compute_region_aggregates(num_df, regions, agg_needed, pop_col)
region_to_value_map = dict(zip(region_agg["Turistična regija"], region_agg[map_indicator]))

# regijski geojson (dissolve)
regions_geojson = None
if selected_region == "Vse regije" and geojson_obj and name_prop:
    regions_geojson = build_region_geojson_from_municipalities(geojson_obj, name_prop, muni_to_region)

# KPI / pregled
if selected_region == "Vse regije":
    st.subheader("Primerjava regij")
    cols_to_show = ["Turistična regija"] + agg_needed
    show_df = region_agg[cols_to_show].copy()
    for c in cols_to_show[1:]:
        show_df[c] = show_df[c].apply(lambda x: round(x, 2))
        #show_df[c] = show_df[c].apply(lambda x: format_si_number(x))
    st.dataframe(show_df, use_container_width=True, height=260, hide_index=True)
else:
    st.subheader("Povzetek izbrane regije")

    reg_df = num_df[num_df["Turistična regija"] == selected_region].copy()
    reg_total = aggregate_indicator(reg_df, map_indicator, pop_col)

    # "Slovenija total" – smiselno le za seštevne indikatorje
    sl_total = aggregate_indicator(num_df, map_indicator, pop_col)

    share_si = np.nan
    if (not is_rate_like(map_indicator)) and sl_total and not np.isnan(sl_total) and sl_total != 0:
        share_si = (reg_total / sl_total) * 100.0

    # KPI: prvi je indikator + delež SLO
    left_kpi, right_kpi = st.columns([1.2, 1])
    with left_kpi:
        if not np.isnan(share_si):
            st.metric(map_indicator, f"{format_si_number(reg_total)}", f"Delež Slovenije: {format_pct(share_si, 1)}")
        else:
            st.metric(map_indicator, f"{format_si_number(reg_total)}")
    with right_kpi:
        st.caption("Opomba: »Delež Slovenije« je prikazan za indikatorje, kjer se vrednosti seštevajo (ne za stopnje/indekse).")

    # dodatni KPI-ji (dashboard)
    if dashboard_mode and dash_inds:
        kpi_cols = st.columns(min(6, len(dash_inds)))
        for idx, ind in enumerate(dash_inds[:6]):

            # vrednost regije
            v_reg = float(region_agg.loc[region_agg["Turistična regija"] == selected_region, ind].iloc[0])

            # total Slovenije za ta indikator
            v_slo = aggregate_indicator(num_df, ind, pop_col)

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
                kpi_cols[idx].metric(ind, format_si_number(v_reg))

st.markdown("---")
st.subheader("Zemljevid in razčlenitev")

map_col, table_col = st.columns([2.2, 1.0], gap="large")

with map_col:
    if geojson_obj is None or name_prop is None:
        st.info("Za zemljevid naloži občinski GeoJSON (npr. `si.json`).")
    else:
        if selected_region == "Vse regije":
            if regions_geojson is None:
                print(geojson_obj)
                st.warning("Ne uspem sestaviti poligonov regij (dissolve). Prikazujem občine obarvane po regijski vrednosti.")
                muni_region_val = {m: region_to_value_map.get(r, np.nan) for m, r in muni_to_region.items()}
                render_map_municipalities(geojson_obj, name_prop, set(muni_to_region.keys()), muni_region_val,indicator_label=map_indicator, height=680)
            else:
                render_map_regions(regions_geojson, region_to_value_map,indicator_label=map_indicator, height=680)
        else:
            reg_df = num_df[num_df["Turistična regija"] == selected_region].copy()
            muni_in_region = set(reg_df["__obcina_norm__"].tolist())
            muni_to_value = {normalize_name(o): float(v) for o, v in zip(reg_df["Občine"], reg_df[map_indicator])}
            render_map_municipalities(geojson_obj, name_prop, muni_in_region, muni_to_value,indicator_label=map_indicator, height=680)

with table_col:
    if selected_region == "Vse regije":
        st.markdown("**Tabela regij (izbran indikator)**")
        t = region_agg[["Turistična regija", map_indicator]].copy()
        t = t.sort_values(map_indicator, ascending=False, na_position="last")
        t[map_indicator] = t[map_indicator].apply(lambda x: round(x, 2))
        #t[map_indicator] = t[map_indicator].apply(lambda x: format_si_number(x))
        t = t.rename(columns={map_indicator: "Vrednost"})
        st.dataframe(t, use_container_width=True, height=680, hide_index=True)
    else:
        st.markdown("**Tabela občin (znotraj regije)**")
        reg_df = num_df[num_df["Turistična regija"] == selected_region].copy()
        reg_total = aggregate_indicator(reg_df, map_indicator, pop_col)

        tbl = pd.DataFrame({
            "Občina": reg_df["Občine"].astype(str),
            "Vrednost": reg_df[map_indicator].astype(float)
        })
        if (reg_total and not np.isnan(reg_total) and reg_total != 0 and not is_rate_like(map_indicator)):
            tbl["Delež v regiji (%)"] = round(((tbl["Vrednost"] / reg_total) * 100.0), 2)
        else:
            tbl["Delež v regiji (%)"] = np.nan

        tbl = tbl.sort_values("Vrednost", ascending=False, na_position="last")
        #tbl["Vrednost"] = tbl["Vrednost"].apply(lambda x: format_si_number(x))
        #tbl["Delež v regiji (%)"] = tbl["Delež v regiji (%)"].apply(lambda x: format_si_number(x, 1))
        st.dataframe(tbl, use_container_width=True, height=680, hide_index=True)
    st.caption("Opomba: »Delež v regiji (%)« je prikazan za indikatorje, kjer se vrednosti seštevajo (ne za stopnje/indekse).")

st.caption("Skupni pogled: Skupni podatki za posamezne regije. Posamezna regija: meje občin ter deleži znotraj regije. Dodan je tudi delež Občine glede na Regijo (kjer je smiselno).")
