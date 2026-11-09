"""Dashboard narrativo del piloto local: cuatro preguntas y sus evidencias."""

from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

from electoral.diagnostico_casillas import (
    costo_hipotetico, evaluar_partido, incorporar_apoyo_minimo, lista_revision,
    perfil_cpv, proponer_esfuerzo,
)
from electoral.diagnostico_casillas_tab import (
    _cargar, _cargar_apoyo, _cargar_perfiles, _mostrar_ficha_casilla,
)
from electoral.reparto_ieeq import PARTIDOS_COMUNES


COLOR_CERCANA = [248, 170, 74, 220]
COLOR_DEFENSA = [72, 187, 211, 220]
COLOR_FORTALEZA = [102, 192, 138, 210]
COLOR_BASE = [158, 155, 170, 180]
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
        elif "ganada_ajustada" in clases or "empate" in clases:
            senal, color = "Ventaja estrecha o empate", COLOR_DEFENSA
        elif "ganada_solida" in clases:
            senal, color = "Ventaja amplia observada", COLOR_FORTALEZA
        else:
            senal, color = "Otro resultado", COLOR_BASE
        casillas_sitio = sorted(grupo.CASILLA_ETIQUETA)
        filas.append({"ID_SECCION": seccion, "LATITUD": float(lat), "LONGITUD": float(lon),
                      "CASILLAS": ", ".join(casillas_sitio), "CASILLA_INICIAL": casillas_sitio[0],
                      "NUM_CASILLAS": len(casillas_sitio), "SENAL": senal, "COLOR": color})
    return pd.DataFrame(filas)


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
    c.metric("Sedes en mapa", f"{len(sedes):,}")
    izquierda, derecha = st.columns([1.35, 1], gap="medium")
    elegido_mapa = None
    with izquierda:
        st.markdown("**Mapa de sedes 2024**")
        st.caption("Naranja: pérdida cercana · azul: ventaja estrecha o empate · verde: ventaja amplia. "
                   "Una marca reúne las casillas del mismo sitio; el color no es probabilidad de victoria.")
        if sedes.empty:
            st.info("No hay puntos de sede para este filtro; consulta la lista de casillas.")
        else:
            capa = pdk.Layer(
                "ScatterplotLayer", id="sedes", data=sedes.to_dict("records"),
                get_position="[LONGITUD, LATITUD]", get_radius=65,
                radius_min_pixels=5, radius_max_pixels=13,
                get_fill_color="COLOR", get_line_color=[22, 20, 30, 255],
                line_width_min_pixels=1, stroked=True, pickable=True)
            capas = [capa]
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
            evento_mapa = st.pydeck_chart(
                pdk.Deck(layers=capas, map_style=None,
                         initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom),
                         tooltip={"text": "Sección {ID_SECCION}\nCasillas {CASILLAS}\n{SENAL}"}),
                height=420, on_select="rerun", selection_mode="single-object",
                key=f"dashboard_mapa_{modo}_{seleccion}",
                alt="Sedes de casillas 2024 coloreadas por resultado cercano o ventaja estrecha")
            objetos = evento_mapa.selection.objects.get("sedes", [])
            if objetos:
                elegido_mapa = (str(objetos[0]["ID_SECCION"]), str(objetos[0]["CASILLA_INICIAL"]))
            if elegido_mapa and elegido_mapa != st.session_state.get("dashboard_ultimo_click_mapa"):
                st.session_state["dashboard_ultimo_click_mapa"] = elegido_mapa
                st.session_state["dashboard_casilla_seleccionada"] = elegido_mapa
                st.rerun()
    with derecha:
        st.markdown("**Casillas del filtro**")
        tabla = vista[["ID_SECCION", "CASILLA_ETIQUETA", "CLASE", "MARGEN_PP",
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
            key=f"dashboard_tabla_patron_{modo}",
            column_config={"Sección": st.column_config.TextColumn(pinned=True),
                           "Margen (pp)": st.column_config.NumberColumn(format="%+.1f")},
            alt="Casillas filtradas; selecciona una para ver su sede y resultado")
        st.caption("Selecciona una fila o un punto para abrir la ficha de casilla.")
    indices = evento_tabla.selection.rows
    if indices and 0 <= indices[0] < len(vista):
        fila = vista.reset_index(drop=True).iloc[indices[0]]
        clave = (str(fila.ID_SECCION), str(fila.CASILLA_ETIQUETA))
        if clave != st.session_state.get("dashboard_ultimo_click_tabla"):
            st.session_state["dashboard_ultimo_click_tabla"] = clave
            st.session_state["dashboard_casilla_seleccionada"] = clave
            st.rerun()
    if seleccion:
        fila = vista.loc[vista.ID_SECCION.eq(seleccion[0])
                         & vista.CASILLA_ETIQUETA.eq(seleccion[1])]
        if len(fila) == 1:
            _mostrar_ficha_casilla(fila.iloc[0], base)


def _perfil(base: pd.DataFrame) -> None:
    _cabecera_pregunta(
        2, "¿Por qué aparece ese resultado?",
        "Comparamos rasgos censales de las secciones de cada clase. Estos contrastes sugieren dónde investigar; no explican la causa del voto individual.",
        "Cómo llegamos: 15 tasas del CPV 2020 en ECEG INEGI–INE, enlazadas por sección "
        "y limitadas a geometrías comparables. Cada sección cuenta una vez por clase. "
        "CPV 2020 vs votos 2024 · asociación, no causa.")
    perfil = perfil_cpv(base, max_frases=3)
    tabla = perfil["tabla"]
    objetivo = st.selectbox("Comparar con pérdida lejana", ["perdida_competitiva", "ganada_solida"],
                            format_func=lambda x: "Pérdida cercana" if x == "perdida_competitiva" else "Victoria sólida",
                            key="dashboard_clase_perfil")
    diferencia = f"dif_est_{objetivo}_vs_perdida_lejana"
    columnas = ["etiqueta", f"media_{objetivo}", "media_perdida_lejana", diferencia]
    top = tabla[columnas].dropna(subset=[diferencia]).copy()
    top = top.reindex(top[diferencia].abs().sort_values(ascending=False).index).head(5)
    if top.empty:
        st.info("No hay suficientes secciones comparables para este contraste.")
        return
    st.caption(f"Secciones con dato: {perfil['n_secciones_por_clase'].get(objetivo, 0)} en la clase elegida "
               f"y {perfil['n_secciones_por_clase'].get('perdida_lejana', 0)} en pérdida lejana.")
    izquierda, derecha = st.columns([1, 1], gap="medium")
    with izquierda:
        st.markdown("**Las cinco mayores diferencias estandarizadas**")
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
                     f"{'pérdida cercana' if objetivo == 'perdida_competitiva' else 'victoria sólida'}.")
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
    comparacion = pd.DataFrame({"Método": ["Persistencia 2021", "Ridge"],
                                "Error medio (pp)": [p["mae_pct"], r["mae_pct"]]})
    st.bar_chart(comparacion, x="Método", y="Error medio (pp)", color="#48BBD3", height=220,
                 alt=f"Error retrospectivo de persistencia y Ridge para {partido}; menor es mejor")
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
    st.caption("Selecciona una fila para ver el motivo, la sede 2024, el polígono y las demás casillas de su sección.")
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
        _mostrar_ficha_casilla(vista.iloc[indices[0]], base)
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
    tabs = st.tabs(["1 · Dónde ganar", "2 · Por qué", "3 · Confianza", "4 · Esfuerzo"],
                   default="1 · Dónde ganar", key="dashboard_preguntas", on_change="rerun")
    with tabs[0]:
        if tabs[0].open:
            _patron(base, puntos)
    with tabs[1]:
        if tabs[1].open:
            _perfil(base)
    with tabs[2]:
        if tabs[2].open:
            _historia(root, partido)
    with tabs[3]:
        if tabs[3].open:
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
