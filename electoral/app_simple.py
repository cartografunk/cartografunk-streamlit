"""Demo estatal de rentabilidad electoral de tres elecciones federales de 2024.

Ejecutar desde la raíz del proyecto: streamlit run electoral/app_simple.py
"""

import json
import math
from datetime import date
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
from electoral.analisis_demo import MIEMBROS_COALICION, analizar_candidatura, aportes_coalicion
from electoral.clasificacion import CLASES, Umbrales
from electoral.config import (
    DIPUTACIONES_PARQUET, ENTIDADES_VISUAL_PARQUET, GEOMETRIA_PARQUET,
    MUNICIPIOS_VISUAL_PARQUET, NOTAS_CALIDAD_DEMO,
    PRESIDENCIA_PARQUET, SENADURIAS_PARQUET,
)
from electoral.estadisticas_fidelidad import correlaciones_pares, icc_por_partido
from electoral.etiquetas import ETIQUETAS_CLASE, ETIQUETAS_RESULTADO
from electoral.explicacion import explicar, perfil_clases
from electoral.exportacion import construir_excel
from electoral.fidelidad import PARTIDOS, analizar_fidelidad, panel
from electoral.forecasting_tab import mostrar_diagnostico_forecast
from electoral.dashboard_casillas import mostrar_dashboard_casillas
from electoral.boletas_tab import mostrar_explorador_boletas
from electoral.limites import limites_estado
from electoral.precalcular_fidelidad import SALIDAS
from electoral.priorizacion import cubrir_meta, meta_distrital, preparar_priorizacion, presupuestar
from electoral.portada import mostrar_portada
from electoral.piloto_local import mostrar_piloto_local


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
@st.cache_data
def cargar_resultados(eleccion: str) -> pd.DataFrame:
    rutas = {
        "Presidencia 2024": PRESIDENCIA_PARQUET,
        "Diputaciones MR 2024": DIPUTACIONES_PARQUET,
        "Senadurías MR 2024": SENADURIAS_PARQUET,
    }
    return pd.read_parquet(rutas[eleccion])


@st.cache_resource
def cargar_geom() -> gpd.GeoDataFrame:
    return gpd.read_parquet(GEOMETRIA_PARQUET)


@st.cache_resource
def cargar_marco_visual() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Copia local simplificada de 00ent y 00mun, publicada por el pipeline geo."""
    return (
        gpd.read_parquet(ENTIDADES_VISUAL_PARQUET),
        gpd.read_parquet(MUNICIPIOS_VISUAL_PARQUET),
    )


@st.cache_data(show_spinner="Preparando límites territoriales…")
def cargar_limites_estado(estado: int) -> tuple[dict, dict, tuple[float, float], int]:
    entidades, municipios = cargar_marco_visual()
    return limites_estado(entidades, municipios, estado)


@st.cache_data(show_spinner="Preparando polígonos del estado…")
def cargar_poligonos_estado(estado: int) -> tuple[dict, tuple[float, float, float, float]]:
    """Serializa una vez la geometría estatal; los controles reutilizan esta copia."""
    geometria = cargar_geom()
    poligonos = geometria.loc[geometria["ENTIDAD"].eq(estado), ["ID_SECCION", "geometry"]]
    return json.loads(poligonos.to_json(drop_id=True)), tuple(poligonos.total_bounds)


def preparar_mapa(geojson: dict, resultados: pd.DataFrame, aportes: pd.DataFrame | None = None,
                  partidos: tuple[str, ...] = ()) -> tuple[dict, int]:
    """Agrega etiquetas y colores a la copia del GeoJSON estatal."""
    por_seccion = {
        seccion: (clase, margen, faltante, votos)
        for seccion, clase, margen, faltante, votos in resultados[
            ["ID_SECCION", "clase", "margen_pct", "faltante_pct", "votos_para_ganar"]
        ].itertuples(index=False, name=None)
    }
    sin_fila = 0
    por_partido = {}
    if aportes is not None:
        por_partido = {
            fila["ID_SECCION"]: " | ".join(
                f"{partido}: {int(fila[f'rep_{partido}']):,} votos "
                f"({fila[f'pct_candidatura_{partido}']:.1f}% candidatura)"
                for partido in partidos
            )
            for _, fila in aportes.iterrows()
        }
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
        if seccion in por_partido:
            propiedades["txt"] += " | " + por_partido[seccion]
    return geojson, sin_fila


@st.cache_data(show_spinner="Cargando elecciones 2024…")
def cargar_elecciones() -> dict[str, pd.DataFrame]:
    return {
        "presidencia": pd.read_parquet(PRESIDENCIA_PARQUET),
        "diputaciones": pd.read_parquet(DIPUTACIONES_PARQUET),
        "senadurias": pd.read_parquet(SENADURIAS_PARQUET),
    }


@st.cache_data
def cargar_cpv_seccion() -> pd.DataFrame | None:
    ruta = PRESIDENCIA_PARQUET.parent / "cpv_2020_seccion.parquet"
    return pd.read_parquet(ruta) if ruta.exists() else None


@st.cache_data(show_spinner="Calculando fidelidad por partido…")
def cargar_analisis_fidelidad(ambito: str, estado: int) -> pd.DataFrame:
    precalculado = PRESIDENCIA_PARQUET.parent / SALIDAS[ambito]
    if precalculado.exists():
        tabla = pd.read_parquet(precalculado)
        return tabla.loc[tabla["ID_ESTADO"].eq(estado)] if ambito == "estado" else tabla
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


@st.cache_data(show_spinner="Preparando Excel…")
def preparar_excel_demo(resultados: pd.DataFrame, parametros: dict) -> bytes:
    return construir_excel(resultados, parametros)


def analizar_estado(
    sec: pd.DataFrame, estado: int, evaluar: str, candidaturas: list[str]
) -> tuple[Umbrales, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Calcula el contexto solo cuando se abre un análisis territorial."""
    umbrales = Umbrales()
    estado_sec = sec.loc[sec["ID_ESTADO"].eq(estado) & sec["estado"].ne("extranjero")]
    res = analizar_candidatura(estado_sec, evaluar, umbrales)
    distritos = agregar(res, "distrito", candidaturas, evaluar, umbrales)
    activos = estado_sec.loc[estado_sec[evaluar].notna(), "ID_DISTRITO_FEDERAL"].unique()
    distritos = distritos.loc[distritos["ID_DISTRITO_FEDERAL"].isin(activos)].copy()
    return umbrales, estado_sec, res, distritos


def mostrar_resumen_clases(conteos: pd.Series) -> None:
    """Seis cifras legibles también en pantallas estrechas."""
    tarjetas = "".join(
        '<div class="lab-metric" style="--metric-color:rgb({})">'
        '<span class="lab-metric-label">{}</span>'
        '<strong>{:,}</strong></div>'.format(
            ",".join(map(str, COLORES[clase])), ETIQUETAS_CLASE[clase], int(conteos[clase])
        )
        for clase in CLASES
    )
    st.html("""
<style>
.lab-metrics{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:9px;margin:6px 0 10px}
.lab-metric{min-width:0;padding:13px 12px 12px;border:1px solid #382d47;border-top:3px solid var(--metric-color);border-radius:9px;background:#161321}
.lab-metric-label{display:block;color:#d4cbdc;font-size:12px;line-height:1.25;min-height:31px}
.lab-metric strong{display:block;margin-top:7px;color:#f6f1f9;font-size:clamp(1.35rem,2.5vw,2rem);font-variant-numeric:tabular-nums}
@media(max-width:700px){.lab-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.lab-metric-label{min-height:0}.lab-metric strong{font-size:1.55rem}}
</style>
<section class="lab-metrics" aria-label="Secciones por clasificación">""" + tarjetas + "</section>")


st.set_page_config(page_title="LABORATORIO ELECTORAL", layout="wide")
st.html("""
<style>
.lab-masthead{display:flex;align-items:center;justify-content:space-between;gap:16px;
  padding:4px 0 19px;border-bottom:1px solid #38204d;font-family:Arial,Helvetica,sans-serif}
.lab-brand{font-size:13px;font-weight:800;letter-spacing:.18em;color:#e8d6f4}
@media(max-width:640px){.lab-masthead{padding-bottom:12px}.lab-brand{font-size:11px}}
</style>
<header class="lab-masthead"><span class="lab-brand">CARTOGRAFUNK / LABORATORIO ELECTORAL</span></header>
""")
st.caption("Elige la elección, la candidatura y el territorio para explorar sus resultados.")

col_eleccion, col_candidatura, col_partidos, col_estado = st.columns([1.4, 1.3, 1.5, 1.3])
with col_eleccion:
    eleccion = st.selectbox("Elección", [
        "Presidencia 2024", "Diputaciones MR 2024", "Senadurías MR 2024",
    ])
sec = cargar_resultados(eleccion)
CANDS = [col for col in sec if col.startswith("cand_") and sec[col].notna().any()]
with col_candidatura:
    evaluar = st.selectbox(
        "Candidatura a evaluar", CANDS,
        index=CANDS.index("cand_PVEM_PT_MORENA") if "cand_PVEM_PT_MORENA" in CANDS else 0,
        format_func=lambda col: NOMBRES.get(col, col.removeprefix("cand_").replace("_", "-")),
    )
miembros = MIEMBROS_COALICION.get(evaluar, ())
with col_partidos:
    if miembros:
        elegidos = st.multiselect(
            "Partidos de la coalición", ["Todos", *miembros], default=["Todos"],
            key=f"partidos_{evaluar}",
        )
        partidos = tuple(miembros if "Todos" in elegidos else elegidos)
    else:
        partidos = ()
        st.caption("Candidatura individual: sin reparto de coalición.")
estados = sorted(sec.loc[sec["estado"].ne("extranjero"), "ID_ESTADO"].unique())
nombres_estados = sec.drop_duplicates("ID_ESTADO").set_index("ID_ESTADO")["NOMBRE_ESTADO"].to_dict()
with col_estado:
    estado = st.selectbox(
        "Estado (clave INE)", estados,
        index=estados.index(22) if 22 in estados else 0,
        format_func=lambda clave: f"{clave:02d} - {nombres_estados[clave]}",
    )

tab_que, tab_casillas, tab_mapa, tab_prioridad, tab_fidelidad, tab_calidad, tab_local, tab_forecast = st.tabs([
    "Introducción", "Dashboard · campaña", "Mapa y secciones", "Priorización",
    "Apoyo mínimo", "Calidad de datos", "Piloto local IEEQ", "Forecasting · diagnóstico",
], default="Introducción", key="vista_laboratorio", on_change="rerun")
with tab_que:
    mostrar_portada(eleccion)

with tab_mapa:
    if tab_mapa.open:
        st.caption(f"Elección seleccionada: {eleccion}. El mapa y las clases corresponden a la candidatura.")
        umbrales, estado_sec, res, distritos = analizar_estado(sec, estado, evaluar, CANDS)
        aportes, resumen_partidos = (
            aportes_coalicion(res, evaluar, partidos)
            if partidos else (None, None)
        )

        conteos = res["clase"].value_counts(sort=False).reindex(CLASES, fill_value=0)
        mostrar_resumen_clases(conteos)
        st.caption(f"{int(res['estado'].eq('sin_resultado').sum())} secciones sin resultado en este estado.")

        cpv = cargar_cpv_seccion()
        if cpv is not None:
            st.subheader("¿Por qué?")
            st.caption("asociación, no causa · CPV 2020 vs votos 2024 · Cada fila es una sección; el estado solo filtra la muestra. El INE resecciona: una clave igual puede abarcar otra población en 2024.")
            clases_perfil = ("ganada_solida", "perdida_competitiva", "perdida_lejana")
            perfil = perfil_clases(res, cpv, estado, clases_perfil, "perdida_lejana", max_frases=3)
            st.write("Perfil CPV de las secciones por clase de candidatura:")
            st.caption("Diferencias estandarizadas frente a las secciones de derrota lejana.")
            tabla_perfil = perfil["tabla"].drop(columns=[c for c in perfil["tabla"] if c.startswith("n_") or c == "variable"])
            st.dataframe(tabla_perfil.rename(columns={
                "etiqueta": "Variable", "media_ganada_solida": "Sólida %",
                "media_perdida_competitiva": "Competitiva %",
                "media_perdida_lejana": "Lejana %",
                "dif_est_ganada_solida_vs_perdida_lejana": "Dif. est. sólida",
                "dif_est_perdida_competitiva_vs_perdida_lejana": "Dif. est. competitiva",
            }), hide_index=True, width="stretch", column_config={
                "Variable": st.column_config.TextColumn(width="medium"),
                **{c: st.column_config.NumberColumn(format="%.1f", width="small")
                   for c in ("Sólida %", "Competitiva %", "Lejana %")},
                **{c: st.column_config.NumberColumn(format="%.2f", width="small")
                   for c in ("Dif. est. sólida", "Dif. est. competitiva")},
            })
            for frase in perfil["frases"]:
                st.write("• " + frase)
            with st.expander("Avanzado: asociaciones con resultados"):
                st.caption("Correlación de Pearson y regresión ridge estandarizada (λ = 0,1). La ventaja firmada es positiva al ganar, negativa al perder y cero en empate. Faltante y alcanzabilidad usan solo derrotas; alcanzabilidad es 0/1. Las betas ajustadas pueden tener otra dirección que la correlación. Sin inferencia causal.")
                for objetivo, titulo in (
                    ("ventaja_firmada", "Ventaja firmada"),
                    ("faltante_pct", "Faltante en derrotas"),
                    ("alcanzable_por_abstencion", "Alcanzable por abstención en derrotas"),
                ):
                    informe = explicar(res, cpv, evaluar, estado, objetivo)
                    st.markdown(f"**{titulo}** · {informe['n']:,} secciones")
                    if informe["variables"]:
                        st.dataframe(pd.DataFrame(informe["variables"]).rename(columns={
                            "etiqueta": "Variable", "correlacion": "Correlación",
                            "beta_estandarizada": "Beta estandarizada",
                        })[["Variable", "Correlación", "Beta estandarizada"]], hide_index=True)
                    else:
                        st.info(informe["nota"])

        geojson_estado, limites = cargar_poligonos_estado(estado)
        mapa, sin_fila = preparar_mapa(geojson_estado, res, aportes, partidos)
        limite_entidad, limites_municipios, posicion_etiqueta, n_municipios = cargar_limites_estado(estado)
        minx, miny, maxx, maxy = limites
        capa_secciones = pdk.Layer(
            "GeoJsonLayer",
            data=mapa,
            get_fill_color="properties.color",
            get_line_color=[255, 255, 255],
            line_width_min_pixels=0.5,
            pickable=True,
            opacity=0.8,
        )
        capa_municipios = pdk.Layer(
            "GeoJsonLayer", data=limites_municipios, filled=False, stroked=True,
            get_line_color=[255, 255, 255, 205], line_width_min_pixels=1.7,
            line_width_max_pixels=2.2, pickable=False,
        )
        capa_entidad = pdk.Layer(
            "GeoJsonLayer", data=limite_entidad, filled=False, stroked=True,
            get_line_color=[255, 255, 255, 255], line_width_min_pixels=3.4,
            line_width_max_pixels=4.2, pickable=False,
        )
        etiqueta = pdk.Layer(
            "TextLayer",
            data=[{"position": posicion_etiqueta, "label": f"{estado:02d}  {nombres_estados[estado]}"}],
            get_position="position", get_text="label", get_size=18,
            get_color=[255, 255, 255], background=True,
            get_background_color=[18, 35, 57, 232], get_border_color=[255, 255, 255, 235],
            get_border_width=1, background_padding=[12, 8], background_border_radius=6,
            get_pixel_offset=[0, -24], pickable=False,
        )
        latitud = (miny + maxy) / 2
        ancho = max(maxx - minx, 0.01)
        alto = max((maxy - miny) / math.cos(math.radians(latitud)), 0.01)
        zoom = min(
            math.log2(360 * 430 / (512 * ancho * 1.3)),
            math.log2(360 * 530 / (512 * alto * 1.3)),
        )
        vista = pdk.ViewState(latitude=latitud, longitude=(minx + maxx) / 2,
                              zoom=max(5.0, min(10.0, zoom)))
        st.pydeck_chart(
            pdk.Deck(
                layers=[capa_secciones, capa_municipios, capa_entidad, etiqueta],
                initial_view_state=vista, tooltip={"text": "{txt}"},
            ),
            height=550,
            alt=f"Rentabilidad por sección en {nombres_estados[estado]}, con {n_municipios} límites municipales y contorno estatal.",
        )
        st.caption(
            f"Blanco: {n_municipios} municipios de 00mun y contorno estatal de 00ent. "
            f"Gris: {sin_fila} polígonos sin fila de resultados. Trazos locales simplificados."
        )

        st.subheader("Secciones más cercanas a la victoria")
        with st.expander("Cómo leer las tablas"):
            st.markdown(
                "**Clasificación:** cercanía de la candidatura evaluada al primer lugar. "
                "**Margen (pp):** ventaja sobre el segundo lugar en caso de victoria. "
                "**Faltante (pp):** distancia al primer lugar en caso de derrota o empate. "
                "**Votos para ganar:** votos adicionales necesarios para superar al primer lugar; en un empate es 1. "
                "**Abstención:** lista nominal menos votos en lista, descontando las casillas especiales. "
                "**Alcanzable con abstención:** indica si los votos para ganar caben en esa abstención positiva."
            )
        rescatables = res.loc[res["resultado"].isin(("perdida", "empate"))].sort_values("votos_para_ganar")
        columnas_rescate = [
            "ID_SECCION", "MUNICIPIO", "clase", "faltante_pct", "votos_para_ganar",
            "abstencion",
        ]
        tabla_rescatables = rescatables[columnas_rescate].head(30).rename(columns={
            "ID_SECCION": "Sección",
            "MUNICIPIO": "Municipio",
            "clase": "Clasificación",
            "faltante_pct": "Faltante (pp)",
            "votos_para_ganar": "Votos para ganar",
            "abstencion": "Abstención",
        })
        tabla_rescatables["Clasificación"] = tabla_rescatables["Clasificación"].astype("object").map(ETIQUETAS_CLASE)
        st.dataframe(
            tabla_rescatables, hide_index=True, width="stretch",
            column_config={
                "Sección": st.column_config.TextColumn(width="small"),
                "Municipio": st.column_config.TextColumn(width="medium"),
                "Clasificación": st.column_config.TextColumn(width="medium"),
                "Faltante (pp)": st.column_config.NumberColumn(format="%.1f", width="small"),
                "Votos para ganar": st.column_config.NumberColumn(width="small"),
                "Abstención": st.column_config.NumberColumn(width="small"),
            },
        )

        st.subheader("Distritos del estado")
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
            **{columna: f"{NOMBRES.get(columna, columna.removeprefix('cand_').replace('_', '-'))} - votos" for columna in CANDS},
            "resultado": "Resultado",
            "clase": "Clasificación",
            "margen_pct": "Margen (pp)",
            "faltante_pct": "Faltante (pp)",
            "votos_para_ganar": "Votos para ganar",
            "n_perdida_competitiva": "Secciones con derrota competitiva",
        })
        tabla_distritos["Resultado"] = tabla_distritos["Resultado"].map(ETIQUETAS_RESULTADO)
        tabla_distritos["Clasificación"] = tabla_distritos["Clasificación"].astype("object").map(ETIQUETAS_CLASE)
        st.dataframe(tabla_distritos, hide_index=True, width="stretch")

        if miembros:
            st.header("Aporte de partidos dentro de la candidatura")
            st.warning("Reparto de coaliciones experimental (A_propios); la regla oficial no está verificada.")
            if partidos:
                st.subheader("Estado seleccionado")
                st.dataframe(resumen_partidos.round(1), hide_index=True, width="stretch")
                st.subheader("Secciones por partido")
                columnas_comunes = [
                    "ID_SECCION", "MUNICIPIO", "resultado", "clase", "margen_votos",
                    "faltante_votos", "votos_para_ganar",
                ]
                tablas = []
                for partido in partidos:
                    tabla = aportes[columnas_comunes + [
                        f"rep_{partido}", f"pct_candidatura_{partido}", f"pct_validos_{partido}",
                    ]].copy()
                    tabla.insert(2, "Partido", partido)
                    tabla = tabla.rename(columns={
                        "ID_SECCION": "Sección", "MUNICIPIO": "Municipio",
                        "resultado": "Resultado de candidatura", "clase": "Clase de candidatura",
                        "margen_votos": "Margen de candidatura", "faltante_votos": "Faltante de candidatura",
                        "votos_para_ganar": "Votos para ganar candidatura",
                        f"rep_{partido}": "Votos atribuidos",
                        f"pct_candidatura_{partido}": "% de candidatura",
                        f"pct_validos_{partido}": "% de votos válidos",
                    })
                    tabla["Resultado de candidatura"] = tabla["Resultado de candidatura"].map(
                        ETIQUETAS_RESULTADO
                    )
                    tabla["Clase de candidatura"] = tabla["Clase de candidatura"].astype(
                        "object"
                    ).map(ETIQUETAS_CLASE)
                    tablas.append(tabla)
                st.dataframe(pd.concat(tablas, ignore_index=True).round(1), hide_index=True, width="stretch")
                st.caption("votos por partido estimados")
            else:
                st.info("Selecciona al menos un partido o Todos para ver su aporte.")

        st.caption(
            f"{eleccion}: candidaturas calculadas con columnas de _SEC.csv. "
            "Geometría MGE 2024 simplificada a 25 m; EPSG:32614 es una hipótesis de trabajo."
        )

with tab_prioridad:
    if tab_prioridad.open:
        umbrales, estado_sec, res, distritos = analizar_estado(sec, estado, evaluar, CANDS)
        st.subheader("Priorización de secciones")
        st.caption(f"Elección seleccionada: {eleccion}. Los costos y descartes son supuestos del usuario.")
        with st.expander("Avanzado", expanded=False):
            costo_global = st.number_input(
                "Costo estimado por voto (pesos)", min_value=0.0, value=None,
                step=1.0, placeholder="Ingresa tu costo estimado por voto",
            )
            if costo_global is not None:
                st.session_state.setdefault("escenarios_prioridad", {})
                clave_escenario = f"{eleccion}:{estado:02d}:{evaluar}"
                base_prioridad = preparar_priorizacion(res, costo_global)
                guardado = st.session_state["escenarios_prioridad"].get(clave_escenario)
                if guardado is not None:
                    anteriores = guardado.set_index("ID_SECCION")
                    for columna in ("costo_por_voto", "descartar"):
                        base_prioridad[columna] = base_prioridad["ID_SECCION"].map(
                            anteriores[columna]
                        ).fillna(base_prioridad[columna])
                    base_prioridad["costo_estimado"] = (
                        base_prioridad["votos_para_ganar"] * base_prioridad["costo_por_voto"]
                    )
                columnas_editor = {
                    "ID_SECCION": "Sección", "MUNICIPIO": "Municipio",
                    "votos_para_ganar": "Votos para ganar", "abstencion": "Abstención",
                    "costo_por_voto": "Costo por voto", "costo_estimado": "Costo estimado",
                    "descartar": "Descartar",
                }
                editor = base_prioridad[[
                    "ID_SECCION", "MUNICIPIO", "votos_para_ganar", "abstencion",
                    "costo_por_voto", "costo_estimado", "descartar",
                ]].rename(columns=columnas_editor)
                editado = st.data_editor(
                    editor, hide_index=True, width="stretch", key=f"prioridad_{eleccion}_{estado}_{evaluar}",
                    disabled=["Sección", "Municipio", "Votos para ganar", "Abstención", "Costo estimado"],
                    column_config={"Costo por voto": st.column_config.NumberColumn(min_value=0.0, step=1.0)},
                )
                tabla_prioridad = base_prioridad.copy()
                tabla_prioridad["costo_por_voto"] = editado["Costo por voto"].to_numpy()
                tabla_prioridad["descartar"] = editado["Descartar"].to_numpy()
                st.session_state["escenarios_prioridad"][clave_escenario] = tabla_prioridad[
                    ["ID_SECCION", "costo_por_voto", "descartar"]
                ].copy()
                presupuesto = st.number_input("Presupuesto (pesos)", min_value=0.0, value=10000.0, step=100.0)
                tabla_presupuesto, gastado = presupuestar(tabla_prioridad, presupuesto)
                st.write(f"Secciones que caben: {int(tabla_presupuesto['seleccionada'].sum()):,}. Total gastado: ${gastado:,.2f}.")
                st.dataframe(tabla_presupuesto[[
                    "ID_SECCION", "costo_estimado", "descartar", "seleccionada",
                ]].rename(columns={
                    "ID_SECCION": "Sección", "costo_estimado": "Costo estimado actualizado",
                    "descartar": "Descartar", "seleccionada": "Dentro del presupuesto",
                }), width="stretch")

                distritos_disponibles = sorted(distritos["ID_DISTRITO_FEDERAL"].astype(int).tolist())
                distrito_meta = st.selectbox(
                    "Distrito federal para la meta", distritos_disponibles,
                    index=distritos_disponibles.index(2) if 2 in distritos_disponibles else 0,
                )
                meta = meta_distrital(distritos, distrito_meta)
                st.caption("Supuesto, no pronóstico: los votos nuevos salen de la abstención.")
                if meta is None:
                    st.info("La candidatura ya obtuvo la victoria en este distrito; no hay faltante por cubrir.")
                else:
                    n_necesarias, capacidad = cubrir_meta(tabla_presupuesto, distrito_meta, meta)
                    st.write(f"Meta del distrito: {meta:,} votos. Capacidad disponible: {capacidad:,.0f} votos.")
                    if n_necesarias is None:
                        st.warning("La abstención disponible de las secciones no descartadas no alcanza la meta.")
                    else:
                        st.write(f"Secciones no descartadas necesarias, en orden de costo: {n_necesarias:,}.")

                parametros_excel = {
                    "candidatura": NOMBRES.get(evaluar, evaluar.removeprefix("cand_").replace("_", "-")),
                    "eleccion": eleccion, "estado": f"{estado:02d} - {nombres_estados[estado]}",
                    "fecha": date.today().isoformat(), "umbrales": umbrales,
                    "distritos": distritos, "priorizacion": tabla_presupuesto,
                    "presupuesto": presupuesto,
                }
                st.download_button(
                    "Descargar diagnóstico en Excel",
                    preparar_excel_demo(res, parametros_excel),
                    file_name=f"rentabilidad_{eleccion.split()[0].lower()}_{estado:02d}_{evaluar.removeprefix('cand_')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

        if costo_global is None:
            st.info("Ingresa tu costo estimado por voto")

with tab_fidelidad:
    if tab_fidelidad.open:
        st.subheader("Apoyo mínimo observado 2024")
        st.caption("Elecciones: Presidencia, Diputaciones MR y Senadurías MR de 2024. Diagnóstico exploratorio, no seguimiento de personas ni de años distintos.")
        st.write(
            "Es el menor porcentaje de votos del partido observado en una sección "
            "entre Presidencia, Diputaciones y Senadurías de 2024. No asegura que "
            "hayan votado las mismas personas en las tres boletas."
        )
        st.caption("Clases: propuesta Scouter, umbrales provisionales. Reparto de coaliciones experimental (A_propios), solo 2024.")
        col_ambito, col_partido, col_estado = st.columns(3)
        with col_ambito:
            ambito_fid = st.selectbox("Ámbito de percentiles", ["estado", "nacional"], index=0)
        with col_partido:
            partido_fid = st.selectbox("Partido", PARTIDOS)
        with col_estado:
            estado_fid = st.selectbox(
                "Estado para ver secciones", estados,
                index=estados.index(22) if 22 in estados else 0,
                format_func=lambda clave: f"{clave:02d} - {nombres_estados[clave]}",
            )

        analisis = cargar_analisis_fidelidad(ambito_fid, estado_fid)
        seleccion = analisis.loc[
            analisis["partido"].eq(partido_fid) & analisis["ID_ESTADO"].eq(estado_fid)
        ].copy()
        resumen = seleccion["clase"].value_counts().reindex(["Bastión", "Base fuerte", "Resto"], fill_value=0)
        for columna, clase in zip(st.columns(3), resumen.index):
            columna.metric(clase, int(resumen[clase]))
        st.caption(f"{len(seleccion):,} secciones con resultado y lista nominal ≥ 100 en las tres elecciones; {int(seleccion['volatil'].sum()):,} volátiles.")

        cpv_fid = cargar_cpv_seccion()
        if cpv_fid is not None:
            st.subheader("¿Por qué?")
            st.caption("asociación, no causa · CPV 2020 vs votos 2024 · Cada fila es una sección; el estado solo filtra la muestra. El INE resecciona: una clave igual puede abarcar otra población en 2024.")
            clases_apoyo = ("Bastión", "Base fuerte", "Resto")
            perfil_apoyo = perfil_clases(seleccion, cpv_fid, estado_fid, clases_apoyo, "Resto", max_frases=3)
            st.caption("Diferencias estandarizadas frente a las secciones de Resto.")
            tabla_apoyo = perfil_apoyo["tabla"].drop(columns=[c for c in perfil_apoyo["tabla"] if c.startswith("n_") or c == "variable"])
            st.dataframe(tabla_apoyo.rename(columns={
                "etiqueta": "Variable", "media_Bastión": "Bastión %",
                "media_Base fuerte": "Base fuerte %", "media_Resto": "Resto %",
                "dif_est_Bastión_vs_Resto": "Dif. est. Bastión",
                "dif_est_Base fuerte_vs_Resto": "Dif. est. Base fuerte",
            }), hide_index=True, width="stretch", column_config={
                "Variable": st.column_config.TextColumn(width="medium"),
                **{c: st.column_config.NumberColumn(format="%.1f", width="small")
                   for c in ("Bastión %", "Base fuerte %", "Resto %")},
                **{c: st.column_config.NumberColumn(format="%.2f", width="small")
                   for c in ("Dif. est. Bastión", "Dif. est. Base fuerte")},
            })
            for frase in perfil_apoyo["frases"]:
                st.write("• " + frase)
            with st.expander("Avanzado: apoyo mínimo y CPV"):
                st.caption("Correlación de Pearson y regresión ridge estandarizada (λ = 0,1) del piso_pct del partido; las betas ajustadas pueden diferir de la correlación.")
                informe_apoyo = explicar(seleccion, cpv_fid, partido_fid, estado_fid, "piso_pct")
                st.write(f"{informe_apoyo['n']:,} secciones completas")
                if informe_apoyo["variables"]:
                    st.dataframe(pd.DataFrame(informe_apoyo["variables"]).rename(columns={
                        "etiqueta": "Variable", "correlacion": "Correlación",
                        "beta_estandarizada": "Beta estandarizada",
                    })[["Variable", "Correlación", "Beta estandarizada"]], hide_index=True)
                else:
                    st.info(informe_apoyo["nota"])

        tabla_fid = seleccion[[
            "ID_SECCION", "partido", "piso_pct", "piso_votos", "rango_pp",
            "percentil_piso", "n_grupo", "clase", "volatil", "umbral_rango_pp",
            "primera_en_todas", "coalicion_distinta", "ambito",
        ]].sort_values(["volatil", "piso_pct"], ascending=[False, False]).rename(columns={
            "ID_SECCION": "Sección", "partido": "Partido", "piso_pct": "Apoyo mínimo (%)",
            "piso_votos": "Apoyo mínimo (votos)", "rango_pp": "Variación (puntos)",
            "percentil_piso": "Percentil del apoyo", "n_grupo": "Secciones del grupo",
            "clase": "Clase", "volatil": "Volátil", "umbral_rango_pp": "Umbral de rango (pp)",
            "primera_en_todas": "Primera en las tres", "coalicion_distinta": "Coalición distinta",
            "ambito": "Ámbito",
        })
        st.subheader("Secciones")
        columnas_tabla = {
            "Sección": st.column_config.TextColumn(width="medium"),
            "Apoyo mínimo (%)": st.column_config.NumberColumn(width="medium", format="%.1f"),
            "Apoyo mínimo (votos)": st.column_config.NumberColumn(width="medium"),
            "Variación (puntos)": st.column_config.NumberColumn(width="medium", format="%.1f"),
            "Percentil del apoyo": st.column_config.NumberColumn(width="medium", format="%.1f"),
            "Secciones del grupo": st.column_config.NumberColumn(width="medium"),
            "Umbral de rango (pp)": st.column_config.NumberColumn(width="medium", format="%.1f"),
            "Primera en las tres": st.column_config.CheckboxColumn(width="medium"),
            "Coalición distinta": st.column_config.CheckboxColumn(width="medium"),
        }
        st.dataframe(
            tabla_fid.style.apply(
                lambda fila: ["background-color: #fff0b3; color: #202020" if fila["Volátil"] else ""] * len(fila),
                axis=1,
            ).format({
                "Apoyo mínimo (%)": "{:.1f}", "Variación (puntos)": "{:.1f}",
                "Percentil del apoyo": "{:.1f}", "Umbral de rango (pp)": "{:.1f}",
            }),
            column_config=columnas_tabla, hide_index=True, width="stretch",
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
        st.subheader("Consistencia y relación entre boletas - estado seleccionado")
        st.dataframe(icc.loc[icc["partido"].eq(partido_fid)], width="stretch")
        st.dataframe(correlaciones.loc[correlaciones["partido"].eq(partido_fid)], width="stretch")
        st.caption("Apoyo mínimo observado 2024: diagnóstico exploratorio, no seguimiento de personas ni de años distintos.")

with tab_calidad:
    st.subheader("Notas de calidad de datos")
    st.caption(f"Elección seleccionada: {eleccion}.")
    notas = NOTAS_CALIDAD_DEMO if eleccion == "Presidencia 2024" else (
        "La geometría MGE 2024 usa EPSG:32614 como supuesto de trabajo.",
        "Las candidaturas individuales y coaliciones activas varían por distrito.",
        "Las secciones sin candidatura activa quedan sin clasificación para esa candidatura.",
        "El reparto de coaliciones por partido es experimental (A_propios).",
    )
    for nota in notas:
        st.markdown(f"\\- {nota}")

with tab_local:
    if tab_local.open:
        mostrar_piloto_local(estado, ROOT)

with tab_forecast:
    if tab_forecast.open:
        mostrar_diagnostico_forecast(estado, ROOT)

with tab_casillas:
    if tab_casillas.open:
        if estado == 22:
            boletas, cuatro = st.tabs(["Boletas y apoyo mínimo", "Cuatro preguntas · piloto diputaciones"])
            with boletas:
                mostrar_explorador_boletas(ROOT)
            with cuatro:
                mostrar_dashboard_casillas(estado, ROOT)
        else:
            mostrar_dashboard_casillas(estado, ROOT)
