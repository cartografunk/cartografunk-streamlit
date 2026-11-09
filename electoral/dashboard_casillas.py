"""Dashboard narrativo del piloto local: cuatro preguntas y sus evidencias."""

from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st
from shapely import wkb
from shapely.geometry import mapping, shape

from electoral.diagnostico_casillas import (
    costo_hipotetico, evaluar_partido, incorporar_apoyo_minimo, lista_revision,
    perfil_cpv, proponer_esfuerzo,
)
from electoral.diagnostico_casillas_tab import (
    _cargar, _cargar_apoyo, _cargar_perfiles, _mostrar_ficha_casilla,
)
from electoral.reparto_ieeq import PARTIDOS_COMUNES


GRUPOS_CPV = {
    "Población": ("pct_mujeres", "pct_menores_18", "pct_60_mas", "pct_18_24",
                  "pct_lengua_indigena", "pct_afromexicana"),
    "Educación": ("pct_analfabeta", "pct_posbasica"),
    "Trabajo y salud": ("pct_pea", "pct_sin_salud"),
    "Vivienda y servicios": ("pct_piso_tierra", "pct_sin_agua", "pct_sin_drenaje"),
    "Tecnología y movilidad": ("pct_internet", "pct_automovil"),
}


# ColorBrewer RdYlBu (orden azul → amarillo → rojo), con gris reservado
# para las casillas o secciones sin resultado.
COLOR_FORTALEZA = [44, 123, 182, 235]    # #2c7bb6
COLOR_DEFENSA = [171, 217, 233, 235]     # #abd9e9
COLOR_EMPATE = [255, 255, 191, 235]      # #ffffbf
COLOR_CERCANA = [253, 174, 97, 235]     # #fdae61
COLOR_BASE = [215, 25, 28, 235]         # #d7191c
COLOR_SIN_DATO = [150, 160, 174, 190]
COLOR_SECCION_AMPLIA = [*COLOR_FORTALEZA[:3], 135]
COLOR_SECCION_CORTA = [*COLOR_DEFENSA[:3], 135]
COLOR_SECCION_EMPATE = [*COLOR_EMPATE[:3], 135]
COLOR_SECCION_CERCANA = [*COLOR_CERCANA[:3], 140]
COLOR_SECCION_LEJANA = [*COLOR_BASE[:3], 135]
COLOR_SECCION_SIN_DATO = [*COLOR_SIN_DATO[:3], 75]
CLASES_CERCANAS = ("perdida_competitiva", "ganada_ajustada", "empate")
NOMBRES_CLASE = {
    "ganada_solida": "Ventaja amplia", "ganada_ajustada": "Ventaja estrecha",
    "empate": "Empate", "perdida_competitiva": "Pérdida cercana",
    "perdida_lejana": "Pérdida lejana", "sin_resultado": "Sin resultado",
}


@st.cache_data(max_entries=2)
def _cargar_puntos(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["ID_SECCION", "CASILLA_ETIQUETA", "LATITUD", "LONGITUD"])
    puntos = pd.read_parquet(path, columns=["ID_SECCION", "CASILLA_ETIQUETA", "LATITUD",
                                            "LONGITUD", "CALIDAD"])
    return puntos.loc[puntos.CALIDAD.isin(("clave_domicilio_y_poligono",
                                          "domicilio_y_revision_manual",
                                          "sede_revisada_visual_usuario"))].copy()


def preparar_sedes(casillas: pd.DataFrame, puntos: pd.DataFrame) -> pd.DataFrame:
    """Una marca por sede; conserva la relación con casillas B/C/E seleccionadas."""
    if casillas.empty or puntos.empty:
        return pd.DataFrame(columns=["ID_SECCION", "LATITUD", "LONGITUD", "CASILLAS",
                                     "CASILLA_INICIAL", "NUM_CASILLAS", "SENAL", "COLOR"])
    unidos = casillas[["ID_SECCION", "CASILLA_ETIQUETA", "CLASE"]].merge(
        puntos[["ID_SECCION", "CASILLA_ETIQUETA", "LATITUD", "LONGITUD"]],
        on=["ID_SECCION", "CASILLA_ETIQUETA"], how="inner", validate="one_to_one")
    if unidos.empty:
        return pd.DataFrame(columns=["ID_SECCION", "LATITUD", "LONGITUD", "CASILLAS",
                                     "CASILLA_INICIAL", "NUM_CASILLAS", "SENAL", "COLOR"])
    filas = []
    for (seccion, lat, lon), grupo in unidos.groupby(["ID_SECCION", "LATITUD", "LONGITUD"], sort=True):
        clases = set(grupo.CLASE)
        if "perdida_competitiva" in clases:
            senal, color = "Pérdida cercana", COLOR_CERCANA
        elif "empate" in clases:
            senal, color = "Empate", COLOR_EMPATE
        elif "ganada_ajustada" in clases:
            senal, color = "Ventaja estrecha", COLOR_DEFENSA
        elif "ganada_solida" in clases:
            senal, color = "Ventaja amplia observada", COLOR_FORTALEZA
        elif "perdida_lejana" in clases:
            senal, color = "Pérdida lejana", COLOR_BASE
        else:
            senal, color = "Sin resultado", COLOR_SIN_DATO
        casillas_sitio = sorted(grupo.CASILLA_ETIQUETA)
        filas.append({"ID_SECCION": seccion, "LATITUD": float(lat), "LONGITUD": float(lon),
                      "CASILLAS": ", ".join(casillas_sitio), "CASILLA_INICIAL": casillas_sitio[0],
                      "NUM_CASILLAS": len(casillas_sitio), "SENAL": senal, "COLOR": color})
    return pd.DataFrame(filas)


@st.cache_data(max_entries=1)
def _geometrias_seccion(path: Path) -> dict[str, dict]:
    """Geometría 2024 simplificada para contexto visual, sólo Querétaro."""
    if not path.exists():
        return {}
    tabla = pd.read_parquet(path, columns=["ID_SECCION", "ENTIDAD", "geometry"],
                            filters=[("ENTIDAD", "=", 22)])
    return {str(fila.ID_SECCION): mapping(wkb.loads(fila.geometry).simplify(
        0.0005, preserve_topology=True)) for fila in tabla.itertuples()}


def _capa_secciones(base: pd.DataFrame, geometrias: dict[str, dict]) -> dict:
    """Color por mediana de margen partidario de las casillas de la sección."""
    resumen = base.groupby("ID_SECCION").agg(
        MARGEN_PP=("MARGEN_PP", "median"), CASILLAS=("CASILLA_ETIQUETA", "count"))
    features = []
    for seccion, fila in resumen.iterrows():
        geometria = geometrias.get(str(seccion))
        if geometria is None:
            continue
        margen = fila.MARGEN_PP
        if pd.isna(margen):
            color = COLOR_SECCION_SIN_DATO
        elif margen >= 10:
            color = COLOR_SECCION_AMPLIA
        elif margen > 0:
            color = COLOR_SECCION_CORTA
        elif margen == 0:
            color = COLOR_SECCION_EMPATE
        elif margen >= -10:
            color = COLOR_SECCION_CERCANA
        else:
            color = COLOR_SECCION_LEJANA
        features.append({"type": "Feature", "geometry": geometria,
                         "properties": {"ID_SECCION": str(seccion), "COLOR": color,
                                        "CASILLAS": int(fila.CASILLAS),
                                        "SENAL": (f"Mediana del margen: {margen:+.1f} pp"
                                                  if pd.notna(margen) else "Sin margen")}})
    return {"type": "FeatureCollection", "features": features}


def _mostrar_leyenda_mapa() -> None:
    """Simbología visible para ambas capas, con los colores exactos del mapa."""
    def item(color: list[int], etiqueta: str, forma: str) -> str:
        r, g, b, alfa = color
        return (f'<span class="leyenda-item"><i class="leyenda-{forma}" '
                f'style="background:rgba({r},{g},{b},{alfa / 255:.3f})"></i>'
                f'{etiqueta}</span>')

    secciones = "".join((
        item(COLOR_SECCION_AMPLIA, "Ventaja amplia ≥10 pp", "seccion"),
        item(COLOR_SECCION_CORTA, "Ventaja estrecha &lt;10 pp", "seccion"),
        item(COLOR_SECCION_EMPATE, "Empate", "seccion"),
        item(COLOR_SECCION_CERCANA, "Pérdida cercana ≤10 pp", "seccion"),
        item(COLOR_SECCION_LEJANA, "Pérdida lejana &gt;10 pp", "seccion"),
        item(COLOR_SECCION_SIN_DATO, "Sin resultado", "seccion"),
    ))
    sedes = "".join((
        item(COLOR_FORTALEZA, "Ventaja amplia", "sede"),
        item(COLOR_DEFENSA, "Ventaja estrecha", "sede"),
        item(COLOR_EMPATE, "Empate", "sede"),
        item(COLOR_CERCANA, "Pérdida cercana", "sede"),
        item(COLOR_BASE, "Pérdida lejana", "sede"),
        item(COLOR_SIN_DATO, "Sin resultado", "sede"),
    ))
    st.html(f"""
    <style>
    .leyenda-mapa{{display:grid;gap:.55rem;padding:.75rem .9rem;margin:.25rem 0 .8rem;
      background:#06263d;border:1px solid #155477;border-radius:12px;color:#d5edfa}}
    .leyenda-fila{{display:flex;align-items:center;flex-wrap:wrap;gap:.35rem .8rem}}
    .leyenda-titulo{{min-width:5.8rem;color:#8ccde8;font-size:.68rem;font-weight:700;
      letter-spacing:.09em;text-transform:uppercase}}
    .leyenda-item{{display:inline-flex;align-items:center;gap:.35rem;font-size:.75rem;
      white-space:nowrap}}
    .leyenda-item i{{display:inline-block;width:.8rem;height:.8rem;flex:none;
      border:1px solid #a7d7ec}}
    .leyenda-sede{{border-radius:50%}}
    .leyenda-seccion{{border-radius:2px}}
    </style>
    <div class="leyenda-mapa" role="group" aria-label="Simbología del mapa electoral">
      <div class="leyenda-fila"><span class="leyenda-titulo">Secciones</span>{secciones}</div>
      <div class="leyenda-fila"><span class="leyenda-titulo">Sedes</span>{sedes}</div>
    </div>
    """)


def _cabecera_pregunta(numero: int, pregunta: str, respuesta: str, metodo: str) -> None:
    st.markdown(f"#### {numero:02d} · {pregunta}")
    st.write(respuesta)
    with st.expander("Cómo llegamos a esta respuesta", on_change="rerun") as evidencia:
        if evidencia.open:
            st.caption(metodo)


def _patron(base: pd.DataFrame, puntos: pd.DataFrame) -> None:
    _cabecera_pregunta(
        1, "¿Dónde vas a ganar?",
        "Aún no podemos afirmar una victoria futura por casilla. El mapa muestra dónde hubo ventajas y pérdidas cercanas observadas en 2024 para investigar cada lugar.",
        "Cómo llegamos: votos IEEQ de diputaciones locales MR por casilla B/C/E; "
        "comparamos cada partido con el mayor de los otros seis partidos atribuidos. "
        "Son resultados pasados, no predicciones de 2027.")
    modo = st.segmented_control("Explorar resultados", ["Cercanas", "Fortalezas", "Todas"],
                                default="Todas", key="dashboard_modo_patron")
    if modo == "Cercanas":
        vista = base.loc[base.CLASE.isin(CLASES_CERCANAS)].copy()
    elif modo == "Fortalezas":
        vista = base.loc[base.CLASE.eq("ganada_solida")].copy()
    else:
        vista = base.copy()
    sedes = preparar_sedes(vista, puntos)
    seccion_activa = st.session_state.get("dashboard_seccion_activa")
    if seccion_activa and not vista.ID_SECCION.eq(seccion_activa).any():
        seccion_activa = None
        st.session_state["dashboard_seccion_activa"] = None
    seleccion = st.session_state.get("dashboard_casilla_seleccionada")
    punto_seleccionado = None
    if seleccion:
        coincide = puntos.loc[puntos.ID_SECCION.eq(seleccion[0])
                              & puntos.CASILLA_ETIQUETA.eq(seleccion[1])]
        if not coincide.empty:
            punto_seleccionado = coincide.iloc[0]
    a, b, c = st.columns(3)
    a.metric("Casillas en vista", f"{len(vista):,}")
    b.metric("Secciones en vista", f"{vista.ID_SECCION.nunique():,}")
    c.metric("Sedes con punto disponibles", f"{len(sedes):,}")
    izquierda, derecha = st.columns([1.35, 1], gap="medium")
    elegido_mapa = None
    with izquierda:
        st.markdown("**Mapa de sedes 2024**")
        capa = st.segmented_control("Vista del mapa", ["Sedes de casillas", "Sólo secciones"],
                                    default="Sedes de casillas", key="dashboard_capa_mapa")
        _mostrar_leyenda_mapa()
        if seccion_activa and st.button("Mostrar todas las secciones", key="dashboard_limpiar_seccion",
                                        icon=":material/zoom_out_map:"):
            st.session_state["dashboard_seccion_activa"] = None
            st.session_state["dashboard_casilla_seleccionada"] = None
            st.rerun()
        if sedes.empty:
            st.info("No hay puntos de sede para este filtro; consulta la lista de casillas.")
        else:
            capas = []
            geometrias = _geometrias_seccion(
                Path(__file__).resolve().parents[1] / "data/electoral/secciones_2024_geom.parquet")
            secciones_mapa = _capa_secciones(vista, geometrias)
            if secciones_mapa["features"]:
                capas.append(pdk.Layer(
                    "GeoJsonLayer", id="secciones", data=secciones_mapa,
                    pickable=True, filled=True, stroked=True,
                    get_fill_color="properties.COLOR",
                    get_line_color=[80, 194, 226, 145],
                    line_width_min_pixels=1))
            sedes_visibles = (sedes.loc[sedes.ID_SECCION.eq(seccion_activa)]
                              if seccion_activa else sedes
                              if capa == "Sedes de casillas" or not secciones_mapa["features"]
                              else sedes.iloc[0:0])
            capa = pdk.Layer(
                "ScatterplotLayer", id="sedes", data=sedes_visibles.to_dict("records"),
                get_position="[LONGITUD, LATITUD]", get_radius=45,
                radius_min_pixels=3, radius_max_pixels=8,
                get_fill_color="COLOR", get_line_color=[22, 20, 30, 255],
                line_width_min_pixels=1, stroked=True, pickable=True)
            capas.append(capa)
            if punto_seleccionado is not None:
                capas.append(pdk.Layer(
                    "ScatterplotLayer", id="seleccion", pickable=False,
                    data=[{"LONGITUD": float(punto_seleccionado.LONGITUD),
                           "LATITUD": float(punto_seleccionado.LATITUD)}],
                    get_position="[LONGITUD, LATITUD]", get_radius=110,
                    radius_min_pixels=12, radius_max_pixels=20,
                    get_fill_color=[255, 255, 255, 45],
                    get_line_color=[255, 255, 255, 255], line_width_min_pixels=3,
                    stroked=True))
            lat = float(punto_seleccionado.LATITUD) if punto_seleccionado is not None else 20.64
            lon = float(punto_seleccionado.LONGITUD) if punto_seleccionado is not None else -100.31
            zoom = 13.5 if punto_seleccionado is not None else 9.2
            if punto_seleccionado is None and seccion_activa in geometrias:
                centro = shape(geometrias[seccion_activa]).centroid
                lat, lon, zoom = centro.y, centro.x, 12.5
            evento_mapa = st.pydeck_chart(
                pdk.Deck(layers=capas, map_style=pdk.map_styles.CARTO_DARK,
                         initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom),
                         tooltip={"text": "Sección {ID_SECCION}\nCasillas {CASILLAS}\n{SENAL}"}),
                height=420, on_select="rerun", selection_mode="single-object",
                key=f"dashboard_mapa_{modo}_{capa}_{seccion_activa}_{seleccion}",
                alt="Sedes de casillas 2024 coloreadas por resultado cercano o ventaja estrecha")
            objetos = evento_mapa.selection.objects.get("sedes", [])
            if objetos:
                elegido_mapa = (str(objetos[0]["ID_SECCION"]), str(objetos[0]["CASILLA_INICIAL"]))
            if elegido_mapa and elegido_mapa != st.session_state.get("dashboard_ultimo_click_mapa"):
                st.session_state["dashboard_ultimo_click_mapa"] = elegido_mapa
                st.session_state["dashboard_seccion_activa"] = elegido_mapa[0]
                st.session_state["dashboard_casilla_seleccionada"] = elegido_mapa
                st.rerun()
            secciones_elegidas = evento_mapa.selection.objects.get("secciones", [])
            if secciones_elegidas:
                objeto = secciones_elegidas[0]
                clave_seccion = str(objeto.get("properties", {}).get("ID_SECCION")
                                    or objeto.get("ID_SECCION", ""))
                if clave_seccion and clave_seccion != seccion_activa:
                    st.session_state["dashboard_seccion_activa"] = clave_seccion
                    st.session_state["dashboard_casilla_seleccionada"] = None
                    st.rerun()
    with derecha:
        st.markdown(f"**Casillas de {seccion_activa}**" if seccion_activa else "**Casillas del filtro**")
        vista_tabla = (vista.loc[vista.ID_SECCION.eq(seccion_activa)]
                       if seccion_activa else vista)
        tabla = vista_tabla[["ID_SECCION", "CASILLA_ETIQUETA", "CLASE", "MARGEN_PP",
                       "VOTOS_PARA_LIDERAR"]].rename(columns={
            "ID_SECCION": "Sección", "CASILLA_ETIQUETA": "Casilla", "CLASE": "Resultado",
            "MARGEN_PP": "Margen (pp)", "VOTOS_PARA_LIDERAR": "Votos para liderar",
        }).reset_index(drop=True)
        tabla.insert(0, "", ["●" if seleccion == (s, c) else "" for s, c in
                              zip(tabla["Sección"], tabla["Casilla"])])
        tabla["Resultado"] = tabla["Resultado"].map(NOMBRES_CLASE).fillna("Sin clasificar")
        evento_tabla = st.dataframe(
            tabla, hide_index=True, width="stretch", height=420,
            on_select="rerun", selection_mode="single-row",
            key=f"dashboard_tabla_patron_{modo}_{seccion_activa}",
            column_config={"Sección": st.column_config.TextColumn(pinned=True),
                           "Margen (pp)": st.column_config.NumberColumn(format="%+.1f")},
            alt="Casillas filtradas; selecciona una para ver su sede y resultado")
        st.caption("Selecciona una fila o un punto para abrir la ficha de casilla.")
    indices = evento_tabla.selection.rows
    if indices and 0 <= indices[0] < len(vista_tabla):
        fila = vista_tabla.reset_index(drop=True).iloc[indices[0]]
        clave = (str(fila.ID_SECCION), str(fila.CASILLA_ETIQUETA))
        if clave != st.session_state.get("dashboard_ultimo_click_tabla"):
            st.session_state["dashboard_ultimo_click_tabla"] = clave
            st.session_state["dashboard_seccion_activa"] = clave[0]
            st.session_state["dashboard_casilla_seleccionada"] = clave
            st.rerun()
    if seleccion:
        fila = vista.loc[vista.ID_SECCION.eq(seleccion[0])
                         & vista.CASILLA_ETIQUETA.eq(seleccion[1])]
        if len(fila) == 1:
            _mostrar_ficha_casilla(fila.iloc[0], base)


def _perfil(base: pd.DataFrame, partido: str) -> None:
    _cabecera_pregunta(
        2, "¿Por qué aparece ese resultado?",
        "Comparamos rasgos censales de las secciones de cada clase. Estos contrastes sugieren dónde investigar; no explican la causa del voto individual.",
        "Cómo llegamos: 15 tasas del CPV 2020 en ECEG INEGI–INE, enlazadas por sección "
        "y limitadas a geometrías comparables. Cada sección cuenta una vez por clase. "
        "CPV 2020 vs votos 2024 · asociación, no causa.")
    perfil = perfil_cpv(base, max_frases=3)
    tabla = perfil["tabla"]
    st.caption(f"{partido}: se comparan 15 rasgos del CPV 2020; se muestran hasta cinco por grupo.")
    grupo = st.selectbox("Grupo de rasgos CPV", ["Todos", *GRUPOS_CPV],
                         key="dashboard_grupo_cpv")
    objetivo = st.selectbox("Comparar con pérdida lejana", ["perdida_competitiva", "ganada_solida"],
                            format_func=lambda x: "Pérdida cercana" if x == "perdida_competitiva" else "Ventaja amplia",
                            key="dashboard_clase_perfil")
    diferencia = f"dif_est_{objetivo}_vs_perdida_lejana"
    columnas = ["etiqueta", f"media_{objetivo}", "media_perdida_lejana", diferencia]
    candidatas = tabla if grupo == "Todos" else tabla.loc[tabla.variable.isin(GRUPOS_CPV[grupo])]
    top = candidatas[columnas].dropna(subset=[diferencia]).copy()
    top = top.reindex(top[diferencia].abs().sort_values(ascending=False).index).head(5)
    if top.empty:
        st.info("No hay suficientes secciones comparables para este contraste.")
        return
    st.caption(f"Secciones con dato: {perfil['n_secciones_por_clase'].get(objetivo, 0)} en la clase elegida "
               f"y {perfil['n_secciones_por_clase'].get('perdida_lejana', 0)} en pérdida lejana.")
    izquierda, derecha = st.columns([1, 1], gap="medium")
    with izquierda:
        st.markdown(f"**{len(top)} mayores diferencias estandarizadas · {grupo.lower()}**")
        grafica = top[["etiqueta", diferencia]].rename(columns={"etiqueta": "Rasgo", diferencia: "Diferencia"})
        chart = alt.Chart(grafica).mark_bar(color="#F8AA4A").encode(
            x=alt.X("Diferencia:Q", title="Diferencia estandarizada"),
            y=alt.Y("Rasgo:N", sort=grafica.Rasgo.tolist(),
                    axis=alt.Axis(labelLimit=230, title=None)),
            tooltip=[alt.Tooltip("Rasgo:N"), alt.Tooltip("Diferencia:Q", format=".2f")],
        ).properties(height=280)
        st.altair_chart(chart, width="stretch",
                        alt="Diferencia estandarizada de cinco rasgos CPV frente a pérdida lejana")
    with derecha:
        st.markdown("**Tres lecturas en español simple**")
        for fila in top.head(3).itertuples(index=False):
            delta = getattr(fila, diferencia)
            direccion = "mayor" if delta > 0 else "menor"
            st.write(f"{fila.etiqueta}: proporción {direccion} en secciones de "
                     f"{'pérdida cercana' if objetivo == 'perdida_competitiva' else 'ventaja amplia'}.")
    st.dataframe(top.rename(columns={"etiqueta": "Rasgo", f"media_{objetivo}": "Clase elegida (%)",
                                     "media_perdida_lejana": "Pérdida lejana (%)",
                                     diferencia: "Diferencia estandarizada"}),
                 hide_index=True, width="stretch",
                 column_config={"Clase elegida (%)": st.column_config.NumberColumn(format="%.1f"),
                                "Pérdida lejana (%)": st.column_config.NumberColumn(format="%.1f"),
                                "Diferencia estandarizada": st.column_config.NumberColumn(format="%+.2f")},
                 alt="Promedios CPV y diferencia de las cinco variables principales")
    st.caption("El CPV describe residentes de la sección; no revela cómo votaron personas o grupos. "
               "Una casilla E recibe contexto de sección, no un perfil propio de su área de atención.")
    with st.expander("Avanzado · los 15 rasgos CPV", on_change="rerun") as avanzado:
        if avanzado.open:
            st.dataframe(tabla[columnas].rename(columns={
                "etiqueta": "Rasgo", f"media_{objetivo}": "Clase elegida (%)",
                "media_perdida_lejana": "Pérdida lejana (%)",
                diferencia: "Diferencia estandarizada",
            }), hide_index=True, width="stretch")
            st.caption("Es un contraste descriptivo por partido, no un modelo de ML. "
                       "El ensayo de ML con CPV se resume en la pregunta 03.")


def _historia(root: Path, partido: str) -> None:
    _cabecera_pregunta(
        3, "¿Con qué grado de confiabilidad?",
        "Aún no hay un grado de confianza prospectivo defendible para decir dónde ganarás. Sí medimos errores de un ensayo retrospectivo 2018→2021→2024.",
        "Cómo llegamos: comparamos persistencia 2021 y Ridge en las secciones de Querétaro "
        "con geometría comparable. El error se mide contra el resultado observado de 2024; "
        "no es un grado de confianza para 2027.")
    path = root / "data/electoral/ieeq_local/benchmark_partidos_2024.json"
    if not path.exists():
        st.info("No está el informe local de la prueba histórica; esta respuesta conserva sólo su límite metodológico.")
        return
    informe = json.loads(path.read_text(encoding="utf-8"))
    universo = informe["universo"]["comparable"]
    resultados = informe["resultados"]
    p = resultados["persistencia"]["por_partido"][partido]
    r = resultados["ridge"]["por_partido"][partido]
    a, b, c = st.columns(3)
    a.metric("Secciones comparables", f"{universo['secciones']:,}/{informe['universo']['total_secciones']:,}")
    b.metric("Lista nominal cubierta", f"{universo['cobertura_lista_nominal_pct']:.1f} %")
    c.metric("Error Ridge · cuota del partido", f"{r['mae_pct']:.1f} pp")
    st.markdown(f"**{partido}: error medio en puntos de cuota de voto**")
    filas_comparacion = [
        {"Método": "Persistencia 2021", "Error medio (pp)": p["mae_pct"]},
        {"Método": "Ridge sin CPV", "Error medio (pp)": r["mae_pct"]},
    ]
    ampliado_path = root / "data/electoral/ieeq_local/benchmark_ml_cpv_expandido_2024.json"
    ampliado = json.loads(ampliado_path.read_text(encoding="utf-8")) if ampliado_path.exists() else None
    if ampliado:
        for nombre, etiqueta in (("15_tasas", "Árbol · 15 tasas CPV"),
                                 ("27_tasas", "Árbol · 27 tasas CPV"),
                                 ("todos_campos", "Árbol · 247 campos CPV")):
            filas_comparacion.append({
                "Método": etiqueta,
                "Error medio (pp)": ampliado["modelos"][nombre]["por_partido"][partido]["mae_cuota_pp"],
            })
    comparacion = pd.DataFrame(filas_comparacion)
    st.bar_chart(comparacion, x="Método", y="Error medio (pp)", color="#48BBD3", height=220,
                 alt=f"Error retrospectivo por método para {partido}; menor es mejor")
    if ampliado:
        errores = ampliado["modelos"]
        st.caption("Nueva corrida: 15 tasas CPV, 27 tasas CPV y 247 campos (220 del ECEG "
                   "más 27 tasas), entrenados y evaluados sobre las mismas secciones. "
                   f"Error medio macro: {errores['15_tasas']['mae_cuota_macro_pp']:.2f}, "
                   f"{errores['27_tasas']['mae_cuota_macro_pp']:.2f} y "
                   f"{errores['todos_campos']['mae_cuota_macro_pp']:.2f} pp, respectivamente; "
                   "Ridge sin CPV: 5.37 pp. Menor error retrospectivo no es probabilidad "
                   "de victoria futura.")
    else:
        st.caption("Ridge usa resultados de elecciones previas; el CPV se analiza por separado. "
                   "Menor error retrospectivo no equivale a una probabilidad de victoria futura.")
    st.caption("NO VERIFICADO: que el patrón se repita en 2027, en otras entidades o en casillas "
               "de secciones reconfiguradas. Este bloque compara secciones, no produce una "
               "probabilidad de victoria por casilla.")
    with st.expander("Avanzado · cobertura y métodos", on_change="rerun") as avanzado:
        if avanzado.open:
            st.dataframe(comparacion, hide_index=True, width="stretch")
            st.write(f"Ridge: {r['lideres_detectados']} liderazgos detectados de "
                     f"{r['lideres_observados']} observados entre siete partidos atribuidos.")
            if ampliado:
                st.dataframe(pd.DataFrame([
                    {"Variables CPV": datos["n_variables_cpv"],
                     "Error macro cuota (pp)": datos["mae_cuota_macro_pp"],
                     "Error macro margen (pp)": datos["mae_margen_macro_pp"],
                     "Liderazgos detectados": datos["por_partido"][partido]["lideres_detectados"],
                     "Liderazgos observados": datos["por_partido"][partido]["lideres_observados"]}
                    for datos in ampliado["modelos"].values()]), hide_index=True, width="stretch")
            cpv_path = root / "data/electoral/ieeq_local/benchmark_ml_cpv_2024.json"
            if cpv_path.exists():
                modelos_cpv = json.loads(cpv_path.read_text(encoding="utf-8"))["modelos"]
                arbol = modelos_cpv["hist_gradient_boosting_cpv"]["mae_cuota_macro_pp"]
                ridge = modelos_cpv["ridge_sin_cpv"]["mae_cuota_macro_pp"]
                st.write(f"En el ensayo con las 15 tasas CPV, el árbol tuvo {arbol:.2f} pp "
                         f"de error medio macro frente a {ridge:.2f} pp de Ridge sin CPV. "
                         "Añadir CPV no mejoró esa medida retrospectiva.")
            st.caption("La comparación usa 788 secciones equivalentes; 165 secciones modificadas "
                       "no reciben esta evaluación individual.")


def _accion(base: pd.DataFrame, puntos: pd.DataFrame, partido: str) -> None:
    _cabecera_pregunta(
        4, "¿Dónde vale la pena revisar esfuerzo de campaña?",
        "La lista junta pérdida cercana, defensa de ventaja, abstención observada, apoyo mínimo y costo supuesto para decidir qué revisar en campo.",
        "Cómo llegamos: reglas transparentes sobre votos 2024; cada motivo se muestra por separado. "
        "No estimamos votos captables, retorno ni probabilidad de victoria.")
    with st.popover("Supuestos de costo", icon=":material/tune:"):
        costo_texto = st.text_input("Costo supuesto por voto adicional (MXN)", value="",
                                   key="dashboard_costo")
        presupuesto_texto = st.text_input("Presupuesto supuesto por casilla (MXN)", value="",
                                         key="dashboard_presupuesto")
        st.caption("Opcional. Sólo multiplica la distancia en votos por tu supuesto; no calcula costo real.")
    base = base.copy()
    base["COSTO_HIPOTETICO"] = float("nan")
    if costo_texto.strip():
        try:
            base = costo_hipotetico(base, float(costo_texto.replace(",", ".")))
        except ValueError:
            st.warning("El costo debe ser un número no negativo.")
    presupuesto = None
    if presupuesto_texto.strip():
        try:
            presupuesto = float(presupuesto_texto.replace(",", "."))
            if not pd.notna(presupuesto) or presupuesto < 0 or presupuesto == float("inf"):
                raise ValueError
        except ValueError:
            st.warning("El presupuesto debe ser un número no negativo.")
            presupuesto = None
    revision = lista_revision(base, presupuesto)
    motivos = revision.TIPO_REVISION.drop_duplicates().tolist()
    col_motivo, col_clave = st.columns([1, 1])
    with col_motivo:
        motivo = st.selectbox("Motivo", ["Todos", *motivos], key="dashboard_motivo")
    with col_clave:
        buscar = st.text_input("Buscar sección o casilla", placeholder="Ej. 22-0782 o E1",
                               key="dashboard_buscar")
    vista = revision if motivo == "Todos" else revision.loc[revision.TIPO_REVISION.eq(motivo)]
    if buscar.strip():
        termino = buscar.strip().upper()
        vista = vista.loc[vista.ID_SECCION.str.contains(termino, regex=False)
                         | vista.CASILLA_ETIQUETA.str.upper().str.contains(termino, regex=False)]
    vista = vista.reset_index(drop=True)
    puntos_clave = set(zip(puntos.ID_SECCION, puntos.CASILLA_ETIQUETA))
    vista["SEDE_EN_MAPA"] = [
        (s, c) in puntos_clave for s, c in zip(vista.ID_SECCION, vista.CASILLA_ETIQUETA)]
    a, b, c = st.columns(3)
    a.metric("Casillas para revisar", f"{len(vista):,}")
    b.metric("Pérdidas cercanas", f"{int(vista.CLASE.eq('perdida_competitiva').sum()):,}")
    c.metric("Con sede en mapa", f"{int(vista.SEDE_EN_MAPA.sum()):,}")
    if vista.empty:
        st.info("No hay casillas para este filtro. Cambia el motivo o la búsqueda.")
        return
    tabla = vista[["ID_SECCION", "CASILLA_ETIQUETA", "TIPO_REVISION", "VOTOS_PARA_LIDERAR",
                   "ABSTENCION", "APOYO_MINIMO_FEDERAL_2024_PCT", "COSTO_HIPOTETICO",
                   "SEDE_EN_MAPA"]].rename(columns={
        "ID_SECCION": "Sección", "CASILLA_ETIQUETA": "Casilla", "TIPO_REVISION": "Motivo",
        "VOTOS_PARA_LIDERAR": "Votos para liderar", "ABSTENCION": "Abstención",
        "APOYO_MINIMO_FEDERAL_2024_PCT": "Apoyo mínimo 2024 (%)",
        "COSTO_HIPOTETICO": "Costo supuesto (MXN)", "SEDE_EN_MAPA": "Sede en mapa",
    })
    seleccion = st.session_state.get("dashboard_accion_seleccionada")
    if seleccion and not ((vista.ID_SECCION.eq(seleccion[0])
                           & vista.CASILLA_ETIQUETA.eq(seleccion[1])).any()):
        seleccion = None
        st.session_state["dashboard_accion_seleccionada"] = None
    geometrias = _geometrias_seccion(
        Path(__file__).resolve().parents[1] / "data/electoral/secciones_2024_geom.parquet")
    sedes = preparar_sedes(vista, puntos)
    izquierda, derecha = st.columns([1.15, 1], gap="medium")
    with izquierda:
        st.markdown("**Mapa de casillas para revisar**")
        _mostrar_leyenda_mapa()
        capas = []
        secciones_mapa = _capa_secciones(vista, geometrias)
        if secciones_mapa["features"]:
            capas.append(pdk.Layer(
                "GeoJsonLayer", id="secciones_esfuerzo", data=secciones_mapa,
                pickable=True, filled=True, stroked=True,
                get_fill_color="properties.COLOR", get_line_color=[80, 194, 226, 145],
                line_width_min_pixels=1))
        if not sedes.empty:
            capas.append(pdk.Layer(
                "ScatterplotLayer", id="sedes_esfuerzo", data=sedes.to_dict("records"),
                get_position="[LONGITUD, LATITUD]", get_radius=45,
                radius_min_pixels=3, radius_max_pixels=8, get_fill_color="COLOR",
                get_line_color=[22, 20, 30, 255], line_width_min_pixels=1,
                stroked=True, pickable=True))
        punto = None
        if seleccion:
            coincide = puntos.loc[puntos.ID_SECCION.eq(seleccion[0])
                                  & puntos.CASILLA_ETIQUETA.eq(seleccion[1])]
            if not coincide.empty:
                punto = coincide.iloc[0]
                capas.append(pdk.Layer(
                    "ScatterplotLayer", id="seleccion_esfuerzo", pickable=False,
                    data=[{"LONGITUD": float(punto.LONGITUD),
                           "LATITUD": float(punto.LATITUD)}],
                    get_position="[LONGITUD, LATITUD]", get_radius=110,
                    radius_min_pixels=12, radius_max_pixels=20,
                    get_fill_color=[255, 255, 255, 45],
                    get_line_color=[255, 255, 255, 255],
                    line_width_min_pixels=3, stroked=True))
        lat, lon, zoom = 20.64, -100.31, 9.2
        if punto is not None:
            lat, lon, zoom = float(punto.LATITUD), float(punto.LONGITUD), 13.5
        elif seleccion and seleccion[0] in geometrias:
            centro = shape(geometrias[seleccion[0]]).centroid
            lat, lon, zoom = centro.y, centro.x, 12.5
        if capas:
            evento_mapa = st.pydeck_chart(
                pdk.Deck(layers=capas, map_style=pdk.map_styles.CARTO_DARK,
                         initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom),
                         tooltip={"text": "Sección {ID_SECCION}\nCasillas {CASILLAS}\n{SENAL}"}),
                height=440, on_select="rerun", selection_mode="single-object",
                key=f"dashboard_mapa_esfuerzo_{partido}_{motivo}_{buscar.strip().upper()}_{seleccion}",
                alt="Sedes y secciones de las casillas para revisar")
            objetos = evento_mapa.selection.objects.get("sedes_esfuerzo", [])
            if objetos:
                elegido = (str(objetos[0]["ID_SECCION"]), str(objetos[0]["CASILLA_INICIAL"]))
                if elegido != seleccion:
                    st.session_state["dashboard_accion_seleccionada"] = elegido
                    st.rerun()
            secciones_elegidas = evento_mapa.selection.objects.get("secciones_esfuerzo", [])
            if secciones_elegidas:
                objeto = secciones_elegidas[0]
                clave = str(objeto.get("properties", {}).get("ID_SECCION")
                            or objeto.get("ID_SECCION", ""))
                filas = vista.loc[vista.ID_SECCION.eq(clave)]
                if not filas.empty:
                    elegido = (str(filas.iloc[0].ID_SECCION), str(filas.iloc[0].CASILLA_ETIQUETA))
                    if elegido != seleccion:
                        st.session_state["dashboard_accion_seleccionada"] = elegido
                        st.rerun()
        else:
            st.info("No hay geometrías ni sedes para estas casillas.")
    with derecha:
        st.markdown("**Casillas del filtro**")
        st.caption("Selecciona una fila o un punto para ubicar la casilla y abrir su ficha.")
        evento = st.dataframe(
            tabla, hide_index=True, width="stretch", height=440,
            on_select="rerun", selection_mode="single-row",
            key=f"dashboard_tabla_accion_{partido}_{motivo}_{buscar.strip().upper()}",
            column_config={"Sección": st.column_config.TextColumn(pinned=True),
                           "Casilla": st.column_config.TextColumn(pinned=True),
                           "Apoyo mínimo 2024 (%)": st.column_config.NumberColumn(format="%.1f"),
                           "Costo supuesto (MXN)": st.column_config.NumberColumn(format="%.0f")},
            alt="Casillas con motivo de revisión, distancia en votos, abstención y sede")
    st.download_button("Descargar selección CSV", tabla.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"revision_casillas_{partido}_2024.csv", mime="text/csv")
    indices = evento.selection.rows
    if indices and 0 <= indices[0] < len(vista):
        fila = vista.iloc[indices[0]]
        elegido = (str(fila.ID_SECCION), str(fila.CASILLA_ETIQUETA))
        if elegido != st.session_state.get("dashboard_accion_ultimo_click_tabla"):
            st.session_state["dashboard_accion_ultimo_click_tabla"] = elegido
            st.session_state["dashboard_accion_seleccionada"] = elegido
            st.rerun()
    if seleccion:
        fila = vista.loc[vista.ID_SECCION.eq(seleccion[0])
                         & vista.CASILLA_ETIQUETA.eq(seleccion[1])].iloc[0]
        _mostrar_ficha_casilla(fila, base)
    st.caption("«Faltante ≤ abstención» es una comparación aritmética, no votos disponibles. "
               "El apoyo mínimo compara tres boletas federales de 2024 y no mide fidelidad individual.")


def mostrar_dashboard_casillas(estado: int, root: Path) -> None:
    titulo, filtro = st.columns([1.7, 1], vertical_alignment="bottom")
    with titulo:
        st.subheader("Decisiones de campaña · Querétaro 2024")
        st.caption("Dónde ganar · por qué · confianza · dónde enfocar esfuerzo")
    if estado != 22:
        st.info("Selecciona Querétaro en el filtro de muestra para explorar este piloto.")
        return
    carpeta = root / "data/electoral/ieeq_local"
    preparado = carpeta / "diagnostico_casillas_cpv_2024.parquet"
    fuentes = (carpeta / "dip_local_mr_2024_casilla.parquet",
               carpeta / "crosswalk_qro_2018_2021_2024_referencias.parquet",
               root / "data/electoral/cpv_2020_seccion.parquet")
    if not preparado.exists() and not all(path.exists() for path in fuentes):
        st.info("Faltan datos locales IEEQ, CPV o cruce cartográfico para abrir el dashboard.")
        return
    with filtro:
        partido = st.selectbox("Partido a explorar", PARTIDOS_COMUNES,
                               index=PARTIDOS_COMUNES.index("MORENA"), key="dashboard_partido")
    base = proponer_esfuerzo(evaluar_partido(_cargar(root), partido))
    apoyo_path = root / "data/electoral/fidelidad_estado.parquet"
    if apoyo_path.exists():
        apoyo = _cargar_apoyo(apoyo_path)
        base = incorporar_apoyo_minimo(base, apoyo.loc[apoyo.ID_ESTADO.eq(22)], partido)
    else:
        base["APOYO_MINIMO_FEDERAL_2024_PCT"] = float("nan")
    perfiles = (carpeta / "perfilamiento_cpv_2024_seccion.parquet",
                carpeta / "perfilamiento_cpv_2024.json")
    if all(path.exists() for path in perfiles):
        base = base.merge(_cargar_perfiles(carpeta), on="ID_SECCION", how="left",
                          validate="many_to_one")
        base.loc[~base.CPV_COMPARABLE, ["PERFIL_CPV", "RASGOS_CPV_SECCION"]] = pd.NA
    else:
        base["PERFIL_CPV"] = pd.NA
        base["RASGOS_CPV_SECCION"] = pd.NA
    puntos = _cargar_puntos(carpeta / "casillas_2024_puntos.parquet")
    preguntas = ("1 · Dónde ganar", "2 · Por qué", "3 · Confianza", "4 · Esfuerzo")
    st.session_state.setdefault("dashboard_pregunta", preguntas[0])
    pregunta = st.segmented_control("Pregunta", preguntas, key="dashboard_pregunta",
                                    width="stretch")
    if pregunta == preguntas[0]:
        _patron(base, puntos)
    elif pregunta == preguntas[1]:
        _perfil(base, partido)
    elif pregunta == preguntas[2]:
        _historia(root, partido)
    else:
        _accion(base, puntos, partido)
    with st.expander("Fuentes y límites del diagnóstico", on_change="rerun") as limites:
        if limites.open:
            st.write("Votos: IEEQ 2024 por casilla. CPV: ECEG INEGI–INE 2020 por sección. "
                     "Sedes: copia cartográfica de Ubica tu Casilla 2024, cotejo de encarte y revisión visual.")
            st.write("El reparto de marcas de coalición en fracciones iguales es una atribución analítica. "
                     "Las casillas especiales y el voto anticipado se analizan aparte. "
                     "Las extraordinarias reciben contexto CPV seccional, no perfil de su área de atención.")
            st.caption("CPV 2020 vs votos 2024 · asociación, no causa. "
                       "Acciones, costos y resultados futuros aún no están verificados causalmente.")
