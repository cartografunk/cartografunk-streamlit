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


CRIME_KINDS = {
    "Incidencia delictiva": "fuero_comun_estatal",
    "Víctimas": "victimas_estatal",
}
CRIME_YEARS = list(range(2015, 2026))
CRIME_RATE = "Tasa por 100 mil (CPV 2020)"


@st.cache_data(show_spinner=False)
def crime_catalog() -> pd.DataFrame:
    return pd.read_parquet(DATA / "crimen_sesnsp" / "dim_delito.parquet")


def crime_path(kind: str) -> str:
    if kind not in ("fuero_comun_estatal", "fuero_comun_municipal", "victimas_estatal"):
        raise ValueError("Fuente SESNSP desconocida")
    return str(DATA / "crimen_sesnsp" / kind / "anio=*" / "*.parquet")


@st.cache_data(show_spinner=False)
def crime_population(level: str) -> pd.DataFrame:
    if level not in ("estatal", "municipal"):
        raise ValueError("Nivel sin denominador CPV 2020")
    frame = pd.read_parquet(DATA / "publico" / level / "poblacion.parquet",
                            columns=["cvegeo", "pob1"])
    return frame.rename(columns={"pob1": "poblacion_cpv2020"})


def crime_conditions(kind: str, sexo: str, edad: str) -> tuple[str, list[str]]:
    clauses = []
    params = []
    if kind == "victimas_estatal":
        if sexo != "Todos":
            clauses.append("sexo = ?")
            params.append(sexo)
        if edad != "Todas":
            clauses.append("grupo_edad = ?")
            params.append(edad)
    return (" AND " + " AND ".join(clauses) if clauses else ""), params


@st.cache_data(show_spinner=False)
def crime_counts(kind: str, code: str, first: int, last: int,
                 sexo: str = "Todos", edad: str = "Todas") -> pd.DataFrame:
    extra, params = crime_conditions(kind, sexo, edad)
    cursor = duckdb_connection().cursor()
    try:
        return cursor.execute(f"""
            SELECT cvegeo, cve_ent,
                   CASE WHEN count(*) FILTER (WHERE conteo IS NULL OR conteo < 0) > 0
                        THEN NULL ELSE sum(conteo) END AS valor
            FROM read_parquet(?, hive_partitioning=true)
            WHERE codigo_delito = ? AND anio BETWEEN ? AND ? {extra}
            GROUP BY cvegeo, cve_ent ORDER BY cvegeo
        """, [crime_path(kind), code, first, last, *params]).df()
    finally:
        cursor.close()


@st.cache_data(show_spinner=False)
def crime_values(kind: str, code: str, first: int, last: int,
                 measure: str, sexo: str = "Todos", edad: str = "Todas") -> pd.DataFrame:
    current = crime_counts(kind, code, first, last, sexo, edad)
    if measure == "Conteo":
        return current
    if measure == CRIME_RATE:
        if kind == "victimas_estatal" and (sexo != "Todos" or edad != "Todas"):
            raise ValueError("La tasa de víctimas requiere todos los sexos y edades")
        level = "municipal" if kind == "fuero_comun_municipal" else "estatal"
        frame = current.merge(crime_population(level), on="cvegeo", how="left",
                              validate="one_to_one")
        denominator = frame.poblacion_cpv2020.where(frame.poblacion_cpv2020 > 0)
        frame["valor"] = frame.valor.div(denominator).div(last - first + 1).mul(100_000)
        return frame[["cvegeo", "cve_ent", "valor"]]
    if measure == "% del historial 2015–2025":
        history = crime_counts(kind, code, 2015, 2025, sexo, edad)
        frame = current.merge(history[["cvegeo", "valor"]].rename(columns={"valor": "denominador"}),
                              on="cvegeo", validate="one_to_one")
    elif measure == "% del estado" and kind == "fuero_comun_municipal":
        state = crime_counts("fuero_comun_estatal", code, first, last)
        frame = current.merge(state[["cve_ent", "valor"]].rename(columns={"valor": "denominador"}),
                              on="cve_ent", validate="many_to_one")
    else:
        raise ValueError("Medida SESNSP no disponible para esta fuente")
    frame["valor"] = frame["valor"].div(frame["denominador"].where(frame["denominador"] > 0)).mul(100)
    return frame[["cvegeo", "cve_ent", "valor"]]


@st.cache_data(show_spinner=False)
def crime_series(kind: str, code: str, state: str, keys: tuple[str, ...],
                 sexo: str = "Todos", edad: str = "Todas") -> pd.DataFrame:
    extra, params = crime_conditions(kind, sexo, edad)
    filter_keys = " AND cvegeo IN (" + ",".join("?" for _ in keys) + ")" if keys else ""
    cursor = duckdb_connection().cursor()
    try:
        return cursor.execute(f"""
            SELECT periodo,
                   CASE WHEN count(*) FILTER (WHERE conteo IS NULL OR conteo < 0) > 0
                        THEN NULL ELSE sum(conteo) END AS conteo
            FROM read_parquet(?, hive_partitioning=true)
            WHERE codigo_delito = ? AND cve_ent = ? {filter_keys} {extra}
            GROUP BY periodo ORDER BY periodo
        """, [crime_path(kind), code, state, *keys, *params]).df()
    finally:
        cursor.close()


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
        return "Sin datos"
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


def legend(items: list[tuple[str, float, float, bool]], unit: str,
           missing_label: str = "Sin CPV") -> None:
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
                  f'height:17px;border:1px solid #888;flex:none"></span><span>{missing_label}</span></div>')
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


def code_sort_key(code: str) -> tuple[str, int, int]:
    """Keep SCINCE codes in their published numeric sequence."""
    match = re.fullmatch(r"([a-z]+)(\d+)(_r)?", code.casefold())
    if match:
        return match.group(1), int(match.group(2)), bool(match.group(3))
    return code.casefold(), -1, 0


def select_grouped_variable(selection: pd.DataFrame, suffix: str, preferred: str) -> pd.Series:
    catalog = grouped_variables(selection)
    preferred_group = (catalog.loc[catalog.codigo == preferred, "grupo"].iloc[0]
                       if preferred in catalog.codigo.values else None)
    first_code = catalog.groupby("grupo")["codigo"].agg(
        lambda codes: min(code_sort_key(code) for code in codes)
    )
    groups = sorted(first_code.index.tolist(), key=lambda group: (first_code[group], group.casefold()))
    group_label = "Grupo" if not suffix else f"Grupo · {suffix}"
    group = st.selectbox(group_label, groups,
                         index=groups.index(preferred_group) if preferred_group in groups else 0)
    choices = catalog.loc[catalog.grupo == group].copy()
    choices["orden_codigo"] = choices.codigo.map(code_sort_key)
    choices = choices.sort_values("orden_codigo")
    duplicate_details = choices.detalle.duplicated(keep=False)
    choices.loc[duplicate_details, "detalle"] = choices.loc[duplicate_details, "descripcion"]
    options = choices.codigo.tolist()
    labels = dict(zip(choices.codigo, choices.detalle))
    variable_label = "Edad y sexo" if len(options) > 1 else "Variable"
    if suffix:
        variable_label += f" · {suffix}"
    code = st.selectbox(variable_label, options,
                        index=options.index(preferred) if preferred in options else 0,
                        format_func=lambda candidate: f"{candidate.upper()} · {labels[candidate]}")
    selected = choices.loc[choices.codigo == code].iloc[0]
    st.caption(f"Descripción del catálogo · {code.upper()}: {selected['descripcion']}")
    return selected


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
                get_line_color=[255, 255, 255, 230],
                line_width_min_pixels=0.75,
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


def render_graph() -> None:
    st.subheader("Gráfica")
    with st.sidebar:
        level_label = st.selectbox("Nivel", list(LEVELS), key="grafica_nivel")
        level, _ = LEVELS[level_label]
        state_code = None
        selected_keys = []
        if level == "municipal":
            municipal_names = names(level)
            states = municipal_names[["cve_ent", "nombre_ent"]].drop_duplicates().sort_values("nombre_ent")
            state_options = {"Elige un estado": None}
            state_options.update(dict(zip(states.nombre_ent, states.cve_ent)))
            state_code = state_options[st.selectbox("Filtro por estado", list(state_options), key="grafica_estado")]
            if state_code:
                candidates = municipal_names.loc[municipal_names.cve_ent == state_code]
                labels = dict(zip(candidates.cvegeo, candidates.nombre))
                selected_keys = st.multiselect(
                    "Buscar y marcar municipios", candidates.cvegeo.tolist(),
                    format_func=lambda key: f"{labels[key]} · {key}",
                    placeholder="Sin selección, todo el estado", key=f"grafica_municipios_{state_code}",
                )
        elif level == "metropolitano":
            metro_names = names(level)
            labels = dict(zip(metro_names.cvegeo, metro_names.nombre))
            selected_keys = st.multiselect(
                "Buscar y marcar metrópolis", metro_names.cvegeo.tolist(),
                format_func=lambda key: f"{labels[key]} · {key}",
                placeholder="Sin selección, las 92 zonas", key="grafica_metro",
            )
        catalog = variables()
        topics = sorted(catalog.tema.dropna().unique().tolist())
        topic = st.selectbox("Tema", topics, index=topics.index("Población"), key="grafica_tema")
        value_type = st.selectbox(
            "Tipo de valor", ["Absoluto", "Relativo", "Tasa por 100 mil habitantes"],
            key="grafica_tipo",
        )
        search = st.text_input("Buscar variable", placeholder="Descripción", key="grafica_buscar")
        source_type = "relativo" if value_type == "Relativo" else "absoluto"
        selection = catalog.loc[(catalog.tema == topic) & (catalog.tipo == source_type)].copy()
        if value_type == "Tasa por 100 mil habitantes":
            selection = selection.loc[selection.codigo != "pob1"]
        if search:
            selection = selection.loc[selection.descripcion.str.contains(search, case=False, regex=False)]
        if selection.empty:
            st.info("Ninguna variable coincide con la búsqueda.")
            return
        preferred = {"Absoluto": "pob1", "Relativo": "pob2_r", "Tasa por 100 mil habitantes": "pob2"}[value_type]
        variable = select_grouped_variable(selection, "", preferred)

    if level == "municipal" and state_code is None:
        st.info("Elige un estado para graficar sus municipios.")
        return

    left, middle, right = st.columns(3)
    with left:
        chart_type = st.selectbox("Tipo de gráfica", ["Barras", "Línea"])
    with middle:
        orientation = st.selectbox("Orientación", ["Vertical", "Horizontal"],
                                   disabled=chart_type == "Línea")
    with right:
        sort_by = st.selectbox("Orden de unidades", ["Valor (mayor a menor)", "CVEGEO", "Nombre"])
    limit = st.selectbox("Mostrar unidades", [20, 50, 100, "Todas"],
                         index=1 if level == "municipal" else 3)

    level_names = names(level)
    if state_code:
        level_names = level_names.loc[level_names.cve_ent == state_code]
    if selected_keys:
        level_names = level_names.loc[level_names.cvegeo.isin(selected_keys)]
    with st.spinner("Preparando gráfica…", show_time=True):
        values = (rate_per_100k(level, topic_file(topic), variable["codigo"])
                  if value_type == "Tasa por 100 mil habitantes"
                  else metric(level, topic_file(topic), variable["codigo"]))
        frame = level_names.merge(values, on="cvegeo", how="left", validate="one_to_one")
        frame = frame.loc[frame.valor.notna()].copy()
    if frame.empty:
        st.info("No hay valores para esta selección.")
        return
    if sort_by == "Valor (mayor a menor)":
        frame = frame.sort_values(["valor", "cvegeo"], ascending=[False, True])
    elif sort_by == "Nombre":
        frame = frame.sort_values("nombre_completo")
    else:
        frame = frame.sort_values("cvegeo")
    if limit != "Todas":
        frame = frame.head(limit)

    label = compass_label(variable, value_type)
    frame["descripcion_catalogo"] = variable["descripcion"]
    if chart_type == "Barras" and orientation == "Horizontal":
        fig = px.bar(frame, x="valor", y="nombre_completo", orientation="h",
                     custom_data=["cvegeo", "descripcion_catalogo"],
                     labels={"valor": label, "nombre_completo": level_label})
        fig.update_yaxes(categoryorder="array", categoryarray=frame.nombre_completo.iloc[::-1].tolist())
        value_axis = "x"
    elif chart_type == "Barras":
        fig = px.bar(frame, x="nombre_completo", y="valor",
                     custom_data=["cvegeo", "descripcion_catalogo"],
                     labels={"valor": label, "nombre_completo": level_label})
        value_axis = "y"
    else:
        fig = px.line(frame, x="nombre_completo", y="valor", markers=True,
                      custom_data=["cvegeo", "descripcion_catalogo"],
                      labels={"valor": label, "nombre_completo": level_label})
        value_axis = "y"
        st.caption("La línea conecta unidades geográficas en el orden elegido; no representa una serie temporal.")
    fig.update_traces(
        hovertemplate=f"<b>%{{customdata[0]}}</b><br>%{{customdata[1]}}<br>{label}: "
                      f"%{{{value_axis}:,.2f}}<extra></extra>"
    )
    fig.update_layout(height=max(450, min(1200, 30 * len(frame) + 120))
                      if orientation == "Horizontal" and chart_type == "Barras" else 520,
                      margin={"l": 25, "r": 25, "t": 30, "b": 80})
    if not (chart_type == "Barras" and orientation == "Horizontal"):
        fig.update_xaxes(tickangle=-45)
    st.plotly_chart(fig, width="stretch", key="grafica_univariable")
    st.caption(f"{len(frame):,} unidades con valor · {variable['codigo'].upper()} · {variable['descripcion']}")
    with st.expander("Datos de la gráfica"):
        shown = frame[["cvegeo", "nombre_completo", "valor"]].rename(
            columns={"nombre_completo": "nombre", "valor": label})
        st.dataframe(shown, hide_index=True, width="stretch")
        st.download_button("Descargar CSV", shown.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"cartografunk_grafica_{level}_{variable['codigo']}.csv",
                           mime="text/csv")


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


def crime_picker(suffix: str, kind: str) -> tuple[str, str]:
    catalog = crime_catalog()
    flag = "en_victimas" if kind == "victimas_estatal" else "en_fuero_comun"
    catalog = catalog.loc[catalog[flag]].copy()
    labels = {row.codigo_delito: f"{row.tipo} · {row.subtipo} · {row.modalidad}"
              for row in catalog.itertuples(index=False)}
    if suffix == "compass_y":
        preferred = catalog.loc[catalog.tipo.str.contains("Extorsión", case=False,
                                                           regex=False), "codigo_delito"]
    else:
        preferred = catalog.loc[
            catalog.subtipo.str.contains("Homicidio doloso", case=False, regex=False) &
            catalog.modalidad.str.contains("arma de fuego", case=False, regex=False),
            "codigo_delito",
        ]
    options = catalog.codigo_delito.tolist()
    code = st.selectbox("Delito", options,
                        index=options.index(preferred.iloc[0]) if not preferred.empty else 0,
                        format_func=lambda key: labels[key], key=f"sesnsp_{suffix}_delito")
    return code, labels[code]


@st.cache_data(show_spinner=False)
def crime_victim_strata() -> list[tuple[str, str]]:
    cursor = duckdb_connection().cursor()
    try:
        rows = cursor.execute("""
            SELECT DISTINCT sexo, grupo_edad FROM read_parquet(?, hive_partitioning=true)
            ORDER BY sexo, grupo_edad
        """, [crime_path("victimas_estatal")]).fetchall()
        return rows
    finally:
        cursor.close()


def crime_strata(kind: str, suffix: str) -> tuple[str, str]:
    if kind != "victimas_estatal":
        return "Todos", "Todas"
    pairs = crime_victim_strata()
    sex = st.selectbox("Sexo", ["Todos", *sorted({row[0] for row in pairs})],
                       key=f"sesnsp_{suffix}_sexo")
    ages = sorted({row[1] for row in pairs if sex == "Todos" or row[0] == sex})
    age = st.selectbox("Edad", ["Todas", *ages], key=f"sesnsp_{suffix}_edad")
    return sex, age


def crime_state_picker(suffix: str) -> str | None:
    states = names("estatal").sort_values("nombre")
    labels = dict(zip(states.cvegeo, states.nombre))
    code = st.selectbox("Filtro por estado", ["", *states.cvegeo.tolist()],
                        format_func=lambda key: labels.get(key, "Elige un estado"),
                        key=f"sesnsp_{suffix}_estado")
    return code or None


def render_crime_map() -> None:
    with st.sidebar:
        source_label = st.selectbox("Registro", list(CRIME_KINDS), key="sesnsp_mapa_fuente")
        kind = CRIME_KINDS[source_label]
        level_label = st.selectbox("Nivel", ["Estado"] if kind == "victimas_estatal"
                                   else ["Estado", "Municipio"], key="sesnsp_mapa_nivel")
        level = LEVELS[level_label][0]
        state = crime_state_picker("mapa") if level == "municipal" else None
        chosen = []
        if state:
            candidates = names("municipal").loc[lambda frame: frame.cve_ent == state]
            labels = dict(zip(candidates.cvegeo, candidates.nombre))
            chosen = st.multiselect("Buscar y marcar municipios", candidates.cvegeo.tolist(),
                                    format_func=lambda key: f"{labels[key]} · {key}",
                                    placeholder="Sin selección, todo el estado",
                                    key=f"sesnsp_mapa_municipios_{state}")
        code, label = crime_picker("mapa", kind)
        sex, age = crime_strata(kind, "mapa")
        choices = ["Conteo", "% del historial 2015–2025"]
        if kind != "victimas_estatal" or (sex == "Todos" and age == "Todas"):
            choices.insert(1, CRIME_RATE)
        if level == "municipal":
            choices.insert(1, "% del estado")
        measure = st.selectbox("Medida", choices, key="sesnsp_mapa_medida")
        first, last = st.slider("Años", 2020 if measure == CRIME_RATE else 2015,
                                2025, (2025, 2025), key="sesnsp_mapa_anios")
        method = st.selectbox("Método de clasificación", CLASSIFICATION_METHODS,
                              key="sesnsp_mapa_metodo")
        palette = st.selectbox("Paleta ColorBrewer", list(PALETTES),
                               key="sesnsp_mapa_paleta")
    if level == "municipal" and not state:
        st.info("Elige un estado para mostrar sus municipios.")
        return
    with st.spinner("Consultando SESNSP y preparando mapa…", show_time=True):
        source_kind = "fuero_comun_municipal" if level == "municipal" else kind
        values = crime_values(source_kind, code, first, last, measure, sex, age)
        frame = names(level).merge(values[["cvegeo", "valor"]], on="cvegeo", how="left",
                                   validate="one_to_one")
        if state:
            frame = frame.loc[frame.cve_ent == state]
        if chosen:
            frame = frame.loc[frame.cvegeo.isin(chosen)]
        unit = "porcentaje" if measure.startswith("%") else "por_100k" if measure == CRIME_RATE else "conteo"
        if level == "municipal" and os.getenv("CARTOGRAFUNK_MUNICIPAL_MAP", "deck").lower() != "pydeck":
            colors, bands = classify(frame.set_index("cvegeo").valor, palette, method)
            rows = [{"key": row.cvegeo, "color": colors[row.cvegeo],
                     "name": row.nombre_completo,
                     "value": format_value(row.valor, unit) +
                     (" por 100 mil habitantes CPV 2020" if unit == "por_100k" and pd.notna(row.valor) else "")}
                    for row in frame.itertuples(index=False)]
            use_component = True
        else:
            shapes = geometry(level)
            if state:
                shapes = [(key, geom) for key, geom in shapes if key.startswith(state)]
            if chosen:
                selected = set(chosen)
                shapes = [(key, geom) for key, geom in shapes if key in selected]
            feature_collection, bands = map_features(shapes, frame, palette, unit, method)
            use_component = False
    st.subheader(f"{label} · {first}" + (f"–{last}" if last != first else ""))
    st.caption(f"SESNSP · {source_label} · {level_label} · {measure}. "
               "Año de registro de la averiguación o carpeta de investigación.")
    if use_component:
        MUNICIPAL_MAP(data={
            "geometryUrl": "app/static/municipal_visual_1000m.json", "rows": rows,
            "stateCode": state, "selectedKeys": chosen,
            "revision": f"sesnsp:{source_kind}:{code}:{first}:{last}:{measure}:{method}:{palette}:{state}:{','.join(chosen)}",
            "debug": False,
        }, key="sesnsp_municipal_map")
    else:
        layer = pdk.Layer("GeoJsonLayer", feature_collection, pickable=True,
                          auto_highlight=True, stroked=True, filled=True,
                          get_fill_color="properties.fill", get_line_color=[255, 255, 255, 230],
                          line_width_min_pixels=0.75)
        deck = CompactDeck(layers=[layer], initial_view_state=pdk.ViewState(
            latitude=24, longitude=-102.5, zoom=2.8, pitch=0),
            tooltip={"html": "<b>{nombre}</b><br>{cvegeo}<br>{valor}"}, map_style=None)
        st.pydeck_chart(deck, width="stretch", height=400, key="sesnsp_mapa")
    legend(bands, unit)
    if level == "municipal":
        st.caption("Las claves municipales sin geometría en el Marco no se dibujan; "
                   "el denominador de % del estado procede del archivo estatal completo.")
    if measure == CRIME_RATE:
        st.caption("Casos ÷ POB1 del CPV 2020 × 100,000"
                   + (f" ÷ {last - first + 1} años (promedio anual)." if last > first else ".")
                   + " Denominador fijo de 2020: no refleja cambios de población posteriores.")
        if level == "municipal":
            st.caption("POB1 disponible para 2,469 de 2,486 claves municipales SESNSP; "
                       "dos municipios con geometría y sin dato CPV se muestran en gris, "
                       "y 15 claves sin geometría no se dibujan.")
    shown = frame[["cvegeo", "nombre_completo", "valor"]].rename(
        columns={"nombre_completo": "nombre", "valor": measure})
    st.dataframe(shown, hide_index=True, width="stretch")
    st.download_button("Descargar CSV", shown.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"cartografunk_sesnsp_{level}_{code}_{first}_{last}.csv",
                       mime="text/csv", key="sesnsp_mapa_descarga")


def render_crime_graph() -> None:
    st.subheader("Evolución histórica")
    with st.sidebar:
        source_label = st.selectbox("Registro", list(CRIME_KINDS), key="sesnsp_grafica_fuente")
        kind = CRIME_KINDS[source_label]
        level_label = st.selectbox("Nivel", ["Estado"] if kind == "victimas_estatal"
                                   else ["Estado", "Municipio"], key="sesnsp_grafica_nivel")
        state = crime_state_picker("grafica")
        chosen = []
        if state and level_label == "Municipio":
            candidates = names("municipal").loc[lambda frame: frame.cve_ent == state]
            labels = dict(zip(candidates.cvegeo, candidates.nombre))
            chosen = st.multiselect("Buscar y marcar municipios", candidates.cvegeo.tolist(),
                                    format_func=lambda key: f"{labels[key]} · {key}",
                                    placeholder="Sin selección, el total estatal oficial",
                                    key=f"sesnsp_grafica_municipios_{state}")
        code, label = crime_picker("grafica", kind)
        sex, age = crime_strata(kind, "grafica")
        measures = ["Conteo"]
        if kind != "victimas_estatal" or (sex == "Todos" and age == "Todas"):
            measures.append(CRIME_RATE)
        measure = st.selectbox("Medida", measures, key="sesnsp_grafica_medida")
        first, last = st.slider("Años visibles", 2020 if measure == CRIME_RATE else 2015,
                                2025, (2020, 2025) if measure == CRIME_RATE else (2015, 2025),
                                key=f"sesnsp_grafica_anios_{'tasa' if measure == CRIME_RATE else 'conteo'}")
        frequency = st.radio("Frecuencia", ["Mensual", "Anual"], horizontal=True,
                             key="sesnsp_grafica_frecuencia")
        rolling = st.checkbox("Acumulado móvil de 12 meses", value=False,
                              disabled=frequency == "Anual", key="sesnsp_grafica_rolling")
    if not state:
        st.info("Elige un estado para ver su evolución histórica.")
        return
    series_kind = "fuero_comun_municipal" if chosen else kind
    with st.spinner("Consultando la serie histórica…", show_time=True):
        frame = crime_series(series_kind, code, state, tuple(chosen), sex, age)
    if frame.empty:
        st.info("No hay registros para esta selección.")
        return
    frame["fecha"] = pd.to_datetime(frame.periodo + "-01")
    if frequency == "Anual":
        frame["año"] = frame.fecha.dt.year
        frame = frame.groupby("año", as_index=False).agg(
            conteo=("conteo", lambda values: values.sum() if values.notna().all() and len(values) == 12 else np.nan))
        frame["fecha"] = pd.to_datetime(frame["año"].astype(str) + "-01-01")
    elif rolling:
        frame["conteo"] = frame.conteo.rolling(12, min_periods=12).sum()
    if measure == CRIME_RATE:
        if chosen:
            population = crime_population("municipal").loc[lambda table: table.cvegeo.isin(chosen)]
            denominator = (float(population.poblacion_cpv2020.sum())
                           if len(population) == len(chosen) and
                           population.poblacion_cpv2020.notna().all() else np.nan)
        else:
            population = crime_population("estatal").set_index("cvegeo")
            denominator = float(population.loc[state, "poblacion_cpv2020"])
        frame["conteo"] = frame.conteo.div(denominator if denominator > 0 else np.nan).mul(100_000)
    frame = frame.loc[frame.fecha.dt.year.between(first, last)]
    place = (", ".join(names("municipal").set_index("cvegeo").loc[chosen, "nombre"].tolist())
             if chosen else names("estatal").set_index("cvegeo").loc[state, "nombre"])
    rate_note = ("Tasa anual por 100 mil habitantes CPV 2020."
                 if frequency == "Anual" else
                 "Tasa de los últimos 12 meses por 100 mil habitantes CPV 2020."
                 if rolling else "Tasa mensual por 100 mil habitantes CPV 2020.")
    st.caption(f"{source_label} · {place} · {label} · {first}–{last}. "
               "Mes/año de registro. " +
               (rate_note + " La población de 2020 permanece fija."
                if measure == CRIME_RATE else "Conteos registrados."))
    value_label = ("Tasa por 100 mil · CPV 2020" if measure == CRIME_RATE
                   else "Conteo acumulado 12 meses" if rolling and frequency == "Mensual"
                   else "Conteo")
    fig = px.line(frame, x="fecha", y="conteo", markers=frequency == "Anual",
                  labels={"fecha": "Periodo", "conteo": value_label})
    fig.update_traces(hovertemplate="%{x|%Y-%m}<br>%{y:,.2f}<extra></extra>" if measure == CRIME_RATE
                      else "%{x|%Y-%m}<br>%{y:,.0f}<extra></extra>")
    fig.update_layout(height=500, margin={"l": 25, "r": 20, "t": 20, "b": 45})
    st.plotly_chart(fig, width="stretch", key="sesnsp_serie")
    st.dataframe(frame, hide_index=True, width="stretch")
    st.download_button("Descargar CSV", frame.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"cartografunk_sesnsp_serie_{code}.csv", mime="text/csv")


@st.cache_data(show_spinner=False)
def crime_annual(kind: str, code: str, sexo: str, edad: str) -> pd.DataFrame:
    extra, params = crime_conditions(kind, sexo, edad)
    cursor = duckdb_connection().cursor()
    try:
        return cursor.execute(f"""
            SELECT cvegeo, anio,
                   CASE WHEN count(*) FILTER (WHERE conteo IS NULL OR conteo < 0) > 0
                        THEN NULL ELSE sum(conteo) END AS valor
            FROM read_parquet(?, hive_partitioning=true)
            WHERE codigo_delito = ? {extra}
            GROUP BY cvegeo, anio ORDER BY cvegeo, anio
        """, [crime_path(kind), code, *params]).df()
    finally:
        cursor.close()


def render_crime_compass() -> None:
    st.subheader("Compass · estados")
    with st.sidebar:
        source_label = st.selectbox("Registro", list(CRIME_KINDS), key="sesnsp_compass_fuente")
        kind = CRIME_KINDS[source_label]
        st.markdown("**Eje X**")
        x_source = st.selectbox("Fuente · X", ["Censo 2020 · INEGI", "Delitos · SESNSP"],
                                key="sesnsp_compass_x_fuente")
        if x_source == "Censo 2020 · INEGI":
            cpv_catalog = variables()
            topics = sorted(cpv_catalog.tema.dropna().unique().tolist())
            topic = st.selectbox("Tema · X", topics,
                                 index=topics.index("Población"), key="sesnsp_compass_x_tema")
            x_type = st.selectbox("Tipo de valor · X", ["Relativo", "Absoluto"],
                                  key="sesnsp_compass_x_tipo")
            search = st.text_input("Buscar variable · X", key="sesnsp_compass_x_buscar")
            selection = cpv_catalog.loc[
                (cpv_catalog.tema == topic) &
                (cpv_catalog.tipo == ("relativo" if x_type == "Relativo" else "absoluto"))
            ]
            if search:
                selection = selection.loc[selection.descripcion.str.contains(search, case=False,
                                                                             regex=False)]
            if selection.empty:
                st.info("No hay indicadores censales para el eje X con esos filtros.")
                return
            x_variable = select_grouped_variable(selection, "CPV X", "pob132_r")
            x_label = compass_label(x_variable, x_type) + " · CPV 2020"
        else:
            x_code, x_label = crime_picker("compass_x", kind)
        st.markdown("**Eje Y**")
        y_code, y_label = crime_picker("compass_y", kind)
        sex, age = crime_strata(kind, "compass")
        measures = ["Conteo", "% del historial 2015–2025"]
        if kind != "victimas_estatal" or (sex == "Todos" and age == "Todas"):
            measures.insert(1, CRIME_RATE)
        measure = st.selectbox("Medida SESNSP", measures,
                               key="sesnsp_compass_medida")
        year_options = CRIME_YEARS[5:] if measure == CRIME_RATE or x_source == "Censo 2020 · INEGI" else CRIME_YEARS
        year = st.select_slider("Año", options=year_options, value=2025,
                                key=f"sesnsp_compass_anio_{year_options[0]}")
    y_all = crime_annual(kind, y_code, sex, age)
    x_all = crime_annual(kind, x_code, sex, age) if x_source == "Delitos · SESNSP" else None
    if measure == CRIME_RATE:
        population = crime_population("estatal").set_index("cvegeo").poblacion_cpv2020
        for all_years in ([x_all, y_all] if x_all is not None else [y_all]):
            all_years["valor"] = all_years.valor.div(all_years.cvegeo.map(population)).mul(100_000)
    elif measure != "Conteo":
        for all_years in ([x_all, y_all] if x_all is not None else [y_all]):
            totals = all_years.groupby("cvegeo").valor.transform(
                lambda values: values.sum() if values.notna().all() and len(values) == 11 else np.nan)
            all_years["valor"] = all_years.valor.div(totals.where(totals > 0)).mul(100)
    reference_start = 2020 if measure == CRIME_RATE or x_all is None else 2015
    y_reference = y_all.loc[y_all.anio >= reference_start]
    x_reference_years = x_all.loc[x_all.anio >= reference_start] if x_all is not None else None
    x_current = (x_all.loc[x_all.anio == year, ["cvegeo", "valor"]]
                 if x_all is not None else
                 metric("estatal", topic_file(x_variable["tema"]), x_variable["codigo"]))
    x_cut = float((x_reference_years if x_all is not None else x_current).valor.median())
    y_cut = float(y_reference.valor.median())
    frame = names("estatal")[["cvegeo", "nombre", "abreviatura"]]
    frame = frame.merge(x_current.rename(columns={"valor": "x"}),
                        on="cvegeo", how="left", validate="one_to_one")
    frame = frame.merge(y_all.loc[y_all.anio == year, ["cvegeo", "valor"]].rename(columns={"valor": "y"}),
                        on="cvegeo", how="left", validate="one_to_one")
    frame = frame.dropna(subset=["x", "y"])
    if frame.empty:
        st.info("No hay estados con valores para ambos ejes.")
        return
    frame["cuadrante"] = np.select([
        (frame.x >= x_cut) & (frame.y >= y_cut),
        (frame.x >= x_cut) & (frame.y < y_cut),
        (frame.x < x_cut) & (frame.y >= y_cut),
    ], ["↑ X · ↑ Y", "↑ X · ↓ Y", "↓ X · ↑ Y"], default="↓ X · ↓ Y")
    colors = {"↑ X · ↑ Y": "#ef4444", "↑ X · ↓ Y": "#f59e0b",
              "↓ X · ↑ Y": "#3b82f6", "↓ X · ↓ Y": "#14b8a6"}
    fig = px.scatter(frame, x="x", y="y", color="cuadrante", text="abreviatura",
                     hover_name="nombre", hover_data={"cvegeo": True, "x": ":,.2f", "y": ":,.2f"},
                     labels={"x": x_label if x_all is None else f"{x_label} · {measure}",
                             "y": f"{y_label} · {measure}"},
                     color_discrete_map=colors)
    fig.update_traces(marker={"size": 11, "line": {"width": 1, "color": "white"}},
                      textfont={"size": 10}, cliponaxis=False)
    positions = compass_text_positions(frame)
    for trace in fig.data:
        trace.textposition = [positions[label] for label in trace.text]
    fig.add_vline(x=x_cut, line_dash="dash", line_color="#9ca3af")
    fig.add_hline(y=y_cut, line_dash="dash", line_color="#9ca3af")
    x_reference = x_reference_years if x_all is not None else x_current
    fig.update_xaxes(range=[min(0, float(x_reference.valor.min()) * 0.95),
                            max(float(x_reference.valor.max()) * 1.05, 1)])
    fig.update_yaxes(range=[0, max(float(y_reference.valor.max()) * 1.05, 1)])
    fig.update_layout(height=620, margin={"l": 25, "r": 20, "t": 30, "b": 45})
    st.plotly_chart(fig, width="stretch", key="sesnsp_compass")
    st.caption(f"{year} · {source_label}. Cortes fijos: X {x_cut:,.2f}; Y {y_cut:,.2f}. "
               + ("X es el valor fijo del Censo 2020; solo cambia Y al mover el año. "
                  if x_all is None else f"Ambos cortes proceden de los 32 estados × {2026-reference_start} años. ")
               + ("Tasa por 100 mil con población fija del CPV 2020."
                  if measure == CRIME_RATE else "La medida SESNSP no es una tasa poblacional."))
    st.dataframe(frame[["cvegeo", "nombre", "x", "y", "cuadrante"]],
                 hide_index=True, width="stretch")


SIACON_SECTORS = {
    "Agricultura": {"estatal": "agro_cierre_estatal", "municipal": "agro_cierre_municipal"},
    "Ganadería": {"estatal": "peco_cierre_estatal", "municipal": "peco_cierre_municipal"},
    "Pesca": {"estatal": "peso_cierre_estatal"},
}
SIACON_METRICS = {
    "Agricultura": {
        "Superficie sembrada": "sembrada", "Superficie cosechada": "cosechada",
        "Superficie siniestrada": "siniestrada", "Volumen de producción": "volumenproduccion",
        "Valor de producción": "valorproduccion",
    },
    "Ganadería": {
        "Volumen en pie": "volumenpie", "Volumen en canal": "volumencanal",
        "Valor en pie": "valorpie", "Valor en canal": "valorcanal",
        "Inventario": "inventario", "Número de cabezas": "numerocabezas",
    },
    "Pesca": {
        "Peso vivo": "pesovivo", "Peso desembarcado": "pesodesembarque",
        "Valor": "valor",
    },
}
SIACON_YEARS = {"Agricultura": {"estatal": (1980, 2024), "municipal": (2003, 2024)},
                "Ganadería": {"estatal": (1980, 2024), "municipal": (2006, 2024)},
                "Pesca": {"estatal": (2011, 2018)}}


@st.cache_data(show_spinner=False)
def siacon_catalog(table: str) -> pd.DataFrame:
    allowed = {"cat_cultivo", "cat_producto", "cat_especie", "cat_especiepesquero",
               "cat_unidadmedida"}
    if table not in allowed:
        raise ValueError("Catálogo SIACON desconocido")
    return pd.read_parquet(DATA / "siacon" / "catalogos" / f"{table}.parquet")


def siacon_source(sector: str, level: str) -> str:
    return SIACON_SECTORS[sector][level]


@st.cache_data(show_spinner=False)
def siacon_available(sector: str, level: str) -> pd.DataFrame:
    table = siacon_source(sector, level)
    path = str(DATA / "siacon" / table / "anio=*" / "*.parquet")
    if sector == "Agricultura":
        columns = "idcultivo, idunidadmedida"
    elif sector == "Ganadería":
        columns = "idespecie, idproducto"
    else:
        columns = "idespecie"
    cursor = duckdb_connection().cursor()
    try:
        return cursor.execute(f"SELECT DISTINCT {columns} FROM read_parquet(?, hive_partitioning=false)",
                              [path]).df()
    finally:
        cursor.close()


@st.cache_data(show_spinner=False)
def siacon_annual(sector: str, level: str, category: int,
                  product: int | None, metric: str) -> pd.DataFrame:
    if metric not in SIACON_METRICS[sector].values():
        raise ValueError("Métrica SIACON desconocida")
    table = siacon_source(sector, level)
    path = str(DATA / "siacon" / table / "anio=*" / "*.parquet")
    if sector == "Agricultura":
        column, conditions = "idcultivo", ""
        params = [path, category]
        if product is not None:
            conditions = " AND idunidadmedida = ?"
            params.append(product)
    elif sector == "Ganadería":
        column, conditions = "idespecie", " AND idproducto = ?"
        params = [path, category, product]
    else:
        column, conditions = "idespecie", ""
        params = [path, category]
    cursor = duckdb_connection().cursor()
    try:
        return cursor.execute(f"""
            SELECT cvegeo, anio,
                   CASE WHEN count(*) FILTER (WHERE {metric} IS NULL) > 0 THEN NULL
                        ELSE sum({metric}) END AS valor
            FROM read_parquet(?, hive_partitioning=false)
            WHERE {column} = ? {conditions}
            GROUP BY cvegeo, anio ORDER BY cvegeo, anio
        """, params).df()
    finally:
        cursor.close()


def siacon_picker(suffix: str, *, compass: bool = False, series: bool = False) -> dict:
    sector = st.selectbox("Sector", list(SIACON_SECTORS), key=f"siacon_{suffix}_sector")
    levels = ["Estado"] if sector == "Pesca" or compass else ["Estado", "Municipio"]
    level_label = st.selectbox("Nivel", levels, key=f"siacon_{suffix}_nivel")
    level = LEVELS[level_label][0]
    years = SIACON_YEARS[sector][level]
    product = None
    if sector == "Agricultura":
        available = siacon_available(sector, level)
        catalog = siacon_catalog("cat_cultivo").loc[
            lambda frame: frame.idcultivo.isin(available.idcultivo)].sort_values("nomcultivo")
        labels = dict(zip(catalog.idcultivo, catalog.nomcultivo))
        category = st.selectbox("Cultivo", catalog.idcultivo.tolist(),
                                format_func=lambda key: f"{labels[key]} · {key}",
                                index=(catalog.idcultivo.tolist().index(7490000)
                                       if 7490000 in catalog.idcultivo.tolist() else 0),
                                key=f"siacon_{suffix}_cultivo")
        # One crop has multiple recorded production units. Keep them separate.
        units = siacon_catalog("cat_unidadmedida").set_index("idunidadmedida")
        candidates = available.loc[
            available.idcultivo == category, "idunidadmedida"].dropna().unique().tolist()
        if len(candidates) > 1:
            product = st.selectbox("Unidad de producción", sorted(candidates),
                                   format_func=lambda key: str(units.loc[key, "nomunidad"]),
                                   key=f"siacon_{suffix}_unidad")
        else:
            product = int(candidates[0])
        unit_name = (str(units.loc[product, "nomcorto"]).strip() if product in units.index
                     else "unidad de la fuente")
        label = labels[category]
    elif sector == "Ganadería":
        available = siacon_available(sector, level)
        species = siacon_catalog("cat_especie").loc[
            lambda frame: frame.idespecie.isin(available.idespecie)].sort_values("ordenreporte")
        labels = dict(zip(species.idespecie, species.nomespecie))
        category = st.selectbox("Especie", species.idespecie.tolist(),
                                format_func=lambda key: labels[key], key=f"siacon_{suffix}_especie")
        products = siacon_catalog("cat_producto").loc[
            lambda frame: (frame.idespecie == category) &
            frame.idproducto.isin(available.loc[available.idespecie == category, "idproducto"])
        ].sort_values("nomproducto")
        product_labels = dict(zip(products.idproducto, products.nomproducto))
        product = st.selectbox("Producto", products.idproducto.tolist(),
                               format_func=lambda key: product_labels[key],
                               key=f"siacon_{suffix}_producto")
        unit_id = products.set_index("idproducto").loc[product, "idunidadmedida"]
        units = siacon_catalog("cat_unidadmedida").set_index("idunidadmedida")
        unit_name = (str(units.loc[unit_id, "nomcorto"]).strip() if unit_id in units.index
                     else "unidad de la fuente")
        label = f"{labels[category]} · {product_labels[product]}"
    else:
        available = siacon_available(sector, level)
        species = siacon_catalog("cat_especiepesquero").loc[
            lambda frame: frame.idespecie.isin(available.idespecie)].sort_values("nomespecie")
        labels = dict(zip(species.idespecie, species.nomespecie))
        category = st.selectbox("Especie", species.idespecie.tolist(),
                                format_func=lambda key: labels[key],
                                index=(species.idespecie.tolist().index(108000)
                                       if 108000 in species.idespecie.tolist() else 0),
                                key=f"siacon_{suffix}_pesca")
        unit_name = "unidad registrada en SIACON"
        label = labels[category]
    metrics = SIACON_METRICS[sector]
    metric_label = (list(metrics)[0] if compass else
                    st.selectbox("Indicador", list(metrics), key=f"siacon_{suffix}_indicador"))
    metric = metrics[metric_label]
    if sector == "Agricultura":
        unit_name = ("ha" if metric in {"sembrada", "cosechada", "siniestrada"}
                     else "pesos" if metric == "valorproduccion" else unit_name)
    elif sector == "Ganadería":
        unit_name = ("pesos" if metric.startswith("valor") else
                     "unidades de inventario" if metric == "inventario" else
                     "cabezas" if metric == "numerocabezas" else unit_name)
    elif metric == "valor":
        unit_name = "unidad monetaria no indicada en la base"
    if (metric == "inventario" and not series) or compass:
        year = st.select_slider("Año", options=list(range(years[0], years[1] + 1)),
                                value=years[1], key=f"siacon_{suffix}_anio")
        first = last = year
    else:
        first, last = st.slider("Años", years[0], years[1],
                                years if series else (years[1], years[1]),
                                key=f"siacon_{suffix}_anios")
    return dict(sector=sector, level=level, category=int(category), product=product,
                metric=metric, metric_label=metric_label, first=first, last=last,
                label=label, unit_name=unit_name)


def siacon_values(choice: dict) -> pd.DataFrame:
    annual = siacon_annual(choice["sector"], choice["level"], choice["category"],
                           choice["product"], choice["metric"])
    annual = annual.loc[annual.anio.between(choice["first"], choice["last"])]
    return annual.groupby("cvegeo", as_index=False).agg(
        valor=("valor", lambda values: values.sum() if values.notna().all() else np.nan))


def render_siacon_map() -> None:
    with st.sidebar:
        choice = siacon_picker("mapa")
        level = choice["level"]
        state = crime_state_picker("siacon_mapa") if level == "municipal" else None
        chosen = []
        if state:
            candidates = names("municipal").loc[lambda frame: frame.cve_ent == state]
            labels = dict(zip(candidates.cvegeo, candidates.nombre))
            chosen = st.multiselect("Buscar y marcar municipios", candidates.cvegeo.tolist(),
                                    format_func=lambda key: f"{labels[key]} · {key}",
                                    key=f"siacon_mapa_municipios_{state}")
        method = st.selectbox("Método de clasificación", CLASSIFICATION_METHODS,
                              key="siacon_mapa_metodo")
        palette = st.selectbox("Paleta ColorBrewer", list(PALETTES),
                               key="siacon_mapa_paleta")
    if level == "municipal" and not state:
        st.info("Elige un estado para mostrar sus municipios.")
        return
    with st.spinner("Consultando SIACON y preparando mapa…", show_time=True):
        frame = names(level).merge(siacon_values(choice), on="cvegeo", how="left",
                                   validate="one_to_one")
        if state:
            frame = frame.loc[frame.cve_ent == state]
        if chosen:
            frame = frame.loc[frame.cvegeo.isin(chosen)]
        if level == "municipal" and os.getenv("CARTOGRAFUNK_MUNICIPAL_MAP", "deck").lower() != "pydeck":
            colors, bands = classify(frame.set_index("cvegeo").valor, palette, method)
            rows = [{"key": row.cvegeo, "color": colors[row.cvegeo],
                     "name": row.nombre_completo, "value": format_value(row.valor, "conteo")}
                    for row in frame.itertuples(index=False)]
            use_component = True
        else:
            shapes = geometry(level)
            if state:
                shapes = [(key, geom) for key, geom in shapes if key.startswith(state)]
            if chosen:
                shapes = [(key, geom) for key, geom in shapes if key in chosen]
            feature_collection, bands = map_features(shapes, frame, palette, "conteo", method)
            use_component = False
    st.subheader(f"{choice['label']} · {choice['first']}" +
                 (f"–{choice['last']}" if choice["last"] != choice["first"] else ""))
    st.caption(f"SIACON · {choice['sector']} · {choice['metric_label']} · {choice['unit_name']}. "
               "Los valores de varios años son sumas de registros anuales; inventario muestra un solo año.")
    if use_component:
        MUNICIPAL_MAP(data={
            "geometryUrl": "app/static/municipal_visual_1000m.json", "rows": rows,
            "stateCode": state, "selectedKeys": chosen,
            "revision": f"siacon:{choice}:{method}:{palette}:{state}:{','.join(chosen)}",
            "debug": False,
        }, key="siacon_municipal_map")
    else:
        layer = pdk.Layer("GeoJsonLayer", feature_collection, pickable=True,
                          auto_highlight=True, stroked=True, filled=True,
                          get_fill_color="properties.fill", get_line_color=[255, 255, 255, 230],
                          line_width_min_pixels=0.75)
        deck = CompactDeck(layers=[layer], initial_view_state=pdk.ViewState(
            latitude=24, longitude=-102.5, zoom=2.8, pitch=0),
            tooltip={"html": "<b>{nombre}</b><br>{cvegeo}<br>{valor}"}, map_style=None)
        st.pydeck_chart(deck, width="stretch", height=400, key="siacon_mapa")
    legend(bands, "conteo", "Sin datos SIACON")
    shown = frame[["cvegeo", "nombre_completo", "valor"]].rename(
        columns={"nombre_completo": "nombre", "valor": choice["metric_label"]})
    st.dataframe(shown, hide_index=True, width="stretch")
    st.download_button("Descargar CSV", shown.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"cartografunk_siacon_{choice['sector']}_{level}_{choice['first']}_{choice['last']}.csv",
                       mime="text/csv", key="siacon_mapa_descarga")


def render_siacon_graph() -> None:
    st.subheader("Evolución histórica")
    with st.sidebar:
        choice = siacon_picker("grafica", series=True)
        state = crime_state_picker("siacon_grafica")
        chosen = []
        if state and choice["level"] == "municipal":
            candidates = names("municipal").loc[lambda frame: frame.cve_ent == state]
            labels = dict(zip(candidates.cvegeo, candidates.nombre))
            chosen = st.multiselect("Buscar y marcar municipios", candidates.cvegeo.tolist(),
                                    format_func=lambda key: f"{labels[key]} · {key}",
                                    key=f"siacon_grafica_municipios_{state}")
    if not state:
        st.info("Elige un estado para ver su evolución histórica.")
        return
    with st.spinner("Consultando la serie histórica…", show_time=True):
        annual = siacon_annual(choice["sector"], choice["level"], choice["category"],
                               choice["product"], choice["metric"])
    keys = chosen if chosen else [state] if choice["level"] == "estatal" else None
    if keys is None:
        annual = annual.loc[annual.cvegeo.str.startswith(state)]
    else:
        annual = annual.loc[annual.cvegeo.isin(keys)]
    annual = annual.loc[annual.anio.between(choice["first"], choice["last"])]
    frame = annual.groupby("anio", as_index=False).agg(
        valor=("valor", lambda values: values.sum() if values.notna().all() else np.nan))
    if frame.empty:
        st.info("No hay registros para esta selección.")
        return
    st.caption(f"SIACON · {choice['sector']} · {choice['label']} · {choice['metric_label']} "
               f"({choice['unit_name']}). Serie anual disponible: "
               f"{SIACON_YEARS[choice['sector']][choice['level']][0]}–"
               f"{SIACON_YEARS[choice['sector']][choice['level']][1]}.")
    fig = px.line(frame, x="anio", y="valor", markers=True,
                  labels={"anio": "Año", "valor": choice["metric_label"]})
    fig.update_traces(hovertemplate="%{x}<br>%{y:,.2f}<extra></extra>")
    st.plotly_chart(fig, width="stretch", key="siacon_serie")
    st.dataframe(frame, hide_index=True, width="stretch")
    st.download_button("Descargar CSV", frame.to_csv(index=False).encode("utf-8-sig"),
                       file_name="cartografunk_siacon_serie.csv", mime="text/csv")


def render_siacon_compass() -> None:
    st.subheader("Compass · estados")
    with st.sidebar:
        choice = siacon_picker("compass", compass=True)
        metrics = SIACON_METRICS[choice["sector"]]
        x_label = st.selectbox("Eje X", list(metrics), key="siacon_compass_x")
        y_label = st.selectbox("Eje Y", list(metrics),
                               index=min(1, len(metrics) - 1), key="siacon_compass_y")
        year = choice["first"]
    def axis(metric_label: str) -> pd.DataFrame:
        annual = siacon_annual(choice["sector"], "estatal", choice["category"],
                               choice["product"], metrics[metric_label])
        return annual.loc[annual.anio == year, ["cvegeo", "valor"]]
    frame = names("estatal")[["cvegeo", "nombre", "abreviatura"]]
    frame = frame.merge(axis(x_label).rename(columns={"valor": "x"}), on="cvegeo", how="left")
    frame = frame.merge(axis(y_label).rename(columns={"valor": "y"}), on="cvegeo", how="left")
    frame = frame.dropna(subset=["x", "y"])
    if frame.empty:
        st.info("No hay estados con valores para ambos ejes en ese año.")
        return
    x_cut, y_cut = frame.x.median(), frame.y.median()
    frame["cuadrante"] = np.select([
        (frame.x >= x_cut) & (frame.y >= y_cut),
        (frame.x < x_cut) & (frame.y >= y_cut),
        (frame.x < x_cut) & (frame.y < y_cut)],
        ["Alto · Alto", "Bajo · Alto", "Bajo · Bajo"], default="Alto · Bajo")
    fig = px.scatter(frame, x="x", y="y", text="abreviatura", hover_name="nombre",
                     color="cuadrante", labels={"x": x_label, "y": y_label})
    fig.add_vline(x=x_cut, line_dash="dash", line_color="#888")
    fig.add_hline(y=y_cut, line_dash="dash", line_color="#888")
    fig.update_traces(textposition="top center")
    st.caption(f"SIACON · {choice['sector']} · {choice['label']} · {year}. "
               "Los cortes son las medianas de los estados con datos en el año elegido.")
    st.plotly_chart(fig, width="stretch", key="siacon_compass")
    st.dataframe(frame[["cvegeo", "nombre", "x", "y", "cuadrante"]],
                 hide_index=True, width="stretch")


EDR_RATE = "Tasa por 100 mil (CPV 2020)"


@st.cache_data(show_spinner=False)
def edr_catalog(table: str) -> pd.DataFrame:
    if table not in {"dim_capitulo", "dim_grupo_causa", "dim_edad_agrupada"}:
        raise ValueError("Catálogo EDR desconocido")
    return pd.read_parquet(DATA / "edr" / "catalogos" / f"{table}.parquet")


def edr_cause_picker(suffix: str, *, default_mode: str = "Todas las causas",
                     default_code: str | None = None) -> tuple[str, str | int | None, str]:
    modes = ["Todas las causas", "Capítulo CIE", "Grupo Lista Mexicana"]
    mode = st.selectbox("Causas", modes, index=modes.index(default_mode),
                        key=f"edr_{suffix}_causas")
    if mode == "Todas las causas":
        return "todas", None, "Todas las causas"
    if mode == "Capítulo CIE":
        catalog = edr_catalog("dim_capitulo")
        labels = dict(zip(catalog.cap.astype(int), catalog.descripcion))
        code = st.selectbox("Capítulo", sorted(labels),
                            format_func=lambda key: f"{key} · {labels[key]}",
                            key=f"edr_{suffix}_capitulo")
        return "capitulo", int(code), labels[code]
    catalog = edr_catalog("dim_grupo_causa")
    labels = dict(zip(catalog.cve, catalog.descripcion))
    codes = sorted(labels)
    code = st.selectbox("Grupo de causas", codes,
                        format_func=lambda key: f"{key} · {labels[key]}",
                        index=codes.index(default_code) if default_code in codes else 0,
                        key=f"edr_{suffix}_grupo")
    return "grupo", code, labels[code]


@st.cache_data(show_spinner=False)
def edr_annual(level: str, mode: str, code: str | int | None,
               sex: int | None, age: int | None) -> pd.DataFrame:
    if level not in {"estatal", "municipal"}:
        raise ValueError("Nivel EDR desconocido")
    conditions, params = [], [str(DATA / "edr" / level / "anio=*" / "*.parquet")]
    if mode == "capitulo":
        conditions.append("capitulo = ?")
        params.append(int(code))
    elif mode == "grupo":
        conditions.append("grupo_causa = ?")
        params.append(str(code))
    elif mode != "todas":
        raise ValueError("Agrupación EDR desconocida")
    if sex is not None:
        conditions.append("sexo = ?")
        params.append(sex)
    if age is not None:
        conditions.append("edad_agru = ?")
        params.append(age)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    cursor = duckdb_connection().cursor()
    try:
        return cursor.execute(f"""
            SELECT cvegeo, anio, sum(defunciones)::BIGINT AS valor
            FROM read_parquet(?, hive_partitioning=true) {where}
            GROUP BY cvegeo, anio ORDER BY cvegeo, anio
        """, params).df()
    finally:
        cursor.close()


def edr_picker(suffix: str, *, series: bool = False, compass: bool = False) -> dict:
    level_label = st.selectbox("Nivel", ["Estado"] if compass else ["Estado", "Municipio"],
                               key=f"edr_{suffix}_nivel")
    level = LEVELS[level_label][0]
    mode, code, label = edr_cause_picker(suffix)
    sex_label = st.selectbox("Sexo", ["Todos", "Hombres", "Mujeres"],
                             key=f"edr_{suffix}_sexo")
    sex = {"Todos": None, "Hombres": 1, "Mujeres": 2}[sex_label]
    ages = edr_catalog("dim_edad_agrupada")
    age_labels = {int(row.cve): row.descripcion for row in ages.itertuples(index=False)}
    age = st.selectbox("Edad", [None, *sorted(age_labels)],
                       format_func=lambda key: age_labels.get(key, "Todas las edades"),
                       key=f"edr_{suffix}_edad")
    measures = ["Defunciones"]
    if sex is None and age is None:
        measures.append(EDR_RATE)
    measure = ("Defunciones" if compass else
               st.selectbox("Medida", measures, key=f"edr_{suffix}_medida"))
    first_year = 2020 if measure == EDR_RATE else 2012
    if compass:
        first = last = st.select_slider("Año", options=list(range(2012, 2025)),
                                        value=2024, key=f"edr_{suffix}_anio")
    else:
        first, last = st.slider("Años de registro", first_year, 2024,
                                (first_year, 2024) if series else (2024, 2024),
                                key=f"edr_{suffix}_anios_{first_year}")
    return dict(level=level, mode=mode, code=code, label=label, sex=sex, age=age,
                measure=measure, first=first, last=last)


def edr_values(choice: dict) -> pd.DataFrame:
    coverage = edr_annual(choice["level"], "todas", None, None, None)
    coverage = coverage.loc[coverage.anio.between(choice["first"], choice["last"]),
                            ["cvegeo"]].drop_duplicates()
    annual = edr_annual(choice["level"], choice["mode"], choice["code"],
                        choice["sex"], choice["age"])
    annual = annual.loc[annual.anio.between(choice["first"], choice["last"])]
    values = annual.groupby("cvegeo", as_index=False).valor.sum()
    values = coverage.merge(values, on="cvegeo", how="left", validate="one_to_one")
    values["valor"] = values.valor.fillna(0)
    if choice["measure"] == EDR_RATE:
        population = crime_population(choice["level"])
        values = values.merge(population, on="cvegeo", how="left")
        values["valor"] = values.valor.div(
            values.poblacion_cpv2020.where(values.poblacion_cpv2020 > 0)
        ).div(choice["last"] - choice["first"] + 1).mul(100_000)
        values = values[["cvegeo", "valor"]]
    return values


def render_edr_map() -> None:
    with st.sidebar:
        choice = edr_picker("mapa")
        level = choice["level"]
        state = crime_state_picker("edr_mapa") if level == "municipal" else None
        chosen = []
        if state:
            candidates = names("municipal").loc[lambda frame: frame.cve_ent == state]
            labels = dict(zip(candidates.cvegeo, candidates.nombre))
            chosen = st.multiselect("Buscar y marcar municipios", candidates.cvegeo.tolist(),
                                    format_func=lambda key: f"{labels[key]} · {key}",
                                    key=f"edr_mapa_municipios_{state}")
        method = st.selectbox("Método de clasificación", CLASSIFICATION_METHODS,
                              key="edr_mapa_metodo")
        palette = st.selectbox("Paleta ColorBrewer", list(PALETTES), key="edr_mapa_paleta")
    if level == "municipal" and not state:
        st.info("Elige un estado para mostrar sus municipios.")
        return
    with st.spinner("Consultando defunciones y preparando mapa…", show_time=True):
        frame = names(level).merge(edr_values(choice), on="cvegeo", how="left",
                                   validate="one_to_one")
        if state:
            frame = frame.loc[frame.cve_ent == state]
        if chosen:
            frame = frame.loc[frame.cvegeo.isin(chosen)]
        unit = "por_100k" if choice["measure"] == EDR_RATE else "conteo"
        if level == "municipal" and os.getenv("CARTOGRAFUNK_MUNICIPAL_MAP", "deck").lower() != "pydeck":
            colors, bands = classify(frame.set_index("cvegeo").valor, palette, method)
            rows = [{"key": row.cvegeo, "color": colors[row.cvegeo],
                     "name": row.nombre_completo, "value": format_value(row.valor, unit)}
                    for row in frame.itertuples(index=False)]
            use_component = True
        else:
            shapes = geometry(level)
            if state:
                shapes = [(key, geom) for key, geom in shapes if key.startswith(state)]
            if chosen:
                shapes = [(key, geom) for key, geom in shapes if key in chosen]
            feature_collection, bands = map_features(shapes, frame, palette, unit, method)
            use_component = False
    st.subheader(f"{choice['label']} · {choice['first']}" +
                 (f"–{choice['last']}" if choice["last"] != choice["first"] else ""))
    st.caption("INEGI · Defunciones Registradas · residencia habitual · año de registro. "
               + ("Tasa anual promedio con población fija CPV 2020." if unit == "por_100k"
                  else "Conteo de defunciones registradas."))
    if use_component:
        MUNICIPAL_MAP(data={
            "geometryUrl": "app/static/municipal_visual_1000m.json", "rows": rows,
            "stateCode": state, "selectedKeys": chosen,
            "revision": f"edr:{choice}:{method}:{palette}:{state}:{','.join(chosen)}",
            "debug": False,
        }, key="edr_municipal_map")
    else:
        layer = pdk.Layer("GeoJsonLayer", feature_collection, pickable=True,
                          auto_highlight=True, stroked=True, filled=True,
                          get_fill_color="properties.fill", get_line_color=[255, 255, 255, 230],
                          line_width_min_pixels=0.75)
        deck = CompactDeck(layers=[layer], initial_view_state=pdk.ViewState(
            latitude=24, longitude=-102.5, zoom=2.8, pitch=0),
            tooltip={"html": "<b>{nombre}</b><br>{cvegeo}<br>{valor}"}, map_style=None)
        st.pydeck_chart(deck, width="stretch", height=400, key="edr_mapa")
    legend(bands, unit, "Sin datos EDR")
    if level == "municipal":
        st.caption("Siete claves municipales históricas (421 defunciones en 2012–2024) "
                   "no tienen geometría actual. Los casos sin municipio identificado "
                   "sí cuentan en el total estatal y no en el mapa municipal.")
    shown = frame[["cvegeo", "nombre_completo", "valor"]].rename(
        columns={"nombre_completo": "nombre", "valor": choice["measure"]})
    st.dataframe(shown, hide_index=True, width="stretch")
    st.download_button("Descargar CSV", shown.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"cartografunk_edr_{level}_{choice['first']}_{choice['last']}.csv",
                       mime="text/csv", key="edr_mapa_descarga")


def render_edr_graph() -> None:
    st.subheader("Evolución histórica")
    with st.sidebar:
        choice = edr_picker("grafica", series=True)
        state = crime_state_picker("edr_grafica")
        chosen = []
        if state and choice["level"] == "municipal":
            candidates = names("municipal").loc[lambda frame: frame.cve_ent == state]
            labels = dict(zip(candidates.cvegeo, candidates.nombre))
            chosen = st.multiselect("Buscar y marcar municipios", candidates.cvegeo.tolist(),
                                    format_func=lambda key: f"{labels[key]} · {key}",
                                    placeholder="Sin selección, total estatal",
                                    key=f"edr_grafica_municipios_{state}")
    if not state:
        st.info("Elige un estado para ver su evolución histórica.")
        return
    level = "municipal" if chosen else "estatal"
    annual = edr_annual(level, choice["mode"], choice["code"], choice["sex"], choice["age"])
    keys = chosen if chosen else [state]
    annual = annual.loc[annual.cvegeo.isin(keys) &
                        annual.anio.between(choice["first"], choice["last"])]
    coverage = edr_annual(level, "todas", None, None, None)
    coverage = coverage.loc[coverage.cvegeo.isin(keys) &
                            coverage.anio.between(choice["first"], choice["last"]),
                            ["anio"]].drop_duplicates()
    frame = coverage.merge(annual.groupby("anio", as_index=False).valor.sum(),
                           on="anio", how="left", validate="one_to_one")
    frame["valor"] = frame.valor.fillna(0)
    if frame.empty:
        st.info("No hay registros para esta selección.")
        return
    if choice["measure"] == EDR_RATE:
        population = crime_population(level)
        selected = population.loc[population.cvegeo.isin(keys), "poblacion_cpv2020"]
        denominator = selected.sum() if len(selected) == len(keys) and selected.notna().all() else np.nan
        frame["valor"] = frame.valor.div(denominator if denominator > 0 else np.nan).mul(100_000)
    st.caption(f"INEGI · Defunciones Registradas · {choice['label']} · "
               "año de registro, residencia habitual. " +
               ("Tasa por 100 mil con población fija CPV 2020." if choice["measure"] == EDR_RATE
                else "Conteo anual."))
    fig = px.line(frame, x="anio", y="valor", markers=True,
                  labels={"anio": "Año de registro", "valor": choice["measure"]})
    fig.update_traces(hovertemplate="%{x}<br>%{y:,.2f}<extra></extra>")
    st.plotly_chart(fig, width="stretch", key="edr_serie")
    st.dataframe(frame, hide_index=True, width="stretch")
    st.download_button("Descargar CSV", frame.to_csv(index=False).encode("utf-8-sig"),
                       file_name="cartografunk_edr_serie.csv", mime="text/csv")


def render_edr_compass() -> None:
    st.subheader("Compass · estados")
    with st.sidebar:
        st.markdown("**Eje X**")
        x_mode, x_code, x_label = edr_cause_picker(
            "compass_x", default_mode="Grupo Lista Mexicana", default_code="28")
        st.markdown("**Eje Y**")
        y_mode, y_code, y_label = edr_cause_picker(
            "compass_y", default_mode="Grupo Lista Mexicana", default_code="E55")
        measure = st.selectbox("Medida", [EDR_RATE, "Defunciones"], key="edr_compass_medida")
        years = list(range(2020 if measure == EDR_RATE else 2012, 2025))
        year = st.select_slider("Año de registro", options=years, value=2024,
                                key=f"edr_compass_anio_{years[0]}")
    x_all = edr_annual("estatal", x_mode, x_code, None, None)
    y_all = edr_annual("estatal", y_mode, y_code, None, None)
    frame = names("estatal")[["cvegeo", "nombre", "abreviatura"]]
    frame = frame.merge(x_all.loc[x_all.anio == year, ["cvegeo", "valor"]].rename(
        columns={"valor": "x"}), on="cvegeo", how="left")
    frame = frame.merge(y_all.loc[y_all.anio == year, ["cvegeo", "valor"]].rename(
        columns={"valor": "y"}), on="cvegeo", how="left")
    frame[["x", "y"]] = frame[["x", "y"]].fillna(0)
    if measure == EDR_RATE:
        population = crime_population("estatal").set_index("cvegeo").poblacion_cpv2020
        denominator = frame.cvegeo.map(population).where(lambda values: values > 0)
        frame["x"] = frame.x.div(denominator).mul(100_000)
        frame["y"] = frame.y.div(denominator).mul(100_000)
        frame = frame.dropna(subset=["x", "y"])
    if frame.empty:
        st.info("No hay estados con valores para ambos ejes.")
        return
    x_cut, y_cut = frame.x.median(), frame.y.median()
    frame["cuadrante"] = np.select([
        (frame.x >= x_cut) & (frame.y >= y_cut),
        (frame.x < x_cut) & (frame.y >= y_cut),
        (frame.x < x_cut) & (frame.y < y_cut)],
        ["Alto · Alto", "Bajo · Alto", "Bajo · Bajo"], default="Alto · Bajo")
    fig = px.scatter(frame, x="x", y="y", text="abreviatura", hover_name="nombre",
                     color="cuadrante", labels={"x": x_label, "y": y_label})
    fig.add_vline(x=x_cut, line_dash="dash", line_color="#888")
    fig.add_hline(y=y_cut, line_dash="dash", line_color="#888")
    fig.update_traces(textposition="top center")
    st.caption(f"INEGI · Defunciones Registradas · {year} · residencia habitual. "
               "Cortes: medianas de los estados con datos. " +
               ("Tasas por 100 mil con población fija CPV 2020." if measure == EDR_RATE
                else "Conteos de defunciones registradas."))
    st.plotly_chart(fig, width="stretch", key="edr_compass")
    st.dataframe(frame[["cvegeo", "nombre", "x", "y", "cuadrante"]],
                 hide_index=True, width="stretch")


def main() -> None:
    st.set_page_config(
        page_title="Haz tu propio mapa · Cartografunk",
        page_icon=str(ROOT / "assets" / "img" / "favicon.webp"),
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown("<style>.block-container{padding-top:1.25rem}</style>", unsafe_allow_html=True)
    st.title("Haz tu propio mapa")
    with st.sidebar:
        source = st.selectbox("Fuente", ["Censo 2020 · INEGI", "Delitos · SESNSP",
                                         "Producción agropecuaria y pesquera · SIACON",
                                         "Defunciones registradas · INEGI"],
                              key="cartografunk_fuente")
    map_tab, graph_tab, compass_tab = st.tabs(["Mapa", "Gráfica", "Compass"], on_change="rerun")
    if map_tab.open:
        with map_tab:
            (render_crime_map() if source == "Delitos · SESNSP" else
             render_siacon_map() if source.startswith("Producción agropecuaria") else
             render_edr_map() if source.startswith("Defunciones registradas") else render_map())
    if graph_tab.open:
        with graph_tab:
            (render_crime_graph() if source == "Delitos · SESNSP" else
             render_siacon_graph() if source.startswith("Producción agropecuaria") else
             render_edr_graph() if source.startswith("Defunciones registradas") else render_graph())
    if compass_tab.open:
        with compass_tab:
            (render_crime_compass() if source == "Delitos · SESNSP" else
             render_siacon_compass() if source.startswith("Producción agropecuaria") else
             render_edr_compass() if source.startswith("Defunciones registradas") else render_compass())
    st.caption(
        "Fuentes: Datos y geografía: Censo de Población y Vivienda INEGI "
        "(2020) y Marco Geoestadístico Nacional INEGI (2025). "
        "Incidencia delictiva y víctimas del fuero común: SESNSP, nueva metodología "
        "(registro 2015–2025, descarga con corte de septiembre de 2026). "
        "Producción agrícola, pecuaria y pesquera: SIACON, copia local con datos hasta 2024 "
        "(pesca hasta 2018). "
        "Defunciones Registradas: INEGI (2012–2024, año de registro y residencia habitual). "
        "Paletas: ColorBrewer 2.0."
    )


if __name__ == "__main__":
    main()
