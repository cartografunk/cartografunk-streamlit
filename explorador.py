"""Explorador público del CPV 2020. Ejecutar con Streamlit."""

from __future__ import annotations

import math
import json
import os
import re
import unicodedata
from pathlib import Path

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd
import pydeck as pdk
from pydeck.bindings.json_tools import default_serialize
import plotly.express as px
import streamlit as st
from shapely.geometry import mapping, shape


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PALETTES = {
    "YlOrRd": ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"],
    "Blues": ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"],
    "BuGn": ["#edf8fb", "#b2e2e2", "#66c2a4", "#2ca25f", "#006d2c"],
    "PuRd": ["#f1eef6", "#d7b5d8", "#df65b0", "#dd1c77", "#980043"],
    "RdPu": ["#feebe2", "#fbb4b9", "#f768a1", "#c51b8a", "#7a0177"],
}
CLASSIFICATION_METHODS = [
    "Cortes naturales (Jenks)",
    "Intervalos iguales",
    "Cuantiles",
    "Desviación estándar",
    "Escala logarítmica",
    "Rupturas bonitas",
]
MISSING_COLOR = [178, 185, 194, 210]
MUNICIPAL_MAP = st.components.v2.component(
    "cartografunk_municipal_map",
    html='<div class="municipal-map"><div class="municipal-map-canvas"></div><div class="municipal-map-status">Preparando mapa…</div></div>',
    css='''.municipal-map{height:400px;position:relative;background:#10131c;border-radius:9px;overflow:hidden}
    .municipal-map-canvas{height:100%;width:100%}
    .municipal-map-status{position:absolute;bottom:10px;left:10px;color:white;background:#10131ccc;padding:4px 8px;font:12px sans-serif;pointer-events:none}''',
    js=(Path(__file__).resolve().parent / "components" / "municipal_map" / "dist" /
        "municipal_map.js").read_text(encoding="utf-8"),
)


class CompactDeck(pdk.Deck):
    """Emit compact JSON; Streamlit sends the return value of to_json()."""

    def to_json(self) -> str:
        return json.dumps(self, default=default_serialize, ensure_ascii=False,
                          sort_keys=True, separators=(",", ":"))
LEVELS = {
    "Estado": ("estatal", "entidad"),
    "Municipio": ("municipal", "municipio"),
    "Metrópoli": ("metropolitano", "zona"),
}
AGE_PATTERN = re.compile(
    r"\bde\s+(\d{1,3})\s+a\s+(\d{1,3})\s+años\b"
    r"|\bde\s+(\d{1,3})\s+años\s+(?:y|o)\s+más\b"
    r"|\bmenor(?:es)?\s+de\s+(\d{1,3})\s+años\b",
    re.IGNORECASE,
)


@st.cache_resource
def duckdb_connection() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(":memory:")


@st.cache_data(show_spinner=False)
def variables() -> pd.DataFrame:
    return pd.read_parquet(DATA / "dim_variable.parquet")


@st.cache_data(show_spinner=False)
def names(level: str) -> pd.DataFrame:
    if level == "metropolitano":
        frame = pd.read_parquet(DATA / "dim_zona.parquet", columns=["cve_zona", "nombre", "tipo"])
        return frame.rename(columns={"cve_zona": "cvegeo"}).assign(nombre_completo=lambda f: f["nombre"])
    dimension_level = "entidad" if level == "estatal" else "municipio"
    frame = pd.read_parquet(
        DATA / "dim_geo.parquet",
        columns=["cvegeo", "nivel", "nombre", "nombre_ent", "nombre_completo", "nombre_corto", "abreviatura", "cve_ent", "en_cpv"],
    )
    return frame.loc[frame["nivel"] == dimension_level].drop(columns="nivel").reset_index(drop=True)


@st.cache_data(show_spinner=False)
def metric(level: str, theme: str, code: str) -> pd.DataFrame:
    # The three parts come exclusively from the published variable dimension.
    path = DATA / "publico" / level / f"{theme}.parquet"
    if not path.is_file() or not code.replace("_", "").isalnum():
        raise ValueError("Variable o nivel no publicado")
    cursor = duckdb_connection().cursor()
    try:
        return cursor.execute(
            f'SELECT cvegeo, "{code}" AS valor FROM read_parquet(?) ORDER BY cvegeo',
            [str(path)],
        ).df()
    finally:
        cursor.close()


@st.cache_data(show_spinner=False)
def rate_per_100k(level: str, theme: str, code: str) -> pd.DataFrame:
    counts = metric(level, theme, code)
    population = metric(level, "poblacion", "pob1").rename(columns={"valor": "poblacion_total"})
    frame = counts.merge(population, on="cvegeo", how="left", validate="one_to_one")
    denominator = frame["poblacion_total"].where(frame["poblacion_total"] > 0)
    frame["valor"] = frame["valor"].astype(float).div(denominator).mul(100_000)
    return frame[["cvegeo", "valor"]]


@st.cache_data(show_spinner=False)
def geometry(level: str, metro_view: str = "Círculos") -> list[tuple[str, dict]]:
    file_name = {
        "estatal": "estatal_visual_5000m.parquet",
        "municipal": "municipal_visual_500m.parquet",
        "metropolitano": ("metropolitana_centroides.parquet" if metro_view == "Círculos"
                           else "metropolitana_huella_urbana.parquet"),
    }[level]
    path = DATA / "geometria" / file_name
    key_column = "cve_zona" if level == "metropolitano" else "cvegeo"
    frame = gpd.read_parquet(path, columns=[key_column, "geometry"])
    result = []
    for key, geom in zip(frame[key_column], frame.geometry):
        mapped = mapping(geom)
        if level in ("municipal", "estatal"):
            # Redondeo exclusivo de la representación enviada al mapa.
            mapped["coordinates"] = round_coordinates(mapped["coordinates"])
        result.append((key, mapped))
    return result


def round_coordinates(value: tuple | list | float) -> tuple | float:
    if isinstance(value, (tuple, list)):
        return tuple(round_coordinates(item) for item in value)
    return round(value, 4)


def rgb(hex_color: str) -> list[int]:
    return [int(hex_color[i : i + 2], 16) for i in (1, 3, 5)] + [215]


def jenks_breaks(values: np.ndarray, classes: int) -> np.ndarray:
    """Exact weighted Fisher–Jenks partition of the distinct sorted values."""
    unique, weights = np.unique(values, return_counts=True)
    count = len(unique)
    classes = min(classes, count)
    if classes == count:
        return unique
    sums = np.r_[0.0, np.cumsum(unique * weights)]
    squares = np.r_[0.0, np.cumsum(unique * unique * weights)]
    totals = np.r_[0, np.cumsum(weights)]
    costs = np.full((classes + 1, count + 1), np.inf)
    previous = np.zeros((classes + 1, count + 1), dtype=int)
    costs[0, 0] = 0.0
    for group in range(1, classes + 1):
        for end in range(group, count + 1):
            starts = np.arange(group - 1, end)
            weight = totals[end] - totals[starts]
            within = squares[end] - squares[starts] - (sums[end] - sums[starts]) ** 2 / weight
            options = costs[group - 1, starts] + np.maximum(within, 0)
            best = int(np.argmin(options))
            costs[group, end] = options[best]
            previous[group, end] = starts[best]
    bounds = []
    end = count
    for group in range(classes, 0, -1):
        start = previous[group, end]
        bounds.append(unique[end - 1])
        end = start
    return np.array(bounds[::-1])


def class_breaks(values: np.ndarray, method: str, classes: int) -> np.ndarray:
    """Return ascending, unique inclusive upper bounds; the last is max(values)."""
    minimum, maximum = float(np.min(values)), float(np.max(values))
    if minimum == maximum:
        return np.array([maximum])
    if method == "Cortes naturales (Jenks)":
        return jenks_breaks(values, classes)
    if method == "Intervalos iguales":
        cuts = np.linspace(minimum, maximum, classes + 1)[1:]
    elif method == "Cuantiles":
        cuts = np.quantile(values, np.linspace(0, 1, classes + 1)[1:])
    elif method == "Desviación estándar":
        mean, deviation = float(np.mean(values)), float(np.std(values))
        cuts = mean + (np.arange(1, classes) - classes / 2) * deviation
    elif method == "Escala logarítmica":
        # log1p retains zero and the signed extension retains negative values.
        transformed = np.sign(values) * np.log1p(np.abs(values))
        grid = np.linspace(float(transformed.min()), float(transformed.max()), classes + 1)[1:]
        cuts = np.sign(grid) * np.expm1(np.abs(grid))
    elif method == "Rupturas bonitas":
        raw_step = (maximum - minimum) / classes
        exponent = math.floor(math.log10(raw_step))
        candidates = sorted({factor * 10 ** power
                             for power in range(exponent - 1, exponent + 3)
                             for factor in (1, 2, 2.5, 5, 10)})
        step = next((candidate for candidate in candidates
                     if candidate >= raw_step and
                     math.ceil(maximum / candidate) - math.floor(minimum / candidate) <= classes),
                    candidates[-1])
        cuts = np.arange(math.floor(minimum / step) + 1,
                         math.ceil(maximum / step) + 1, dtype=float) * step
    else:
        raise ValueError(f"Método de clasificación desconocido: {method}")
    return np.unique(np.r_[np.asarray(cuts)[(np.asarray(cuts) > minimum) &
                                              (np.asarray(cuts) < maximum)], maximum])


def classify(values: pd.Series, palette: str, method: str = CLASSIFICATION_METHODS[0]
             ) -> tuple[dict[str, list[int]], list[tuple[str, float, float, bool]]]:
    valid = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if valid.empty:
        return {key: MISSING_COLOR for key in values.index}, []
    # Si el cero ocupa al menos un quintil, recibe su propia clase.
    own_zero = (valid.eq(0).mean() >= 0.20) and valid.ne(0).any()
    rest = valid.loc[valid.ne(0)] if own_zero else valid
    cuts = class_breaks(rest.to_numpy(dtype=float), method, 4 if own_zero else 5)
    bands = {}
    for key, value in valid.items():
        bands[key] = -1 if own_zero and value == 0 else int(np.searchsorted(cuts[:-1], value, side="left"))
    occupied = sorted(set(bands.values()), key=lambda band: float(valid.loc[
        [key for key, assigned in bands.items() if assigned == band]].min()))
    palette_positions = np.rint(np.linspace(0, 4, len(occupied))).astype(int)
    color_by_band = dict(zip(occupied, (PALETTES[palette][index] for index in palette_positions)))
    colors = {key: rgb(color_by_band[bands[key]]) if key in bands else MISSING_COLOR
              for key in values.index}
    legend_items = []
    for band in occupied:
        observed = valid.loc[[key for key, assigned in bands.items() if assigned == band]]
        legend_items.append((color_by_band[band], float(observed.min()),
                             float(observed.max()), band == -1))
    return colors, legend_items


def format_value(value: float | int | None, unit: str) -> str:
    if value is None or pd.isna(value):
        return "Sin datos CPV"
    if unit == "porcentaje":
        return f"{value:,.2f} %"
    if unit == "por_100k":
        return f"{value:,.1f}"
    if float(value).is_integer():
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def map_features(
    shapes: list[tuple[str, dict]], frame: pd.DataFrame, palette: str, unit: str,
    method: str = CLASSIFICATION_METHODS[0],
) -> tuple[dict, list[tuple[str, float, float, bool]]]:
    values = frame.set_index("cvegeo")["valor"]
    colors, legend_items = classify(values, palette, method)
    records = frame.set_index("cvegeo")
    features = []
    for key, shape in shapes:
        record = records.loc[key]
        value = record["valor"]
        features.append(
            {
                "type": "Feature",
                "geometry": shape,
                "properties": {
                    "cvegeo": key,
                    "nombre": record["nombre_completo"],
                    "valor": format_value(value, unit) + (" por 100 mil habitantes" if unit == "por_100k" and pd.notna(value) else ""),
                    "fill": colors[key],
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}, legend_items


def metro_bubbles(shapes: list[tuple[str, dict]], frame: pd.DataFrame,
                  unit: str, palette: str, method: str = CLASSIFICATION_METHODS[0]
                  ) -> tuple[list[dict], list[tuple[str, float, float, bool]]]:
    records = frame.set_index("cvegeo")
    values = pd.to_numeric(records["valor"], errors="coerce")
    colors, legend_items = classify(values, palette, method)
    nonnegative = values.loc[values.ge(0)].dropna()
    maximum = float(nonnegative.max()) if not nonnegative.empty else 0.0
    points = []
    for key, point in shapes:
        record = records.loc[key]
        value = values.loc[key]
        valid = pd.notna(value) and value >= 0
        radius = max(4.0, 24.0 * math.sqrt(float(value) / maximum)) if valid and maximum > 0 else 4.0
        points.append({
            "position": point["coordinates"], "cvegeo": key,
            "nombre": record["nombre_completo"],
            "valor": format_value(record["valor"], unit)
            + (" por 100 mil habitantes" if unit == "por_100k" and pd.notna(value) else ""),
            "fill": colors[key] if valid else MISSING_COLOR,
            "radio": radius,
        })
    return points, legend_items


def legend(items: list[tuple[str, float, float, bool]], unit: str) -> None:
    if not items:
        return
    labels = []
    for color, lower, upper, is_zero in items:
        range_label = ("0" if is_zero else format_value(lower, unit) if lower == upper
                       else f"{format_value(lower, unit)}–{format_value(upper, unit)}")
        labels.append(
            f'<div style="display:flex;align-items:center;gap:9px;margin:4px 0">'
            f'<span style="display:inline-block;background:{color};width:17px;height:17px;'
            f'border:1px solid #888;flex:none"></span><span>{range_label}</span></div>'
        )
    labels.append('<div style="display:flex;align-items:center;gap:9px;margin:4px 0">'
                  '<span style="display:inline-block;background:#b2b9c2;width:17px;'
                  'height:17px;border:1px solid #888;flex:none"></span><span>Sin CPV</span></div>')
    st.markdown('<div style="line-height:1.35">' + "".join(labels) + '</div>', unsafe_allow_html=True)


def topic_file(topic: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", topic.casefold())
        if not unicodedata.combining(char)
    ).replace(" ", "_")


def grouped_variables(selection: pd.DataFrame) -> pd.DataFrame:
    """Group age and sex breakdowns under a common descriptive concept."""
    catalog = selection.copy()
    groups, details, age_starts, age_ends, sex_orders = [], [], [], [], []
    for description in catalog.descripcion:
        base = re.sub(r"^Porcentaje de\s+", "", description, flags=re.IGNORECASE)
        age = AGE_PATTERN.search(base)
        if age:
            if age.group(1):
                age_start, age_end = int(age.group(1)), int(age.group(2))
                age_label = f"{age_start} a {age_end} años"
            elif age.group(3):
                age_start, age_end = int(age.group(3)), 999
                age_label = f"{age_start} años y más"
            else:
                age_start, age_end = 0, int(age.group(4)) - 1
                age_label = f"Menores de {age.group(4)} años"
        else:
            age_start, age_end, age_label = -1, -1, ""
        if re.search(r"\bfemenina\b", base, re.IGNORECASE):
            sex_label, sex_order = "Mujeres", 1
        elif re.search(r"\bmasculina\b", base, re.IGNORECASE):
            sex_label, sex_order = "Hombres", 2
        else:
            sex_label, sex_order = "Total", 0
        group = AGE_PATTERN.sub("", base)
        group = re.sub(r"\b(?:femenina|masculina)\b", "", group, flags=re.IGNORECASE)
        group = re.sub(r"\s+", " ", group).strip(" ,.;")
        if group.casefold().startswith("población que "):
            group = group[len("población que "):]
        group = group[:1].upper() + group[1:]
        detail = " · ".join(part for part in (age_label, sex_label) if part)
        groups.append(group)
        details.append(detail if age or sex_order else description)
        age_starts.append(age_start)
        age_ends.append(age_end)
        sex_orders.append(sex_order)
    catalog["grupo"] = groups
    catalog["detalle"] = details
    catalog["edad_inicio"] = age_starts
    catalog["edad_fin"] = age_ends
    catalog["orden_sexo"] = sex_orders
    exceptions = pd.read_csv(DATA / "agrupacion_excepciones.csv")
    for row in exceptions.itertuples(index=False):
        matching = catalog["codigo"].eq(row.variable)
        if not matching.any():
            continue
        catalog.loc[matching, "grupo"] = row.grupo_objetivo
        catalog.loc[matching, "detalle"] = row.subgrupo
        age_range = re.search(r"(\d+) a (\d+) años", row.subgrupo)
        age_open = re.search(r"(\d+) años y más", row.subgrupo)
        if age_range:
            catalog.loc[matching, ["edad_inicio", "edad_fin"]] = [int(age_range[1]), int(age_range[2])]
        elif age_open:
            catalog.loc[matching, ["edad_inicio", "edad_fin"]] = [int(age_open[1]), 999]
        catalog.loc[matching, "orden_sexo"] = 1 if "Mujeres" in row.subgrupo else 2 if "Hombres" in row.subgrupo else 0
    return catalog


def select_grouped_variable(selection: pd.DataFrame, suffix: str, preferred: str) -> pd.Series:
    catalog = grouped_variables(selection)
    preferred_group = (catalog.loc[catalog.codigo == preferred, "grupo"].iloc[0]
                       if preferred in catalog.codigo.values else None)
    groups = sorted(catalog.grupo.unique().tolist(), key=str.casefold)
    group_label = "Grupo" if not suffix else f"Grupo · {suffix}"
    group = st.selectbox(group_label, groups,
                         index=groups.index(preferred_group) if preferred_group in groups else 0)
    choices = catalog.loc[catalog.grupo == group].sort_values(
        ["edad_inicio", "edad_fin", "orden_sexo", "descripcion", "codigo"]
    ).copy()
    duplicate_details = choices.detalle.duplicated(keep=False)
    choices.loc[duplicate_details, "detalle"] = choices.loc[duplicate_details, "descripcion"]
    options = choices.codigo.tolist()
    labels = dict(zip(choices.codigo, choices.detalle))
    variable_label = "Edad y sexo" if len(options) > 1 else "Variable"
    if suffix:
        variable_label += f" · {suffix}"
    code = st.selectbox(variable_label, options,
                        index=options.index(preferred) if preferred in options else 0,
                        format_func=lambda candidate: labels[candidate])
    return choices.loc[choices.codigo == code].iloc[0]


def render_map() -> None:
    with st.sidebar:
        level_label = st.selectbox("Nivel", list(LEVELS))
        level, _ = LEVELS[level_label]
        state_code = None
        selected_municipalities = []
        selected_metropolises = []
        if level == "municipal":
            municipal_names = names(level)
            state_names = municipal_names[["cve_ent", "nombre_ent"]].drop_duplicates().sort_values("nombre_ent")
            state_options = {"Elige un estado": None}
            state_options.update(dict(zip(state_names.nombre_ent, state_names.cve_ent)))
            state_filter = st.selectbox("Filtro por estado", list(state_options))
            state_code = state_options[state_filter]
            if state_code:
                candidates = municipal_names.loc[municipal_names.cve_ent == state_code]
                candidate_labels = dict(zip(candidates.cvegeo, candidates.nombre))
                selected_municipalities = st.multiselect(
                    "Buscar y marcar municipios", candidates.cvegeo.tolist(),
                    format_func=lambda key: f"{candidate_labels[key]} · {key}",
                    placeholder="Escribe un nombre; sin selección, todo el estado",
                    key=f"municipios_{state_code}",
                )
        elif level == "metropolitano":
            metro_names = names(level)
            metro_labels = {
                row.cvegeo: f"{row.nombre} · {row.tipo} · {row.cvegeo}"
                for row in metro_names.itertuples(index=False)
            }
            selected_metropolises = st.multiselect(
                "Buscar y marcar metrópolis", metro_names.cvegeo.tolist(),
                format_func=lambda key: metro_labels[key],
                placeholder="Escribe un nombre; sin selección, las 92 zonas",
            )
        all_variables = variables()
        topics = sorted(all_variables["tema"].dropna().unique().tolist())
        default_topic = topics.index("Población") if "Población" in topics else 0
        topic = st.selectbox("Tema", topics, index=default_topic)
        value_type = st.selectbox("Tipo de valor", ["Absoluto", "Relativo", "Tasa por 100 mil habitantes"])
        search = st.text_input("Buscar variable", placeholder="Descripción")
        source_type = "relativo" if value_type == "Relativo" else "absoluto"
        selection = all_variables.loc[
            (all_variables["tema"] == topic) & (all_variables["tipo"] == source_type)
        ].copy()
        if value_type == "Tasa por 100 mil habitantes":
            selection = selection.loc[selection["codigo"] != "pob1"]
        if search:
            selection = selection.loc[
                selection["descripcion"].str.contains(search, case=False, regex=False)
            ]
        if selection.empty:
            st.info("Ninguna variable coincide con la búsqueda.")
            st.stop()
        preferred = {"Absoluto": "pob1", "Relativo": "pob2_r", "Tasa por 100 mil habitantes": "pob2"}[value_type]
        variable = select_grouped_variable(selection, "", preferred)
        code = variable["codigo"]
        method = st.selectbox("Método de clasificación", CLASSIFICATION_METHODS)
        palette = st.selectbox("Paleta ColorBrewer", list(PALETTES))
        metro_view = st.radio("Vista de Metrópoli", ["Círculos", "Huella urbana"],
                              horizontal=True) if level == "metropolitano" else ""

    if level == "municipal" and state_code is None:
        st.info("Elige un estado para mostrar sus municipios. Después puedes buscar y marcar municipios concretos.")
        return
    theme_file = topic_file(topic)
    level_names = names(level)
    if state_code:
        level_names = level_names.loc[level_names.cve_ent == state_code]
        if selected_municipalities:
            level_names = level_names.loc[level_names.cvegeo.isin(selected_municipalities)]
    elif level == "metropolitano" and selected_metropolises:
        level_names = level_names.loc[level_names.cvegeo.isin(selected_metropolises)]
    use_municipal_component = (level == "municipal" and
                               os.getenv("CARTOGRAFUNK_MUNICIPAL_MAP", "deck").lower() != "pydeck")
    with st.spinner("Consultando datos y preparando mapa…", show_time=True):
        metrics = (rate_per_100k(level, theme_file, code)
                   if value_type == "Tasa por 100 mil habitantes"
                   else metric(level, theme_file, code))
        table = level_names.merge(metrics, on="cvegeo", how="left", validate="one_to_one")
        display_unit = "por_100k" if value_type == "Tasa por 100 mil habitantes" else variable["unidad"]
        if use_municipal_component:
            colors, legend_items = classify(table.set_index("cvegeo")["valor"], palette, method)
            rows = [
                {"key": row.cvegeo, "color": colors[row.cvegeo],
                 "name": row.nombre_completo,
                 "value": format_value(row.valor, display_unit) +
                 (" por 100 mil habitantes" if display_unit == "por_100k" and pd.notna(row.valor) else "")}
                for row in table.itertuples(index=False)
            ]
        else:
            shapes = geometry(level, metro_view)
            if level == "metropolitano" and selected_metropolises:
                selected_set = set(selected_metropolises)
                shapes = [(key, geom) for key, geom in shapes if key in selected_set]
            if state_code:
                shapes = [(key, geom) for key, geom in shapes if key.startswith(state_code)]
                if selected_municipalities:
                    selected_set = set(selected_municipalities)
                    shapes = [(key, geom) for key, geom in shapes if key in selected_set]
        if not use_municipal_component and level == "metropolitano" and metro_view == "Círculos":
            points, legend_items = metro_bubbles(shapes, table, display_unit, palette, method)
        elif not use_municipal_component:
            feature_collection, legend_items = map_features(shapes, table, palette, display_unit, method)

    display_name = variable["descripcion"]
    if value_type == "Tasa por 100 mil habitantes":
        display_name += " por 100 mil habitantes"
    st.subheader(display_name)
    summary_parts = [level_label]
    if value_type != "Absoluto":
        summary_parts.append(value_type)
    summary_parts.append(f"{len(table):,} {'unidad' if len(table) == 1 else 'unidades'}")
    summary_parts.append(method)
    if level == "metropolitano" and metro_view == "Círculos":
        summary_parts.append("tamaño según valor")
    st.caption(" · ".join(summary_parts))
    if level == "metropolitano" and metro_view == "Círculos":
        st.caption("Cada punto marca el centroide de la huella urbana de una metrópoli. Su área es proporcional al valor; los valores pequeños tienen un tamaño mínimo visible.")
    elif level == "metropolitano":
        st.caption("Los polígonos muestran la huella urbana de cada metrópoli, no el área municipal completa.")
    if value_type == "Tasa por 100 mil habitantes":
        st.caption("Cálculo: conteo absoluto ÷ población total de la misma unidad geográfica × 100,000.")
    if use_municipal_component:
        MUNICIPAL_MAP(data={
            "geometryUrl": "app/static/municipal_visual_1000m.json",
            "rows": rows, "stateCode": state_code,
            "selectedKeys": selected_municipalities,
            "revision": f"{value_type}:{code}:{method}:{palette}:{state_code}:{','.join(selected_municipalities)}",
            "debug": False,
        }, key="municipal_map")
    else:
        view = pdk.ViewState(latitude=24.0, longitude=-102.5, zoom=2.8, pitch=0)
        if level == "metropolitano" and selected_metropolises:
            if metro_view == "Círculos":
                xs, ys = zip(*(point["position"] for point in points))
                xmin, ymin, xmax, ymax = min(xs), min(ys), max(xs), max(ys)
            else:
                g = gpd.GeoSeries([shape(feature["geometry"]) for feature in feature_collection["features"]])
                xmin, ymin, xmax, ymax = g.total_bounds
            span = max(xmax - xmin, (ymax - ymin) * 1.6, 0.01)
            view = pdk.ViewState(
                latitude=(ymin + ymax) / 2, longitude=(xmin + xmax) / 2,
                zoom=7.5 if len(selected_metropolises) == 1 else
                     max(3.2, min(9.5, math.log2(360 / span) - 1.5)),
                pitch=0,
            )
        if state_code:
            g = gpd.GeoSeries([shape(feature["geometry"]) for feature in feature_collection["features"]])
            if not g.empty:
                xmin, ymin, xmax, ymax = g.total_bounds
                view = pdk.ViewState(
                    latitude=(ymin + ymax) / 2, longitude=(xmin + xmax) / 2,
                    zoom=max(3.2, min(8.5, math.log2(360 / max(xmax - xmin, (ymax - ymin) * 1.6, 0.01)) - 1.5)),
                    pitch=0,
                )
        if level == "metropolitano" and metro_view == "Círculos":
            layer = pdk.Layer(
                "ScatterplotLayer", points, pickable=True, auto_highlight=True,
                stroked=True, filled=True, get_position="position", get_fill_color="fill",
                get_line_color=[242, 238, 255, 220], get_radius="radio",
                radius_units=pdk.types.String("pixels"), line_width_min_pixels=1,
            )
        else:
            layer = pdk.Layer(
                "GeoJsonLayer", feature_collection, pickable=True, auto_highlight=True,
                stroked=True, filled=True, get_fill_color="properties.fill",
                get_line_color=[80, 88, 95, 150],
                line_width_min_pixels=0.5 if level == "metropolitano" else 0.25,
            )
        with st.spinner("Dibujando mapa…", show_time=True):
            deck = CompactDeck(
                layers=[layer], initial_view_state=view,
                tooltip={"html": "<b>{nombre}</b><br>{cvegeo}<br>{valor}"},
                map_style=None,
            )
            st.pydeck_chart(deck, width="stretch", height=400)
    legend(legend_items, display_unit)
    if level == "municipal":
        if "29048" in set(table.cvegeo):
            st.warning(
                "Anomalía de origen: en La Magdalena Tlaltelulco (29048), los porcentajes "
                "de población femenina y masculina figuran como 569.2 % y 559.9 %; los conteos corresponden a "
                "50.41 % y 49.59 %. Se muestran los valores publicados, sin corregirlos."
            )
        missing_cpv = sorted(set(table.loc[table.valor.isna(), "cvegeo"]) & {"02007", "04013"})
        if missing_cpv:
            verb = "se muestra" if len(missing_cpv) == 1 else "se muestran"
            have = "tiene" if len(missing_cpv) == 1 else "tienen"
            st.caption(f"{', '.join(missing_cpv)} {verb} en gris porque no {have} datos CPV.")
    with st.expander("Tabla y descarga del recorte", expanded=True):
        if level == "metropolitano":
            shown = table[["cvegeo", "nombre_completo", "tipo", "valor"]].rename(
                columns={"nombre_completo": "nombre", "valor": display_name}
            )
        else:
            shown = table[["cvegeo", "nombre_completo", "nombre_ent", "valor"]].rename(
                columns={"nombre_completo": "nombre", "nombre_ent": "entidad", "valor": display_name}
            )
        value_format = "%,.0f" if value_type == "Absoluto" else "%,.1f" if value_type == "Tasa por 100 mil habitantes" else "%,.2f"
        if level == "municipal":
            shown = shown.loc[shown[display_name].notna()]
        st.dataframe(shown, hide_index=True, width="stretch", height=330,
                     column_config={display_name: st.column_config.NumberColumn(format=value_format)})
        st.download_button(
            "Descargar CSV", shown.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"cartografunk_{level}_{code}.csv", mime="text/csv",
        )


def compass_axis(axis: str, catalog: pd.DataFrame, default_code: str) -> tuple[pd.Series, str]:
    st.markdown(f"**Eje {axis}**")
    topics = sorted(catalog["tema"].dropna().unique().tolist())
    topic = st.selectbox(f"Tema · {axis}", topics, index=topics.index("Población"))
    value_type = st.selectbox(f"Tipo de valor · {axis}",
                              ["Absoluto", "Relativo", "Tasa por 100 mil habitantes"], index=1)
    search = st.text_input(f"Buscar variable · {axis}", placeholder="Descripción")
    source_type = "relativo" if value_type == "Relativo" else "absoluto"
    selection = catalog.loc[(catalog.tema == topic) & (catalog.tipo == source_type)].copy()
    if value_type == "Tasa por 100 mil habitantes":
        selection = selection.loc[selection.codigo != "pob1"]
    if search:
        selection = selection.loc[
            selection.descripcion.str.contains(search, case=False, regex=False)
        ]
    if selection.empty:
        st.info(f"No hay variables para el eje {axis} con estos filtros.")
        st.stop()
    return select_grouped_variable(selection, axis, default_code), value_type


def compass_values(variable: pd.Series, value_type: str) -> pd.DataFrame:
    code = variable["codigo"]
    theme = topic_file(variable["tema"])
    if value_type == "Tasa por 100 mil habitantes":
        return rate_per_100k("estatal", theme, code)
    return metric("estatal", theme, code)


def compass_label(variable: pd.Series, value_type: str) -> str:
    label = variable["descripcion"]
    if value_type == "Tasa por 100 mil habitantes":
        return f"{label} por 100 mil habitantes"
    if variable["unidad"] == "porcentaje":
        return f"{label} (%)"
    return label


def compass_text_positions(frame: pd.DataFrame) -> dict[str, str]:
    """Spread nearby state abbreviations around their points."""
    positions = ["top center", "bottom center", "middle right", "middle left",
                 "top right", "bottom left", "top left", "bottom right"]
    x = (frame.x.to_numpy() - frame.x.min()) / max(frame.x.max() - frame.x.min(), 1)
    y = (frame.y.to_numpy() - frame.y.min()) / max(frame.y.max() - frame.y.min(), 1)
    density = [int(np.sum((np.abs(x - x[i]) < 0.10) & (np.abs(y - y[i]) < 0.10)))
               for i in range(len(frame))]
    assigned: dict[int, str] = {}
    for i in sorted(range(len(frame)), key=lambda row: -density[row]):
        nearby = {assigned[j] for j in assigned
                  if abs(x[i] - x[j]) < 0.10 and abs(y[i] - y[j]) < 0.10}
        assigned[i] = next((position for position in positions if position not in nearby),
                           positions[i % len(positions)])
    return dict(zip(frame.abreviatura, (assigned[i] for i in range(len(frame)))))


def render_compass() -> None:
    st.subheader("Compass · estados")
    st.caption("Compara dos indicadores o índices del Censo 2020. Las líneas marcan la mediana de cada eje.")
    catalog = variables()
    left, right = st.columns(2)
    with left:
        x_variable, x_type = compass_axis("X", catalog, "pob132_r")
    with right:
        y_variable, y_type = compass_axis("Y", catalog, "pob126_r")

    x_label = compass_label(x_variable, x_type)
    y_label = compass_label(y_variable, y_type)
    frame = names("estatal")[["cvegeo", "nombre", "abreviatura"]]
    frame = frame.merge(compass_values(x_variable, x_type).rename(columns={"valor": "x"}),
                        on="cvegeo", how="left", validate="one_to_one")
    frame = frame.merge(compass_values(y_variable, y_type).rename(columns={"valor": "y"}),
                        on="cvegeo", how="left", validate="one_to_one")
    plot = frame.dropna(subset=["x", "y"]).copy()
    if plot.empty:
        st.info("No hay estados con valores para ambos ejes.")
        return
    x_median = float(plot.x.median())
    y_median = float(plot.y.median())
    plot["cuadrante"] = np.select(
        [
            (plot.x >= x_median) & (plot.y >= y_median),
            (plot.x >= x_median) & (plot.y < y_median),
            (plot.x < x_median) & (plot.y >= y_median),
        ],
        ["↑ X · ↑ Y", "↑ X · ↓ Y", "↓ X · ↑ Y"],
        default="↓ X · ↓ Y",
    )
    colors = {"↑ X · ↑ Y": "#ef4444", "↑ X · ↓ Y": "#f59e0b",
              "↓ X · ↑ Y": "#3b82f6", "↓ X · ↓ Y": "#14b8a6"}
    fig = px.scatter(
        plot, x="x", y="y", color="cuadrante", text="abreviatura",
        hover_name="nombre", hover_data={"cvegeo": True, "x": ":,.2f", "y": ":,.2f", "cuadrante": False},
        labels={"x": x_label, "y": y_label, "cuadrante": "Cuadrante"},
        color_discrete_map=colors,
    )
    fig.update_traces(marker={"size": 11, "line": {"width": 1, "color": "white"}},
                      textfont={"size": 10}, cliponaxis=False)
    text_positions = compass_text_positions(plot)
    for trace in fig.data:
        trace.textposition = [text_positions[label] for label in trace.text]
    fig.add_vline(x=x_median, line_dash="dash", line_color="#9ca3af")
    fig.add_hline(y=y_median, line_dash="dash", line_color="#9ca3af")
    fig.update_layout(height=620, margin={"l": 30, "r": 25, "t": 45, "b": 45},
                      legend={"orientation": "h", "y": -0.18, "x": 0})
    st.plotly_chart(fig, width="stretch", key="compass_scatter")
    st.caption(f"32 estados · Mediana X: {x_median:,.2f} · Mediana Y: {y_median:,.2f}. "
               "Alto/bajo indica posición respecto a la mediana, no una valoración.")
    if x_type == "Tasa por 100 mil habitantes" or y_type == "Tasa por 100 mil habitantes":
        st.caption("Tasa = conteo absoluto ÷ población total del estado × 100,000.")
    shown = plot[["cvegeo", "nombre", "x", "y", "cuadrante"]].rename(
        columns={"x": x_label, "y": y_label})
    with st.expander("Datos del compass"):
        st.dataframe(shown, hide_index=True, width="stretch",
                     column_config={x_label: st.column_config.NumberColumn(format="%,.2f"),
                                    y_label: st.column_config.NumberColumn(format="%,.2f")})
        st.download_button("Descargar CSV del compass", shown.to_csv(index=False).encode("utf-8-sig"),
                           file_name="cartografunk_compass_estados.csv", mime="text/csv")


def main() -> None:
    st.set_page_config(
        page_title="Haz tu propio mapa · Cartografunk",
        page_icon=str(ROOT / "assets" / "img" / "favicon.webp"),
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown("<style>.block-container{padding-top:1.25rem}</style>", unsafe_allow_html=True)
    st.title("Haz tu propio mapa")
    map_tab, compass_tab = st.tabs(["Mapa", "Compass"], on_change="rerun")
    if map_tab.open:
        with map_tab:
            render_map()
    if compass_tab.open:
        with compass_tab:
            render_compass()
    st.caption(
        "Fuentes: Datos y geografía: Censo de Población y Vivienda INEGI "
        "(2020) y Marco Geoestadístico Nacional INEGI (2025). "
        "Paletas: ColorBrewer 2.0."
    )


if __name__ == "__main__":
    main()
