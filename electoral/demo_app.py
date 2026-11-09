"""Demo estatal de rentabilidad electoral de Presidencia 2024.

Ejecutar desde la raíz del proyecto: streamlit run electoral/demo_app.py
"""

import json
from io import BytesIO
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import geopandas as gpd
import pandas as pd
import pydeck as pdk
import streamlit as st

from electoral.agregacion import agregar
from electoral.clasificacion import CLASES, Umbrales, clasificar
from electoral.config import (
    CANDIDATURAS, DIPUTACIONES_PARQUET, GEOMETRIA_PARQUET,
    PRESIDENCIA_PARQUET, SENADURIAS_PARQUET,
)
from electoral.estadisticas_fidelidad import correlaciones_pares, icc_por_partido
from electoral.fidelidad import PARTIDOS, analizar_fidelidad, panel
from electoral.rentabilidad import rentabilidad


CANDS = [f"cand_{nombre}" for nombre in CANDIDATURAS]
NOMBRES = {
    "cand_PAN_PRI_PRD": "PAN-PRI-PRD",
    "cand_PVEM_PT_MORENA": "PVEM-PT-MORENA",
    "cand_MC": "MC",
}
COLORES = {
    "ganada_solida": [69, 117, 180],
    "ganada_ajustada": [145, 191, 219],
    "empate": [255, 255, 191],
    "perdida_competitiva": [254, 224, 144],
    "perdida_intermedia": [252, 141, 89],
    "perdida_lejana": [215, 48, 39],
}
GRIS = [200, 200, 200]
ETIQUETAS_CLASE = {
    "ganada_solida": "Ganada sólida",
    "ganada_ajustada": "Ganada ajustada",
    "empate": "Empate",
    "perdida_competitiva": "Perdida competitiva",
    "perdida_intermedia": "Perdida intermedia",
    "perdida_lejana": "Perdida lejana",
}
ETIQUETAS_RESULTADO = {"ganada": "Ganada", "empate": "Empate", "perdida": "Perdida"}


@st.cache_data
def cargar_resultados() -> pd.DataFrame:
    return pd.read_parquet(PRESIDENCIA_PARQUET)


@st.cache_resource
def cargar_geom() -> gpd.GeoDataFrame:
    return gpd.read_parquet(GEOMETRIA_PARQUET)


@st.cache_data(show_spinner="Preparando polígonos del estado…")
def cargar_poligonos_estado(estado: int) -> tuple[dict, tuple[float, float, float, float]]:
    """Serializa una vez la geometría estatal; los controles reutilizan esta copia."""
    geometria = cargar_geom()
    poligonos = geometria.loc[geometria["ENTIDAD"].eq(estado), ["ID_SECCION", "geometry"]]
    return json.loads(poligonos.to_json(drop_id=True)), tuple(poligonos.total_bounds)


def preparar_mapa(geojson: dict, resultados: pd.DataFrame) -> tuple[dict, int]:
    """Agrega etiquetas y colores a la copia del GeoJSON estatal."""
    por_seccion = {
        seccion: (clase, margen, faltante, votos)
        for seccion, clase, margen, faltante, votos in resultados[
            ["ID_SECCION", "clase", "margen_pct", "faltante_pct", "votos_para_ganar"]
        ].itertuples(index=False, name=None)
    }
    sin_fila = 0
    for feature in geojson["features"]:
        propiedades = feature["properties"]
        seccion = propiedades["ID_SECCION"]
        if seccion not in por_seccion:
            sin_fila += 1
        clase, margen, faltante, votos = por_seccion.get(seccion, (None, None, None, None))
        clase = str(clase) if pd.notna(clase) else None
        distancia = margen if pd.notna(margen) else -faltante if pd.notna(faltante) else None
        propiedades["color"] = COLORES.get(clase, GRIS)
        propiedades["txt"] = (
            f"{seccion} | {ETIQUETAS_CLASE.get(clase, 'Sin resultado')} | "
            f"{f'{distancia:+.1f} pp' if distancia is not None else 'sin dato'} | "
            f"votos para ganar: {int(votos) if pd.notna(votos) else '-'}"
        )
    return geojson, sin_fila


@st.cache_data(show_spinner="Cargando elecciones 2024…")
def cargar_elecciones() -> dict[str, pd.DataFrame]:
    return {
        "presidencia": pd.read_parquet(PRESIDENCIA_PARQUET),
        "diputaciones": pd.read_parquet(DIPUTACIONES_PARQUET),
        "senadurias": pd.read_parquet(SENADURIAS_PARQUET),
    }


@st.cache_data(show_spinner="Calculando fidelidad por partido…")
def cargar_analisis_fidelidad(ambito: str, estado: int) -> pd.DataFrame:
    elecciones = cargar_elecciones()
    if ambito == "estado":
        elecciones = {
            nombre: df.loc[df["ID_ESTADO"].eq(estado)]
            for nombre, df in elecciones.items()
        }
    return analizar_fidelidad(elecciones, ambito=ambito)


@st.cache_data(show_spinner="Calculando estadísticas…")
def cargar_estadisticas_fidelidad(estado: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    elecciones = {
        nombre: df.loc[
            df["ID_ESTADO"].eq(estado)
            & pd.to_numeric(df["LISTA_NOMINAL"], errors="coerce").ge(100)
        ]
        for nombre, df in cargar_elecciones().items()
    }
    largo = panel(elecciones)
    return icc_por_partido(largo), correlaciones_pares(largo)


def _excel_fidelidad(tabla: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        tabla.to_excel(writer, index=False, sheet_name="Fidelidad")
    return buffer.getvalue()


st.set_page_config(page_title="Rentabilidad electoral", layout="wide")
st.title("Rentabilidad electoral · Presidencia 2024")

sec = cargar_resultados()
estados = sorted(sec.loc[sec["estado"].ne("extranjero"), "ID_ESTADO"].unique())
nombres_estados = sec.drop_duplicates("ID_ESTADO").set_index("ID_ESTADO")["NOMBRE_ESTADO"].to_dict()

tab_rentabilidad, tab_fidelidad = st.tabs(["Rentabilidad", "Fidelidad"])
with tab_rentabilidad:
    with st.sidebar:
        evaluar = st.selectbox("Candidatura a evaluar", CANDS, index=1, format_func=NOMBRES.get)
        st.caption("Se comparan candidaturas. Los votos de coalición no se reparten entre partidos en este demo.")
        estado = st.selectbox(
            "Estado (clave INE)", estados,
            index=estados.index(14) if 14 in estados else 0,
            format_func=lambda clave: f"{clave:02d} · {nombres_estados[clave]}",
        )
        st.markdown("**Umbrales (puntos porcentuales)**")
        competitiva = st.slider("Competitiva: faltante menor a", 1.0, 10.0, 5.0, 0.5)
        lejana = st.slider("Lejana / sólida desde", 10.0, 30.0, 15.0, 1.0)
        votos_alcanzables = st.slider("Alcanzable en votos (≤)", 10, 300, 100, 10)

    umbrales = Umbrales(
        solida_pp=lejana,
        competitiva_pp=competitiva,
        lejana_pp=lejana,
        votos_alcanzables=votos_alcanzables,
    )
    estado_sec = sec.loc[sec["ID_ESTADO"].eq(estado) & sec["estado"].ne("extranjero")]
    res = clasificar(rentabilidad(estado_sec, CANDS, evaluar), umbrales)

    conteos = res["clase"].value_counts(sort=False).reindex(CLASES, fill_value=0)
    for columna, clase in zip(st.columns(len(CLASES)), CLASES):
        columna.metric(ETIQUETAS_CLASE[clase], int(conteos[clase]))
    st.caption(f"{int(res['estado'].eq('sin_resultado').sum())} secciones sin resultado en este estado.")

    leyenda = [
        f'<span style="color:rgb({",".join(map(str, COLORES[clase]))});font-size:1.4em">●</span> {ETIQUETAS_CLASE[clase]}'
        for clase in CLASES
    ]
    leyenda.append('<span style="color:rgb(200,200,200);font-size:1.4em">●</span> Sin resultado')
    st.markdown(" &nbsp;&nbsp; ".join(leyenda), unsafe_allow_html=True)

    geojson_estado, limites = cargar_poligonos_estado(estado)
    mapa, sin_fila = preparar_mapa(geojson_estado, res)
    st.caption(f"{sin_fila} polígonos del MGE sin fila de resultados en este estado; se muestran en gris.")
    minx, miny, maxx, maxy = limites
    capa = pdk.Layer(
        "GeoJsonLayer",
        data=mapa,
        get_fill_color="properties.color",
        get_line_color=[255, 255, 255],
        line_width_min_pixels=0.5,
        pickable=True,
        opacity=0.8,
    )
    vista = pdk.ViewState(latitude=(miny + maxy) / 2, longitude=(minx + maxx) / 2, zoom=6.5)
    st.pydeck_chart(pdk.Deck(layers=[capa], initial_view_state=vista, tooltip={"text": "{txt}"}))

    st.subheader("Secciones más cercanas a ganar")
    with st.expander("Cómo leer las tablas"):
        st.markdown(
            "**Clasificación:** cercanía de la candidatura evaluada al primer lugar. "
            "**Margen (pp):** ventaja sobre el segundo lugar cuando gana. "
            "**Faltante (pp):** distancia al primer lugar cuando pierde. "
            "**Votos para ganar:** votos adicionales necesarios para superar al primer lugar; en un empate es 1. "
            "**Abstención:** lista nominal menos votos en lista, descontando las casillas especiales. "
            "**Alcanzable con abstención:** indica si los votos para ganar caben en esa abstención positiva."
        )
    rescatables = res.loc[res["resultado"].isin(("perdida", "empate"))].sort_values("votos_para_ganar")
    columnas_rescate = [
        "ID_SECCION", "MUNICIPIO", "clase", "faltante_pct", "votos_para_ganar",
        "abstencion", "rescatable_vs_abst", "alcanzable_por_abstencion",
    ]
    tabla_rescatables = rescatables[columnas_rescate].head(30).rename(columns={
        "ID_SECCION": "Sección",
        "MUNICIPIO": "Municipio",
        "clase": "Clasificación",
        "faltante_pct": "Faltante (pp)",
        "votos_para_ganar": "Votos para ganar",
        "abstencion": "Abstención",
        "rescatable_vs_abst": "Votos necesarios / abstención",
        "alcanzable_por_abstencion": "Alcanzable con abstención",
    })
    tabla_rescatables["Clasificación"] = tabla_rescatables["Clasificación"].astype("object").map(ETIQUETAS_CLASE)
    tabla_rescatables["Alcanzable con abstención"] = tabla_rescatables[
        "Alcanzable con abstención"
    ].map({True: "Sí", False: "No"}).fillna("Sin dato")
    st.dataframe(tabla_rescatables, width="stretch")

    st.subheader("Distritos del estado")
    distritos = agregar(res, "distrito", CANDS, evaluar, umbrales)
    columnas_distrito = [
        "ID_DISTRITO_FEDERAL", "n_secciones", "n_con_resultado", "n_sin_resultado",
        *CANDS, "resultado", "clase", "margen_pct", "faltante_pct",
        "votos_para_ganar", "n_perdida_competitiva",
    ]
    tabla_distritos = distritos[columnas_distrito].rename(columns={
        "ID_DISTRITO_FEDERAL": "Distrito federal",
        "n_secciones": "Secciones",
        "n_con_resultado": "Con resultado",
        "n_sin_resultado": "Sin resultado",
        **{columna: f"{NOMBRES[columna]} · votos" for columna in CANDS},
        "resultado": "Resultado",
        "clase": "Clasificación",
        "margen_pct": "Margen (pp)",
        "faltante_pct": "Faltante (pp)",
        "votos_para_ganar": "Votos para ganar",
        "n_perdida_competitiva": "Secciones perdidas competitivas",
    })
    tabla_distritos["Resultado"] = tabla_distritos["Resultado"].map(ETIQUETAS_RESULTADO)
    tabla_distritos["Clasificación"] = tabla_distritos["Clasificación"].astype("object").map(ETIQUETAS_CLASE)
    st.dataframe(tabla_distritos, width="stretch")

    st.caption(
        "Presidencia 2024: candidaturas calculadas con columnas de _SEC.csv. "
        "Geometría MGE 2024 simplificada a 25 m; EPSG:32614 es una hipótesis de trabajo."
    )

with tab_fidelidad:
    st.subheader("Fidelidad por partido · 2024")
    st.caption("Clases: propuesta Scouter, umbrales provisionales. Reparto de coaliciones experimental (A_propios), solo 2024.")
    col_ambito, col_partido, col_estado = st.columns(3)
    with col_ambito:
        ambito_fid = st.selectbox("Ámbito de percentiles", ["estado", "nacional"], index=0)
    with col_partido:
        partido_fid = st.selectbox("Partido", PARTIDOS)
    with col_estado:
        estado_fid = st.selectbox(
            "Estado para ver secciones", estados,
            index=estados.index(14) if 14 in estados else 0,
            format_func=lambda clave: f"{clave:02d} · {nombres_estados[clave]}",
        )

    analisis = cargar_analisis_fidelidad(ambito_fid, estado_fid)
    seleccion = analisis.loc[
        analisis["partido"].eq(partido_fid) & analisis["ID_ESTADO"].eq(estado_fid)
    ].copy()
    resumen = seleccion["clase"].value_counts().reindex(["Bastión", "Base fuerte", "Resto"], fill_value=0)
    for columna, clase in zip(st.columns(3), resumen.index):
        columna.metric(clase, int(resumen[clase]))
    st.caption(f"{len(seleccion):,} secciones con resultado y lista nominal ≥ 100 en las tres elecciones; {int(seleccion['volatil'].sum()):,} volátiles.")

    tabla_fid = seleccion[[
        "ID_SECCION", "partido", "piso_pct", "piso_votos", "rango_pp",
        "percentil_piso", "n_grupo", "clase", "volatil", "umbral_rango_pp",
        "primera_en_todas", "coalicion_distinta", "ambito",
    ]].sort_values(["volatil", "piso_pct"], ascending=[False, False]).rename(columns={
        "ID_SECCION": "Sección", "partido": "Partido", "piso_pct": "Piso (%)",
        "piso_votos": "Piso (votos)", "rango_pp": "Rango (pp)",
        "percentil_piso": "Percentil del piso", "n_grupo": "Secciones del grupo",
        "clase": "Clase", "volatil": "Volátil", "umbral_rango_pp": "Umbral de rango (pp)",
        "primera_en_todas": "Primera en las tres", "coalicion_distinta": "Coalición distinta",
        "ambito": "Ámbito",
    })
    st.subheader("Secciones")
    st.dataframe(
        tabla_fid.style.apply(
            lambda fila: ["background-color: #fff0b3" if fila["Volátil"] else ""] * len(fila),
            axis=1,
        ),
        width="stretch",
    )
    archivo = f"fidelidad_{partido_fid}_{ambito_fid}_{estado_fid:02d}"
    descargas = st.columns(2)
    descargas[0].download_button(
        "Descargar CSV", tabla_fid.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{archivo}.csv", mime="text/csv",
    )
    descargas[1].download_button(
        "Descargar Excel", _excel_fidelidad(tabla_fid),
        file_name=f"{archivo}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    icc, correlaciones = cargar_estadisticas_fidelidad(estado_fid)
    st.subheader("ICC y correlaciones · estado seleccionado")
    st.dataframe(icc.loc[icc["partido"].eq(partido_fid)], width="stretch")
    st.dataframe(correlaciones.loc[correlaciones["partido"].eq(partido_fid)], width="stretch")
