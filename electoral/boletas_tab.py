"""Explorador de boletas locales y federales conservadas por año y cargo."""

import math
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

from electoral.dashboard_casillas import _cargar_puntos
from electoral.diagnostico_casillas_tab import _cargar_geometria_seccion
from electoral.reparto_ieeq import COMBINACIONES, INDEPENDIENTES, PROPIOS


@st.cache_data(max_entries=1)
def _datos(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    base = root / "data/electoral/ieeq_local"
    return (pd.read_parquet(base / "boletas_qro_2018_2024_seccion.parquet"),
            pd.read_parquet(base / "votos_opcion_qro_2018_2024_seccion.parquet"))


@st.cache_data(max_entries=1)
def _indice_casillas(root: Path) -> pd.DataFrame:
    return pd.read_parquet(root / "data/electoral/ieeq_local/boletas_qro_2018_2024_casilla.parquet",
                           columns=["ANIO", "CARGO", "ID_MUNICIPIO"])


def apoyo_minimo_directo(boletas: pd.DataFrame, votos: pd.DataFrame,
                         partido: str, municipio: int | None = None,
                         extras: pd.DataFrame | None = None) -> pd.DataFrame:
    """Mínimo de marca directa por partido entre boletas de 2024.

    Cada porcentaje usa los votos válidos de su propia boleta. Las marcas de
    coalición permanecen en otras opciones y no se imputan al partido.
    """
    b = boletas.loc[boletas.ANIO.eq(2024) & boletas.CARGO.isin(
        ("ayuntamiento", "senado"))].copy()
    if municipio is not None:
        b = b.loc[b.ID_MUNICIPIO.eq(municipio)]
    v = votos.loc[votos.ANIO.eq(2024) & votos.CARGO.isin(
        ("ayuntamiento", "senado"))].copy()
    if municipio is not None:
        v = v.loc[v.ID_MUNICIPIO.eq(municipio)]
    validos = v.groupby(["CARGO", "ID_SECCION"], as_index=False).VOTOS.sum().rename(
        columns={"VOTOS": "VOTOS_VALIDOS"})
    propio = v.loc[v.OPCION.eq(partido), ["CARGO", "ID_SECCION", "VOTOS"]]
    tasas = b[["CARGO", "ID_SECCION"]].merge(validos, on=["CARGO", "ID_SECCION"],
                                               validate="one_to_one")
    tasas = tasas.merge(propio, on=["CARGO", "ID_SECCION"], how="left",
                         validate="one_to_one")
    tasas["PCT"] = 100 * tasas.VOTOS / tasas.VOTOS_VALIDOS.where(tasas.VOTOS_VALIDOS.gt(0))
    if extras is not None and not extras.empty:
        otras = extras[["CARGO", "ID_SECCION", "VOTOS_VALIDOS", "VOTOS"]].copy()
        otras["PCT"] = 100 * otras.VOTOS / otras.VOTOS_VALIDOS.where(otras.VOTOS_VALIDOS.gt(0))
        tasas = pd.concat([tasas, otras], ignore_index=True)
    wide = tasas.pivot(index="ID_SECCION", columns="CARGO", values="PCT")
    wide.columns = [f"PCT_{c.upper()}" for c in wide.columns]
    wide = wide.reset_index()
    cols = list(wide.columns.drop("ID_SECCION"))
    if all(c in wide for c in cols):
        wide["APOYO_MINIMO_DIRECTO_PCT"] = wide[cols].min(axis=1, skipna=False)
        wide["RANGO_ENTRE_BOLETAS_PP"] = wide[cols].max(axis=1) - wide[cols].min(axis=1)
    return wide


@st.cache_data(max_entries=16)
def _otras_boletas_2024(root: Path, partido: str) -> pd.DataFrame:
    fuentes = {
        "presidencia": root / "data/electoral/presidencia_2024_seccion.parquet",
        "dip_federal": root / "data/electoral/diputaciones_2024_seccion.parquet",
        "dip_local": root / "data/electoral/ieeq_local/dip_local_mr_2024_seccion_bce.parquet",
    }
    filas = []
    for cargo, path in fuentes.items():
        if not path.exists():
            continue
        d = pd.read_parquet(path)
        if cargo == "dip_local":
            d = d.loc[d.ID_SECCION.str.startswith("22-")].copy()
            validos = d.TOTAL_VOTOS - d.NULOS - d.NO_REGISTRADAS
        else:
            d = d.loc[d.ID_ESTADO.eq(22) & d.SECCION.gt(0)].copy()
            validos = d.NUM_VOTOS_VALIDOS
        filas.append(pd.DataFrame({"CARGO": cargo, "ID_SECCION": d.ID_SECCION,
                                   "VOTOS_VALIDOS": validos, "VOTOS": d[partido]}))
    return pd.concat(filas, ignore_index=True) if filas else pd.DataFrame()


def resumen_marcas_casilla(casillas: pd.DataFrame, opcion: str) -> pd.DataFrame:
    """Compara la marca elegida con la mayor marca rival en cada casilla.

    Es una comparación descriptiva de opciones impresas en la boleta. No
    convierte marcas de coalición en votos de candidaturas ni reparte partidos.
    """
    opciones = [*PROPIOS[2024], *COMBINACIONES[2024], *INDEPENDIENTES[2024]]
    if opcion not in opciones or any(col not in casillas for col in opciones):
        raise ValueError("Faltan opciones de la boleta de Ayuntamiento 2024")
    votos = casillas[opciones].apply(pd.to_numeric, errors="coerce").fillna(0)
    rival = votos.drop(columns=opcion)
    salida = casillas.copy()
    salida["VOTOS_OPCION"] = votos[opcion].astype(int)
    salida["RIVAL"] = rival.idxmax(axis=1)
    salida["VOTOS_RIVAL"] = rival.max(axis=1).astype(int)
    salida["DIFERENCIA_VOTOS"] = salida.VOTOS_OPCION - salida.VOTOS_RIVAL
    validos = votos.sum(axis=1)
    salida["DIFERENCIA_PP"] = (100 * salida.DIFERENCIA_VOTOS /
                               validos.where(validos.gt(0))).round(1)
    salida["LECTURA_RESULTADO"] = [
        ("Sin votos válidos" if total == 0 else
         f"Ventaja de {abs(int(d))} votos ({abs(pp):.1f} pp)" if d > 0 else
         f"Desventaja de {abs(int(d))} votos ({abs(pp):.1f} pp)" if d < 0 else
         "Empate en marcas")
        for d, pp, total in zip(salida.DIFERENCIA_VOTOS,
                                salida.DIFERENCIA_PP, validos)
    ]
    return salida


def zoom_seccion(limites: tuple[float, float, float, float]) -> float:
    """Encuadra el contorno seccional en un mapa de unos 500 × 420 píxeles."""
    oeste, sur, este, norte = limites
    ancho = max(este - oeste, 1e-5)
    alto = max(norte - sur, 1e-5)
    return min(16.0, max(8.0, min(
        math.log2(360 * 240 / (256 * ancho)),
        math.log2(360 * 200 / (256 * alto)),
    )))


def _casillas_ayuntamiento_2024(root: Path, municipio: int, opcion: str) -> None:
    path = root / "data/electoral/ieeq_local/ayuntamiento_2024_casilla.parquet"
    if not path.exists():
        return
    cas = pd.read_parquet(path)
    cas = cas.loc[cas.ID_MUNICIPIO.eq(municipio)].reset_index(drop=True)
    if cas.empty or opcion not in cas:
        return
    st.markdown("#### Casillas de Ayuntamiento 2024")
    st.caption("Cada fila es una casilla B/C/E. Su punto es la sede de instalación 2024; "
               "el CPV pertenece a la sección. Pulsa una casilla de la lista para centrar el mapa.")
    cas = resumen_marcas_casilla(cas, opcion)
    st.caption("La diferencia compara marcas de boleta en esta casilla; no es margen de candidatura.")
    puntos = _cargar_puntos(root / "data/electoral/ieeq_local/casillas_2024_puntos.parquet")
    mapa = cas[["ID_SECCION", "CASILLA_ETIQUETA", "VOTOS_OPCION", "RIVAL",
                "VOTOS_RIVAL", "LECTURA_RESULTADO"]].copy()
    mapa["OPCION"] = opcion
    mapa = mapa.merge(
        puntos[["ID_SECCION", "CASILLA_ETIQUETA", "LATITUD", "LONGITUD"]],
        on=["ID_SECCION", "CASILLA_ETIQUETA"], how="inner", validate="one_to_one")
    seleccion = st.session_state.get("boletas_casilla_seleccionada")
    if seleccion and not ((cas.ID_SECCION.eq(seleccion[0])
                           & cas.CASILLA_ETIQUETA.eq(seleccion[1])).any()):
        seleccion = None
    punto = mapa.loc[mapa.ID_SECCION.eq(seleccion[0])
                     & mapa.CASILLA_ETIQUETA.eq(seleccion[1])] if seleccion else mapa.iloc[0:0]
    punto = punto.iloc[0] if len(punto) else None
    geometria = (_cargar_geometria_seccion(
        root / "data/electoral/secciones_2024_geom.parquet", seleccion[0])
        if seleccion and punto is None else None)
    centro_seccion = ((geometria[1][1] + geometria[1][3]) / 2,
                      (geometria[1][0] + geometria[1][2]) / 2) if geometria else None
    col_mapa, col_tabla = st.columns([1.2, 1], gap="medium")
    with col_mapa:
        if mapa.empty:
            st.info("No hay sedes puntuales para estas casillas; conserva la tabla por casilla.")
        else:
            capas = [pdk.Layer("ScatterplotLayer", id="casillas", data=mapa.to_dict("records"),
                               get_position="[LONGITUD, LATITUD]", get_radius=55,
                               radius_min_pixels=5, radius_max_pixels=13,
                               get_fill_color=[248, 170, 74, 210], pickable=True)]
            if punto is not None:
                capas.append(pdk.Layer("ScatterplotLayer", id="casilla_activa", pickable=False,
                                       data=[{"LATITUD": float(punto.LATITUD),
                                              "LONGITUD": float(punto.LONGITUD)}],
                                       get_position="[LONGITUD, LATITUD]", get_radius=105,
                                       radius_min_pixels=11, radius_max_pixels=19,
                                       get_fill_color=[255, 255, 255, 35],
                                       get_line_color=[255, 255, 255, 255],
                                       line_width_min_pixels=3, stroked=True))
            elif geometria is not None:
                capas.append(pdk.Layer("GeoJsonLayer", id="seccion_activa", data=geometria[0],
                                       pickable=False, filled=True, stroked=True,
                                       get_fill_color=[248, 170, 74, 38],
                                       get_line_color=[255, 255, 255, 240],
                                       get_line_width=3, line_width_min_pixels=2))
            evento_mapa = st.pydeck_chart(
                pdk.Deck(layers=capas, map_style=pdk.map_styles.CARTO_DARK,
                         initial_view_state=pdk.ViewState(
                             latitude=float(punto.LATITUD) if punto is not None else
                             centro_seccion[0] if centro_seccion else 20.6,
                             longitude=float(punto.LONGITUD) if punto is not None else
                             centro_seccion[1] if centro_seccion else -100.4,
                             zoom=13.5 if punto is not None else
                             zoom_seccion(geometria[1]) if geometria else 10),
                         tooltip={"html": "<b>Sección {ID_SECCION} · casilla {CASILLA_ETIQUETA}</b><br/>"
                                          "{OPCION}: {VOTOS_OPCION} votos<br/>"
                                          "{RIVAL}: {VOTOS_RIVAL} votos<br/>"
                                          "{LECTURA_RESULTADO}<br/>"
                                          "<small>Comparación de marcas, no de candidaturas</small>",
                                  "style": {"backgroundColor": "#151523", "color": "#ffffff",
                                            "fontSize": "13px", "padding": "10px"}}),
                height=420, on_select="rerun", selection_mode="single-object",
                key=f"boletas_mapa_{municipio}_{opcion}_{seleccion}",
                alt="Casillas de Ayuntamiento 2024; selecciona una para verla en la tabla")
            objetos = evento_mapa.selection.objects.get("casillas", [])
            if objetos:
                clave = (str(objetos[0]["ID_SECCION"]), str(objetos[0]["CASILLA_ETIQUETA"]))
                if clave != seleccion:
                    st.session_state["boletas_casilla_seleccionada"] = clave
                    st.session_state[f"boletas_buscar_{municipio}"] = clave[0]
                    st.session_state.pop(f"boletas_pagina_{municipio}_{opcion}", None)
                    st.rerun()
    with col_tabla:
        busqueda = st.text_input("Buscar sección o casilla", key=f"boletas_buscar_{municipio}",
                                 placeholder="Ej. 22-0269 o B1")
        visibles = cas.loc[
            cas.ID_SECCION.astype(str).str.contains(busqueda, case=False, regex=False)
            | cas.CASILLA_ETIQUETA.astype(str).str.contains(busqueda, case=False, regex=False)
        ] if busqueda else cas
        por_pagina = 15
        paginas = max(1, (len(visibles) + por_pagina - 1) // por_pagina)
        clave_pagina = f"boletas_pagina_{municipio}_{opcion}"
        if clave_pagina in st.session_state and int(st.session_state[clave_pagina]) > paginas:
            del st.session_state[clave_pagina]
        pagina_seleccionada = 1
        if seleccion:
            posiciones = visibles.index[
                visibles.ID_SECCION.eq(seleccion[0])
                & visibles.CASILLA_ETIQUETA.eq(seleccion[1])
            ]
            if len(posiciones):
                pagina_seleccionada = visibles.index.get_loc(posiciones[0]) // por_pagina + 1
        pagina = st.number_input("Página de casillas", min_value=1, max_value=paginas,
                                 value=pagina_seleccionada, step=1, key=clave_pagina)
        st.caption(f"{len(visibles):,} casillas · página {pagina}/{paginas} · pulsa una fila")
        for fila in visibles.iloc[(pagina - 1) * por_pagina:pagina * por_pagina].itertuples():
            clave = (str(fila.ID_SECCION), str(fila.CASILLA_ETIQUETA))
            marca = "● " if clave == seleccion else ""
            etiqueta = (f"{marca}{fila.ID_SECCION} · {fila.CASILLA_ETIQUETA}   "
                        f"{fila.VOTOS_OPCION} votos de {opcion}   "
                        f"{fila.LECTURA_RESULTADO}")
            if st.button(etiqueta, key=f"boletas_fila_{municipio}_{opcion}_{fila.ID_SECCION}_{fila.CASILLA_ETIQUETA}",
                         use_container_width=True):
                st.session_state["boletas_casilla_seleccionada"] = clave
                st.rerun()
    if seleccion:
        fila = cas.loc[cas.ID_SECCION.eq(seleccion[0])
                       & cas.CASILLA_ETIQUETA.eq(seleccion[1])]
        if len(fila):
            st.info(f"Sección {seleccion[0]} · casilla {seleccion[1]} · "
                    f"{int(fila.iloc[0].VOTOS_OPCION)} votos de {opcion}; "
                    f"{int(fila.iloc[0].VOTOS_RIVAL)} de {fila.iloc[0].RIVAL}. "
                    f"{fila.iloc[0].LECTURA_RESULTADO}. "
                    + ("Sede marcada y mapa centrado." if punto is not None
                       else "Sin sede puntual cotejada; mapa centrado en la sección." if geometria
                       else "Sin sede puntual ni geometría disponible."))


def _casillas_historicas(root: Path, anio: int, cargo: str,
                         municipio: int | None, opcion: str) -> None:
    path = root / "data/electoral/ieeq_local/boletas_qro_2018_2024_casilla.parquet"
    if not path.exists():
        return
    cas = pd.read_parquet(path)
    cas = cas.loc[cas.ANIO.eq(anio) & cas.CARGO.eq(cargo)].copy()
    if municipio is not None:
        cas = cas.loc[cas.ID_MUNICIPIO.eq(municipio)]
    if cas.empty or opcion not in cas:
        return
    cas["VOTOS_OPCION"] = pd.to_numeric(cas[opcion], errors="coerce").fillna(0)
    st.markdown(f"#### Casillas de {cargo} {anio}")
    st.caption("La casilla sigue siendo la unidad de voto. Las sedes 2024 no se reutilizan "
               "como ubicación de casillas históricas: la dirección y el territorio pudieron cambiar.")
    tabla = cas[["ID_SECCION", "CASILLA_ETIQUETA", "VOTOS_OPCION", "TOTAL_VOTOS",
                 "LISTA_NOMINAL"]].reset_index(drop=True)
    evento = st.dataframe(tabla, hide_index=True, width="stretch", height=420,
                          on_select="rerun", selection_mode="single-row",
                          key=f"boletas_historicas_{anio}_{cargo}_{municipio}_{opcion}",
                          alt="Resultados por casilla de la elección histórica elegida")
    if evento.selection.rows:
        fila = tabla.iloc[evento.selection.rows[0]]
        st.info(f"Sección {fila.ID_SECCION} · casilla {fila.CASILLA_ETIQUETA} · "
                f"{int(fila.VOTOS_OPCION)} votos de {opcion}. "
                "Ubicación puntual histórica aún sin cotejar.")


def mostrar_explorador_boletas(root: Path) -> None:
    base = root / "data/electoral/ieeq_local"
    if not (base / "boletas_qro_2018_2024_seccion.parquet").exists():
        st.info("Falta construir el panel local: python scripts/build_ieeq_boletas.py")
        return
    boletas, votos = _datos(root)
    st.subheader("Boletas y antecedentes · Querétaro")
    st.write("Explora casillas por cargo y año. La sección enlaza el contexto territorial y el CPV; "
             "cada boleta conserva sus opciones de voto.")
    pares = sorted(set(zip(boletas.ANIO, boletas.CARGO)), reverse=True)
    control_eleccion, control_municipio, control_opcion = st.columns(3)
    with control_eleccion:
        anio, cargo = st.selectbox("Elección", pares,
                                   format_func=lambda p: f"{p[0]} · {p[1].capitalize()}",
                                   index=pares.index((2024, "ayuntamiento")),
                                   key="explorador_eleccion")
    b = boletas.loc[boletas.ANIO.eq(anio) & boletas.CARGO.eq(cargo)].copy()
    v = votos.loc[votos.ANIO.eq(anio) & votos.CARGO.eq(cargo)].copy()
    if cargo == "ayuntamiento":
        municipios = sorted(b.ID_MUNICIPIO.unique())
        with control_municipio:
            municipio = st.selectbox("Municipio de la boleta", municipios,
                                      index=municipios.index(14) if 14 in municipios else 0,
                                      format_func=lambda n: "Querétaro (14)" if n == 14 else f"Municipio {int(n)}",
                                      key="explorador_municipio")
        b = b.loc[b.ID_MUNICIPIO.eq(municipio)]
        v = v.loc[v.ID_MUNICIPIO.eq(municipio)]
    else:
        municipio = None
    opciones = sorted(v.OPCION.unique())
    with control_opcion:
        opcion = st.selectbox("Opción marcada en la boleta", opciones,
                              index=opciones.index("PAN") if "PAN" in opciones else 0,
                              key="explorador_opcion")
    validos = v.groupby("ID_SECCION", as_index=False).VOTOS.sum().rename(
        columns={"VOTOS": "VOTOS_VALIDOS"})
    elegido = v.loc[v.OPCION.eq(opcion), ["ID_SECCION", "VOTOS"]]
    vista = b.merge(validos, on="ID_SECCION", validate="one_to_one").merge(
        elegido, on="ID_SECCION", how="left", validate="one_to_one")
    vista["CUOTA_PCT"] = 100 * vista.VOTOS / vista.VOTOS_VALIDOS.where(vista.VOTOS_VALIDOS.gt(0))
    a, c, d = st.columns(3)
    if cargo in ("ayuntamiento", "gubernatura"):
        indice = _indice_casillas(root)
        mascara = indice.ANIO.eq(anio) & indice.CARGO.eq(cargo)
        if municipio is not None:
            mascara &= indice.ID_MUNICIPIO.eq(municipio)
        a.metric("Casillas", f"{int(mascara.sum()):,}", help=f"{len(vista):,} secciones")
    else:
        a.metric("Secciones", f"{len(vista):,}")
    c.metric("Votos de la opción", f"{int(vista.VOTOS.sum()):,}")
    d.metric("Cuota de la opción", f"{100 * vista.VOTOS.sum() / vista.VOTOS_VALIDOS.sum():.1f} %")
    st.caption("La opción puede ser partido, coalición o candidatura independiente. "
               "La cuota usa votos válidos de esta boleta, no lista nominal.")
    if anio == 2024 and opcion in ("PAN", "PRI", "PRD", "MC", "PVEM", "MORENA", "PT"):
        extras = _otras_boletas_2024(root, opcion)
        if municipio is not None:
            extras = extras.loc[extras.ID_SECCION.isin(vista.ID_SECCION)]
        piso = apoyo_minimo_directo(boletas, votos, opcion, municipio, extras)
        vista = vista.merge(piso, on="ID_SECCION", how="left", validate="one_to_one")
        con_piso = vista.APOYO_MINIMO_DIRECTO_PCT.notna()
        st.markdown("#### Apoyo mínimo observado al partido")
        st.write("El menor porcentaje de **marca directa al mismo partido** entre Ayuntamiento, "
                 "Senado, Presidencia y diputaciones federal y local de 2024, sección por sección. "
                 "Las combinaciones de "
                 "coalición se muestran por separado y no se reparten aquí.")
        x, y = st.columns(2)
        x.metric("Secciones con cinco boletas", f"{int(con_piso.sum()):,}/{len(vista):,}")
        y.metric("Mediana del mínimo", f"{vista.APOYO_MINIMO_DIRECTO_PCT.median():.1f} %")
        st.caption("Es un mínimo descriptivo entre elecciones, no identifica a las mismas personas "
                   "ni prueba que voten por el partido sin importar la candidatura.")
    columnas = ["ID_SECCION", "VOTOS", "CUOTA_PCT", "TOTAL_VOTOS", "LISTA_NOMINAL"]
    if "APOYO_MINIMO_DIRECTO_PCT" in vista:
        columnas += [c for c in vista if c.startswith("PCT_")]
        columnas += ["APOYO_MINIMO_DIRECTO_PCT"]
    if anio == 2024 and cargo == "ayuntamiento":
        _casillas_ayuntamiento_2024(root, municipio, opcion)
    elif cargo in ("ayuntamiento", "gubernatura"):
        _casillas_historicas(root, anio, cargo, municipio, opcion)
    with st.expander("Resumen por sección · Avanzado"):
        st.dataframe(vista[columnas], hide_index=True, width="stretch", height=460,
                     alt="Resultados por sección de la opción y la elección elegidas")
    st.caption("CPV 2020 se enlaza sólo para secciones 2024 con geometría comparable. "
               "El cotejo histórico 2018/2021→2024 requiere la correspondencia territorial; "
               "coincidir en número de sección no basta.")
