"""Vista de patrones CPV y esfuerzo exploratorio por casilla local."""

import json
import math
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pydeck as pdk
import streamlit as st

from electoral.config import GEOMETRIA_PARQUET
from electoral.diagnostico_casillas import (
    cobertura, costo_hipotetico, evaluar_partido, incorporar_apoyo_minimo,
    lista_revision, perfil_cpv, preparar_casillas, proponer_esfuerzo,
)
from electoral.reparto_ieeq import PARTIDOS_COMUNES


@st.cache_data(max_entries=2)
def _cargar(root: Path) -> pd.DataFrame:
    carpeta = root / "data/electoral/ieeq_local"
    preparado = carpeta / "diagnostico_casillas_cpv_2024.parquet"
    if preparado.exists():
        return pd.read_parquet(preparado)
    encarte = carpeta / "encarte_qro_2024_claves.parquet"
    return preparar_casillas(
        pd.read_parquet(carpeta / "dip_local_mr_2024_casilla.parquet"),
        pd.read_parquet(carpeta / "crosswalk_qro_2018_2021_2024_referencias.parquet"),
        pd.read_parquet(root / "data/electoral/cpv_2020_seccion.parquet"),
        pd.read_parquet(encarte) if encarte.exists() else None,
    )


@st.cache_data(max_entries=2)
def _cargar_apoyo(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path, columns=["ID_SECCION", "partido", "piso_pct", "ID_ESTADO"])


@st.cache_data(max_entries=2)
def _cargar_perfiles(carpeta: Path) -> pd.DataFrame:
    asignacion = pd.read_parquet(carpeta / "perfilamiento_cpv_2024_seccion.parquet",
                                 columns=["ID_SECCION", "PERFIL_CPV"])
    if asignacion.ID_SECCION.duplicated().any():
        raise ValueError("Perfil CPV duplicado por sección")
    informe = json.loads((carpeta / "perfilamiento_cpv_2024.json").read_text(encoding="utf-8"))
    rasgos = {int(clave): "; ".join(
        f"{r['etiqueta']}: {r['direccion']}" for r in valor["rasgos"][:3])
        for clave, valor in informe["perfiles"].items()}
    asignacion["RASGOS_CPV_SECCION"] = asignacion.PERFIL_CPV.map(rasgos)
    return asignacion


@st.cache_data(max_entries=64)
def _cargar_geometria_seccion(path: Path, id_seccion: str) -> tuple[dict, tuple[float, float, float, float]] | None:
    """Lee sólo el polígono 2024 solicitado; nunca infiere la sede de casilla."""
    if not path.exists():
        return None
    geom = gpd.read_parquet(path, columns=["ID_SECCION", "geometry"],
                            filters=[("ID_SECCION", "==", id_seccion)])
    if len(geom) != 1 or geom.geometry.isna().any() or geom.geometry.is_empty.any():
        return None
    if geom.crs is None or geom.crs.to_epsg() != 4326:
        geom = geom.to_crs(4326)
    return json.loads(geom.to_json(drop_id=True)), tuple(float(x) for x in geom.total_bounds)


@st.cache_data(max_entries=64)
def _cargar_punto_casilla(path: Path, id_seccion: str, casilla: str) -> dict | None:
    if not path.exists():
        return None
    puntos = pd.read_parquet(path, filters=[("ID_SECCION", "==", id_seccion),
                                             ("CASILLA_ETIQUETA", "==", casilla)])
    aceptados = puntos.loc[puntos.CALIDAD.isin(("clave_domicilio_y_poligono",
                                              "domicilio_y_revision_manual",
                                              "sede_revisada_visual_usuario"))]
    if len(aceptados) != 1:
        return None
    return aceptados.iloc[0][["LONGITUD", "LATITUD", "SEDE", "DOMICILIO_FUENTE",
                             "CALIDAD", "URL_REVISION", "NOTA_REVISION"]].to_dict()


def _mostrar_ficha_casilla(fila: pd.Series, base: pd.DataFrame,
                           puntos_path: Path | None = None) -> None:
    seccion, casilla = str(fila.ID_SECCION), str(fila.CASILLA_ETIQUETA)
    with st.container(border=True):
        st.subheader(f"Sección {seccion} · casilla {casilla}")
        if fila.get("TIPO_REVISION"):
            st.markdown(f"**{fila.TIPO_REVISION}.** {fila.MOTIVO_REVISION}")
        elif fila.get("ACCION_HIPOTESIS"):
            st.markdown(f"**Esfuerzo a explorar:** {fila.ACCION_HIPOTESIS}.")
        m1, m2, m3 = st.columns(3)
        m1.metric("Votos del partido atribuidos", f"{fila.VOTOS_PARTIDO:,.1f}")
        m2.metric("Votos del rival", f"{fila.VOTOS_RIVAL:,.1f}")
        m3.metric("Margen partidario", f"{fila.MARGEN_PP:+.1f} pp" if pd.notna(fila.MARGEN_PP) else "Sin dato")
        if pd.notna(fila.get("PERFIL_CPV")):
            st.caption(f"Perfil CPV de la sección {int(fila.PERFIL_CPV)}: {fila.RASGOS_CPV_SECCION}. "
                       "CPV 2020 vs votos 2024; asociación, no causa.")
        else:
            st.caption("Esta sección no tiene perfil CPV comparable.")
        if puntos_path is None:
            puntos_path = (Path(__file__).resolve().parents[1]
                           / "data/electoral/ieeq_local/casillas_2024_puntos.parquet")
        punto = _cargar_punto_casilla(puntos_path, seccion, casilla)
        if punto:
            if punto["CALIDAD"] == "domicilio_y_revision_manual":
                st.caption("Sede de instalación cotejada por clave y domicilio del encarte IEEQ; "
                           "la posición fue revisada visualmente en Google Maps por el usuario. "
                           "El punto está fuera del polígono de la sección. "
                           "No representa el domicilio de los votantes ni una verificación en campo.")
                if punto["URL_REVISION"]:
                    st.link_button("Abrir revisión en Google Maps", punto["URL_REVISION"])
            elif punto["CALIDAD"] == "sede_revisada_visual_usuario":
                st.caption("Sede de instalación 2024 revisada visualmente por el usuario en mapas. "
                           "Se conserva el punto publicado; la ubicación no se comprobó en campo "
                           "y no representa el domicilio de los votantes.")
                if punto["NOTA_REVISION"]:
                    st.info("Referencia histórica: " + punto["NOTA_REVISION"])
            else:
                st.caption("El punto señala la sede de instalación de esta casilla en Ubica tu Casilla 2024 "
                           "(copia publicada por Morlan), cotejada con clave, domicilio del encarte IEEQ "
                           "y polígono seccional. No representa el domicilio de los votantes. "
                           "La precisión física del punto no está verificada en campo.")
            st.markdown(f"**Sede:** {punto['SEDE']}  ")
            st.caption(f"Domicilio de la fuente cartográfica: {punto['DOMICILIO_FUENTE']}")
            st.link_button("Abrir punto en Google Maps",
                           "https://www.google.com/maps/search/?api=1&query="
                           f"{punto['LATITUD']},{punto['LONGITUD']}")
        else:
            st.caption("El mapa delimita la sección electoral de 2024. Esta casilla no tiene un punto "
                       "que haya pasado el cotejo de clave, domicilio y polígono.")
        if pd.notna(fila.LOCALIDAD_INSTALACION):
            st.caption(f"Localidad de instalación registrada en el encarte: {fila.LOCALIDAD_INSTALACION}.")
        datos_mapa = _cargar_geometria_seccion(GEOMETRIA_PARQUET, seccion)
        if datos_mapa is None:
            st.info("No hay polígono 2024 disponible para esta sección; se conservan los datos de casilla.")
        else:
            geojson, (minx, miny, maxx, maxy) = datos_mapa
            lat = (miny + maxy) / 2
            ancho = max(maxx - minx, 0.0005)
            alto = max((maxy - miny) / max(math.cos(math.radians(lat)), 0.1), 0.0005)
            zoom = min(math.log2(360 * 360 / (512 * ancho * 1.35)),
                       math.log2(360 * 380 / (512 * alto * 1.35)))
            capa = pdk.Layer("GeoJsonLayer", data=geojson, filled=True, stroked=True,
                             get_fill_color=[180, 79, 255, 90],
                             get_line_color=[245, 238, 255, 255], line_width_min_pixels=3,
                             pickable=True)
            capas = [capa]
            if punto:
                capas.append(pdk.Layer(
                    "ScatterplotLayer", data=[{"LONGITUD": punto["LONGITUD"],
                                               "LATITUD": punto["LATITUD"]}],
                    get_position="[LONGITUD, LATITUD]", get_radius=70,
                    radius_min_pixels=9, radius_max_pixels=18,
                    get_fill_color=[255, 166, 39, 255],
                    get_line_color=[20, 20, 30, 255], line_width_min_pixels=2,
                    stroked=True, pickable=True))
            st.pydeck_chart(pdk.Deck(
                layers=capas, map_style=None,
                initial_view_state=pdk.ViewState(latitude=lat, longitude=(minx + maxx) / 2,
                                                 zoom=max(7, min(16, zoom))),
                tooltip={"text": f"Sección {seccion} · casilla {casilla}"}), height=390,
                alt=(f"Polígono de la sección {seccion} y sede puntual de la casilla {casilla}"
                     if punto else f"Polígono de la sección electoral {seccion}, sin punto cotejado"))
        st.markdown("**Casillas B/C/E de esta sección**")
        hermanas = base.loc[base.ID_SECCION.eq(seccion), ["CASILLA_ETIQUETA", "LOCALIDAD_INSTALACION",
                            "VOTOS_PARTIDO", "VOTOS_RIVAL", "MARGEN_PP", "CLASE"]].copy()
        hermanas.insert(0, "Seleccionada", hermanas.CASILLA_ETIQUETA.eq(casilla))
        hermanas = hermanas.rename(columns={
            "CASILLA_ETIQUETA": "Casilla", "LOCALIDAD_INSTALACION": "Localidad de instalación",
            "VOTOS_PARTIDO": "Votos partido", "VOTOS_RIVAL": "Votos rival",
            "MARGEN_PP": "Margen (pp)", "CLASE": "Clase",
        }).sort_values("Casilla")
        st.dataframe(hermanas, hide_index=True, width="stretch",
                     alt=f"Casillas B/C/E con resultados partidarios en la sección {seccion}")


def mostrar_diagnostico_casillas(estado: int, root: Path) -> None:
    st.subheader("¿Dónde vale la pena actuar? · diagnóstico por casilla")
    st.caption("Diputaciones locales MR 2024 · CPV 2020 vs votos 2024 · asociación, no causa. "
               "Querétaro es filtro de muestra; las filas son casillas B/C/E, no promedios estatales.")
    if estado != 22:
        st.info("Selecciona Querétaro en el filtro de muestra para abrir este piloto.")
        return
    carpeta = root / "data/electoral/ieeq_local"
    preparado = carpeta / "diagnostico_casillas_cpv_2024.parquet"
    fuentes = (carpeta / "dip_local_mr_2024_casilla.parquet",
               carpeta / "crosswalk_qro_2018_2021_2024_referencias.parquet",
               root / "data/electoral/cpv_2020_seccion.parquet")
    if not preparado.exists() and not all(p.exists() for p in fuentes):
        st.info("Faltan archivos locales IEEQ, cruce cartográfico o CPV; el diagnóstico se oculta.")
        return
    partido = st.selectbox("Partido", PARTIDOS_COMUNES, index=PARTIDOS_COMUNES.index("MORENA"),
                           key="casillas_partido")
    base = proponer_esfuerzo(evaluar_partido(_cargar(root), partido))
    apoyo_path = root / "data/electoral/fidelidad_estado.parquet"
    if apoyo_path.exists():
        apoyo = _cargar_apoyo(apoyo_path)
        base = incorporar_apoyo_minimo(base, apoyo.loc[apoyo.ID_ESTADO.eq(22)], partido)
    else:
        base["APOYO_MINIMO_FEDERAL_2024_PCT"] = float("nan")
    cub = cobertura(base)
    a, b, c = st.columns(3)
    a.metric("Casillas con CPV comparable", f"{cub['casillas_cpv']:,}/{cub['casillas']:,}")
    b.metric("Secciones con CPV comparable", f"{cub['secciones_cpv']:,}/{cub['secciones']:,}")
    c.metric("Lista nominal cubierta", f"{cub['lista_nominal_pct']:.1f} %")
    st.caption("Las casillas especiales S y el voto anticipado A quedan fuera: su sección de instalación "
               "no identifica la residencia del votante. Una extraordinaria E recibe CPV de la sección, "
               "sin perfil propio de su área de atención verificado. La etiqueta E1C1, E1C2… "
               "se recupera del JSON del propio IEEQ; el encarte aporta la localidad de instalación. "
               "Reparto de marcas de coalición en "
               "fracciones iguales: atribución analítica, no cómputo oficial por partido.")

    st.markdown("#### Esfuerzo a explorar")
    st.caption("La propuesta usa votos observados, abstención y distancia al liderazgo entre partidos. "
               "El apoyo mínimo es el menor porcentaje del partido en tres boletas federales de 2024 "
               "de la misma sección; no mide fidelidad de personas. Es una hipótesis de campaña; "
               "ni la abstención ni el costo supuesto equivalen a votos captables.")
    costo_texto = st.text_input("Costo supuesto por voto adicional (opcional, MXN)", value="",
                               key="casillas_costo")
    if costo_texto.strip():
        try:
            base = costo_hipotetico(base, float(costo_texto.replace(",", ".")))
        except ValueError:
            st.warning("Ingresa un costo numérico mayor o igual a cero.")
            base["COSTO_HIPOTETICO"] = float("nan")
    else:
        base["COSTO_HIPOTETICO"] = float("nan")
    archivos_perfiles = (carpeta / "perfilamiento_cpv_2024_seccion.parquet",
                        carpeta / "perfilamiento_cpv_2024.json")
    if all(p.exists() for p in archivos_perfiles):
        base = base.merge(_cargar_perfiles(carpeta), on="ID_SECCION", how="left",
                          validate="many_to_one")
        base.loc[~base.CPV_COMPARABLE, ["PERFIL_CPV", "RASGOS_CPV_SECCION"]] = pd.NA
    else:
        base["PERFIL_CPV"] = pd.NA
        base["RASGOS_CPV_SECCION"] = pd.NA
    presupuesto_texto = st.text_input("Presupuesto supuesto por casilla (opcional, MXN)", value="",
                                     key="casillas_presupuesto")
    presupuesto = None
    if presupuesto_texto.strip():
        try:
            presupuesto = float(presupuesto_texto.replace(",", "."))
            if not pd.notna(presupuesto) or presupuesto < 0 or presupuesto == float("inf"):
                raise ValueError
        except ValueError:
            st.warning("Ingresa un presupuesto numérico mayor o igual a cero.")
            presupuesto = None
    revision = lista_revision(base, presupuesto)
    st.markdown("#### Casillas para revisar")
    st.caption("Selección por reglas observables: pérdida partidaria ≤10 pp, empate, ventaja partidaria <10 pp "
               "o dato electoral a revisar. Se agrupa por motivo y luego por clave, sin ranking de "
               "probabilidad de victoria. «Faltante ≤ abstención» es una comparación aritmética, "
               "no votos disponibles para el partido. El presupuesto sólo compara un costo supuesto.")
    if not all(p.exists() for p in archivos_perfiles):
        st.caption("No está el archivo local de perfiles CPV; se muestran los resultados electorales sin perfil de sección.")
    tipos = revision.TIPO_REVISION.drop_duplicates().tolist()
    elegidos = st.multiselect("Motivos de revisión", tipos, default=tipos,
                              key="casillas_tipos_revision")
    seleccion = revision.loc[revision.TIPO_REVISION.isin(elegidos)]
    cols_revision = ["ID_SECCION", "CASILLA_ETIQUETA", "TIPO_REVISION", "MOTIVO_REVISION",
                     "VOTOS_PARTIDO", "VOTOS_RIVAL", "VOTOS_PARA_LIDERAR", "ABSTENCION",
                     "ALCANZABLE_ABSTENCION", "APOYO_MINIMO_FEDERAL_2024_PCT", "COSTO_HIPOTETICO",
                     "DENTRO_PRESUPUESTO_SUPUESTO", "CPV_COMPARABLE", "PERFIL_CPV", "RASGOS_CPV_SECCION"]
    corta = seleccion[cols_revision].rename(columns={
        "ID_SECCION": "Sección", "CASILLA_ETIQUETA": "Casilla", "TIPO_REVISION": "Motivo",
        "MOTIVO_REVISION": "Por qué revisar", "VOTOS_PARTIDO": "Votos partido",
        "VOTOS_RIVAL": "Votos rival", "VOTOS_PARA_LIDERAR": "Votos para liderar",
        "ABSTENCION": "Abstención", "ALCANZABLE_ABSTENCION": "Faltante ≤ abstención",
        "APOYO_MINIMO_FEDERAL_2024_PCT": "Apoyo mínimo federal 2024 (%)",
        "COSTO_HIPOTETICO": "Costo supuesto (MXN)",
        "DENTRO_PRESUPUESTO_SUPUESTO": "Dentro del presupuesto supuesto",
        "CPV_COMPARABLE": "CPV comparable", "PERFIL_CPV": "Perfil CPV de sección",
        "RASGOS_CPV_SECCION": "Rasgos CPV de sección",
    })
    todas = base.sort_values(["ID_SECCION", "CASILLA_ETIQUETA"]).reset_index(drop=True)
    vista = todas[["ID_SECCION", "CASILLA_ETIQUETA", "LOCALIDAD_INSTALACION", "FILA_FUENTE", "CLASE", "VOTOS_PARTIDO",
                  "RIVAL", "VOTOS_RIVAL", "MARGEN_PP", "VOTOS_PARA_LIDERAR", "ABSTENCION",
                  "ALCANZABLE_ABSTENCION", "VOTOS_SOBRE_LISTA", "APOYO_MINIMO_FEDERAL_2024_PCT", "COSTO_HIPOTETICO",
                  "CPV_COMPARABLE", "ACCION_HIPOTESIS"]].rename(columns={
        "ID_SECCION": "Sección", "CASILLA_ETIQUETA": "Casilla",
        "LOCALIDAD_INSTALACION": "Localidad de instalación", "FILA_FUENTE": "Fila IEEQ",
        "CLASE": "Clase", "VOTOS_PARTIDO": "Votos partido", "RIVAL": "Rival",
        "VOTOS_RIVAL": "Votos rival", "MARGEN_PP": "Margen (pp)",
        "VOTOS_PARA_LIDERAR": "Votos para liderar", "ABSTENCION": "Abstención",
        "ALCANZABLE_ABSTENCION": "Faltante ≤ abstención", "CPV_COMPARABLE": "CPV comparable",
        "VOTOS_SOBRE_LISTA": "Votos sobre lista",
        "APOYO_MINIMO_FEDERAL_2024_PCT": "Apoyo mínimo federal 2024 (%)",
        "COSTO_HIPOTETICO": "Costo hipotético (MXN)",
        "ACCION_HIPOTESIS": "Esfuerzo a probar",
    })
    modo = st.segmented_control("Mostrar casillas", ["Para revisar", "Todas"],
                                default="Para revisar", key="casillas_modo_tabla")
    tabla = corta.reset_index(drop=True) if modo == "Para revisar" else vista
    filas = seleccion.reset_index(drop=True) if modo == "Para revisar" else todas
    st.caption("Haz clic en una fila para ver su sede cotejada, si está disponible, "
               "y el polígono de la sección con las demás casillas B/C/E.")
    evento = st.dataframe(
        tabla, hide_index=True, width="stretch", height=420,
        on_select="rerun", selection_mode="single-row",
        key=f"casillas_tabla_{partido}_{modo}_{'-'.join(elegidos) if modo == 'Para revisar' else 'todas'}",
        column_order=(["Sección", "Casilla", "Motivo", "Votos partido", "Votos rival",
                       "Votos para liderar", "Abstención", "Perfil CPV de sección"]
                      if modo == "Para revisar" else
                      ["Sección", "Casilla", "Clase", "Votos partido", "Votos rival",
                       "Margen (pp)", "Votos para liderar", "Abstención"]),
        column_config={
            "Sección": st.column_config.TextColumn(pinned=True),
            "Casilla": st.column_config.TextColumn(pinned=True),
            "Votos partido": st.column_config.NumberColumn(format="%.1f"),
            "Votos rival": st.column_config.NumberColumn(format="%.1f"),
            "Margen (pp)": st.column_config.NumberColumn(format="%+.1f"),
        },
        alt="Casillas electorales seleccionables por sección para abrir su ficha y mapa",
    )
    st.download_button("Descargar tabla visible", tabla.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"casillas_{'revision' if modo == 'Para revisar' else 'todas'}_{partido}_2024.csv",
                       mime="text/csv")
    indices = evento.selection.rows
    if indices and 0 <= indices[0] < len(filas):
        _mostrar_ficha_casilla(filas.iloc[indices[0]], base)
    perfil = perfil_cpv(base, max_frases=3)
    st.markdown("#### ¿Por qué aparecen estos patrones?")
    st.caption("Las clases comparan el liderazgo del partido entre siete partidos atribuidos en cada casilla; "
               "no la victoria de la candidatura de coalición. Victoria sólida: ≥10 puntos; derrota "
               "competitiva: hasta 10 puntos de desventaja. Los umbrales son exploratorios.")
    if perfil["frases"]:
        for frase in perfil["frases"][:5]:
            st.write(frase)
    else:
        st.info("No hay suficientes secciones comparables para contrastar clases.")
    st.caption("Cada sección cuenta una vez por clase aunque tenga varias casillas. "
               f"{perfil['n_secciones_en_varias_clases']} contribuciones adicionales pertenecen a secciones "
               "que tienen casillas en más de una clase. Son asociaciones ecológicas descriptivas.")
    with st.expander("Avanzado · las 15 variables y cobertura", on_change="rerun") as avanzado:
        if avanzado.open:
            st.dataframe(perfil["tabla"], hide_index=True, width="stretch",
                         alt="Medias CPV y diferencias estandarizadas por clase de casilla")
            st.write("Casillas sin CPV comparable por clase:", cub["sin_cpv_por_clase"])
            st.caption("Las diferencias estandarizadas describen contraste entre clases, sin p-valores. "
                       "Las 165 secciones con perímetro no comparable se mantienen en la tabla de casillas "
                       "para diagnóstico electoral, pero se excluyen del perfil CPV.")
