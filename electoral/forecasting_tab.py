"""Vista aislada del ensayo retrospectivo de forecasting local."""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from electoral.diagnostico_forecast import (
    MODELOS_CON_INTERVALO, PARTIDOS, cargar_benchmark, diagnostico_secciones,
)
from electoral.perfilamiento_cpv import resumir_partido


@st.cache_data(max_entries=2)
def _cargar(carpeta: Path) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    return cargar_benchmark(carpeta)


@st.cache_data(max_entries=2)
def _cargar_grupos(carpeta: Path) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    resumen = json.loads((carpeta / "resumen_grupos_secciones_2021_2024.json").read_text(encoding="utf-8"))
    benchmark = pd.read_parquet(carpeta / "benchmark_partidos_grupos_2024.parquet")
    mapa = pd.read_csv(carpeta / "mapa_grupos_secciones_2021_2024.csv")
    return resumen, benchmark, mapa


@st.cache_data(max_entries=2)
def _cargar_ml(carpeta: Path) -> tuple[dict, pd.DataFrame]:
    informe = json.loads((carpeta / "benchmark_ml_cpv_2024.json").read_text(encoding="utf-8"))
    filas = pd.read_parquet(carpeta / "benchmark_ml_cpv_2024_seccion.parquet")
    return informe, filas


@st.cache_data(max_entries=2)
def _cargar_perfiles(carpeta: Path) -> tuple[dict, pd.DataFrame]:
    informe = json.loads((carpeta / "perfilamiento_cpv_2024.json").read_text(encoding="utf-8"))
    secciones = pd.read_parquet(carpeta / "perfilamiento_cpv_2024_seccion.parquet")
    return informe, secciones


@st.cache_data(max_entries=2)
def _cargar_candidaturas(carpeta: Path) -> pd.DataFrame:
    return pd.read_parquet(carpeta / "margen_candidatura_ieeq_2024_seccion.parquet")


def mostrar_diagnostico_forecast(estado: int, root: Path) -> None:
    st.subheader("Forecasting · prueba retrospectiva 2024")
    st.caption("Diputaciones locales MR · unidad: sección · Querétaro es el filtro de muestra. Reparto fraccionario de coaliciones por partido.")
    if estado != 22:
        st.info("Selecciona Querétaro en el filtro de muestra para abrir este ensayo local.")
        return
    carpeta = root / "data/electoral/ieeq_local"
    required = ("benchmark_partidos_2024.json", "benchmark_partidos_2024_seccion.parquet",
                "crosswalk_qro_2018_2021_2024_referencias.parquet")
    if not all((carpeta / name).exists() for name in required):
        st.info("El diagnóstico requiere archivos locales del benchmark y cruce territorial; se oculta cuando faltan.")
        return
    informe, predicciones, cruce = _cargar(carpeta)
    partido = st.selectbox("Partido del ensayo", PARTIDOS, index=PARTIDOS.index("MORENA"), key="forecast_partido")
    modelo = st.selectbox("Método", MODELOS_CON_INTERVALO, index=1,
                         format_func=lambda x: "Ridge" if x == "ridge" else "Persistencia 2021",
                         key="forecast_modelo")
    datos = diagnostico_secciones(informe, predicciones, cruce, partido, modelo)
    cobertura = informe["universo"]["comparable"]
    partido_info = informe["resultados"][modelo]["por_partido"][partido]
    metricas = st.columns(3)
    metricas[0].metric("Secciones comparables", f"{cobertura['secciones']}/{informe['universo']['total_secciones']}")
    metricas[1].metric("Lista nominal cubierta", f"{cobertura['cobertura_lista_nominal_pct']:.1f} %")
    metricas[2].metric("MAE de cuota del partido", f"{partido_info['mae_pct']:.1f} pp")
    sin_modelo = informe["universo"]["total_secciones"] - cobertura["secciones"]
    sustantivo = "sección queda" if sin_modelo == 1 else "secciones quedan"
    st.caption(f"{sin_modelo} {sustantivo} sin modelo por cambio territorial. El estado sólo filtra la muestra; no se muestran resultados agregados por estado, municipio o distrito.")
    st.warning("Ensayo retrospectivo, no pronóstico validado. “Lidera” compara siete partidos con serie 2018–2024; no equivale a ganar la candidatura MR. El intervalo nominal 90 % no alcanzó esa cobertura en todos los partidos.")
    resumen = datos.LECTURA.value_counts()
    st.write(
        f"{int(resumen.get('Lidera entre siete partidos', 0))} secciones: lidera · "
        f"{int(resumen.get('No lidera entre siete partidos', 0))}: no lidera · "
        f"{int(resumen.get('Indeterminado: intervalo cruza empate', 0))}: indeterminado · "
        f"{int(resumen.get('Sin modelo: sección modificada', 0))}: sin modelo."
    )
    st.caption(f"En el resultado observado lideró en {partido_info['lideres_observados']} de las {cobertura['secciones']} comparables; "
               f"el método detectó {partido_info['lideres_detectados']}. "
               "Esto mide desempeño retrospectivo, no confianza futura.")
    vista = datos.rename(columns={
        "ID_SECCION": "Sección", "LECTURA": "Lectura del ensayo",
        "CUOTA_PREDICHA_PCT": "Cuota estimada (%)", "CUOTA_OBSERVADA_PCT": "Cuota observada 2024 (%)",
        "MARGEN_PREDICHO_PP": "Margen estimado (pp)", "MARGEN_OBSERVADO_PP": "Margen observado 2024 (pp)",
        "LIMITE_INFERIOR_PP": "Límite inferior (pp)", "LIMITE_SUPERIOR_PP": "Límite superior (pp)",
    })[["Sección", "Lectura del ensayo", "Cuota estimada (%)", "Cuota observada 2024 (%)",
        "Margen estimado (pp)", "Margen observado 2024 (pp)", "Límite inferior (pp)", "Límite superior (pp)"]]
    st.dataframe(vista, hide_index=True, width="stretch",
                 alt="Diagnóstico retrospectivo por sección con predicción, resultado observado y abstenciones")
    st.subheader("Leer una sección")
    seccion = st.selectbox("Sección del ensayo", datos.ID_SECCION.tolist(), key="forecast_seccion")
    fila = datos.set_index("ID_SECCION").loc[seccion]
    if pd.isna(fila.MARGEN_PREDICHO_PP):
        st.info("Esta sección no recibió estimación: su perímetro cambió entre los cortes comparados. El encarte no permite repartir su voto anterior.")
    else:
        base_2021 = predicciones.loc[
            predicciones.ID_SECCION.eq(seccion) & predicciones.PARTIDO.eq(partido)
            & predicciones.MODELO.eq("persistencia")
        ]
        if len(base_2021) != 1:
            raise ValueError("Falta la cuota 2021 usada como referencia")
        cuota_2021 = float(base_2021.iloc[0].CUOTA_PREDICHA_PCT)
        cambio = fila.CUOTA_PREDICHA_PCT - cuota_2021
        st.write(
            f"En 2021, la cuota atribuida a {partido} fue {cuota_2021:.1f} %. "
            f"{modelo.capitalize()} estimó {fila.CUOTA_PREDICHA_PCT:.1f} % para 2024 "
            f"({cambio:+.1f} puntos). El margen estimado frente al mayor de los otros "
            f"seis partidos fue {fila.MARGEN_PREDICHO_PP:+.1f} puntos; su intervalo "
            f"histórico va de {fila.LIMITE_INFERIOR_PP:+.1f} a {fila.LIMITE_SUPERIOR_PP:+.1f}. "
            f"Lectura: {fila.LECTURA.lower()}."
        )
        st.caption("Esta explicación describe las entradas y la salida del método; asociación, no causa. El resultado observado de 2024 está en la tabla para comprobar el ensayo.")
    st.download_button("Descargar diagnóstico por sección", vista.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"diagnostico_forecast_{partido}_{modelo}_2024.csv", mime="text/csv")
    archivos_grupos = ("resumen_grupos_secciones_2021_2024.json",
                       "benchmark_partidos_grupos_2024.parquet",
                       "mapa_grupos_secciones_2021_2024.csv")
    if all((carpeta / name).exists() for name in archivos_grupos):
        resumen_grupos, benchmark_grupos, mapa_grupos = _cargar_grupos(carpeta)
        st.subheader("Comparación con secciones reagrupadas")
        st.write("Cuando una sección se dividió o fusionó, sumamos las casillas B+C+E de todas las secciones relacionadas en cada año. Cada voto entra una sola vez.")
        st.caption(f"{resumen_grupos['secciones_2021']} secciones de 2021 y {resumen_grupos['secciones_2024']} de 2024 → "
                   f"{resumen_grupos['grupos_comparables']} grupos: {resumen_grupos['grupos_uno_a_uno']} de una a una y "
                   f"{resumen_grupos['grupos_reconfigurados']} reconfigurados. "
                   f"Lista nominal 2024 incluida: {resumen_grupos['lista_nominal_2024_agrupada']:,}.")
        st.caption("En los grupos reconfigurados la estimación corresponde al grupo completo, no a cada sección hija. Este benchmark por grupos no tiene intervalo recalibrado: no se informa confianza ni decisión de victoria.")
        solo_reconfigurados = st.checkbox("Ver sólo grupos reconfigurados", value=True, key="forecast_solo_grupos")
        sizes = mapa_grupos.drop_duplicates("ID_GRUPO_2021_2024")[[
            "ID_GRUPO_2021_2024", "SECCIONES_2021_EN_GRUPO", "SECCIONES_2024_EN_GRUPO"]]
        grupos = benchmark_grupos.loc[
            benchmark_grupos.PARTIDO.eq(partido) & benchmark_grupos.MODELO.eq(modelo)
        ].merge(sizes, on="ID_GRUPO_2021_2024", validate="one_to_one")
        if solo_reconfigurados:
            grupos = grupos.loc[
                grupos.SECCIONES_2021_EN_GRUPO.gt(1) | grupos.SECCIONES_2024_EN_GRUPO.gt(1)]
        grupos = grupos.rename(columns={
            "ID_GRUPO_2021_2024": "Grupo (clave 2021)",
            "SECCIONES_2021_EN_GRUPO": "Secciones 2021", "SECCIONES_2024_EN_GRUPO": "Secciones 2024",
            "CUOTA_2021_PCT": "Cuota 2021 (%)", "CUOTA_2024_ESTIMADA_PCT": "Estimado 2024 (%)",
            "CUOTA_2024_OBSERVADA_PCT": "Observado 2024 (%)",
            "MARGEN_2024_ESTIMADO_PP": "Margen estimado (pp)",
            "MARGEN_2024_OBSERVADO_PP": "Margen observado (pp)",
        })[["Grupo (clave 2021)", "Secciones 2021", "Secciones 2024", "Cuota 2021 (%)",
            "Estimado 2024 (%)", "Observado 2024 (%)", "Margen estimado (pp)", "Margen observado (pp)"]]
        st.dataframe(grupos, hide_index=True, width="stretch",
                     alt="Comparación retrospectiva de votos por partido en grupos de secciones relacionadas")
    if all((carpeta / name).exists() for name in (
        "benchmark_ml_cpv_2024.json", "benchmark_ml_cpv_2024_seccion.parquet"
    )):
        ml_report, ml_rows = _cargar_ml(carpeta)
        ml = ml_report["modelos"]["hist_gradient_boosting_cpv"]["por_partido"][partido]
        ridge_ml = ml_report["modelos"]["ridge_sin_cpv"]["por_partido"][partido]
        st.subheader("ML con CPV · prueba retrospectiva")
        st.write(
            f"En {ml_report['evaluacion_2024_secciones']} secciones comparables, el modelo con CPV "
            f"tuvo un error medio de {ml['mae_cuota_pp']:.1f} puntos para {partido}; "
            f"Ridge sin CPV tuvo {ridge_ml['mae_cuota_pp']:.1f}. "
            f"Detectó {ml['lideres_detectados']} de {ml['lideres_observados']} secciones "
            f"donde {partido} lideró, y marcó {ml['falsos_lideres']} liderazgos que no ocurrieron."
        )
        st.caption("CPV 2020 vs votos 2024; asociación, no causa. Es una prueba con 2024 ya observado, sin confianza futura calibrada. Las secciones modificadas quedan fuera.")
        table = ml_rows.loc[
            ml_rows.PARTIDO.eq(partido)
            & ml_rows.MODELO.eq("hist_gradient_boosting_cpv")
        ].rename(columns={
            "ID_SECCION": "Sección", "CUOTA_PREDICHA_PCT": "Estimado 2024 (%)",
            "CUOTA_OBSERVADA_PCT": "Observado 2024 (%)",
            "MARGEN_PREDICHO_PP": "Margen estimado (pp)",
            "MARGEN_OBSERVADO_PP": "Margen observado (pp)",
        })[["Sección", "Estimado 2024 (%)", "Observado 2024 (%)",
            "Margen estimado (pp)", "Margen observado (pp)"]]
        st.dataframe(table, hide_index=True, width="stretch",
                     alt="Ensayo ML retrospectivo por partido y sección comparable")
        if all((carpeta / name).exists() for name in (
            "perfilamiento_cpv_2024.json", "perfilamiento_cpv_2024_seccion.parquet"
        )):
            perfiles, secciones_perfil = _cargar_perfiles(carpeta)
            archivo_candidaturas = carpeta / "margen_candidatura_ieeq_2024_seccion.parquet"
            candidaturas_locales = _cargar_candidaturas(carpeta) if archivo_candidaturas.exists() else None
            perfil_partido, detalle_perfil = resumir_partido(
                secciones_perfil, ml_rows, partido, candidaturas_locales)
            st.subheader("Perfiles CPV de secciones")
            st.write(
                f"Agrupamos {perfiles['secciones_con_perfil']} secciones por sus 15 tasas censales. "
                "Las cifras de voto describen cómo se comportó cada grupo en 2024."
            )
            perfil_partido["Rasgos CPV"] = perfil_partido.PERFIL_CPV.map(
                lambda n: ", ".join(
                    ("Más " if item["direccion"] == "mayor" else "Menos ")
                    + item["etiqueta"].lower()
                    for item in perfiles["perfiles"][str(n)]["rasgos"]
                )
            )
            vista_perfiles = perfil_partido.rename(columns={
                "PERFIL_CPV": "Perfil", "secciones": "Secciones",
                "cuota_observada_media_pct": "Cuota media por sección (%)",
                "lidera_observado": "Lideró entre siete partidos",
                "derrotas_cercanas": "Partido a ≤5 pp del primero",
                "cercanas_y_ml_predijo_liderazgo": "ML: liderazgo puntual",
            })[["Perfil", "Rasgos CPV", "Secciones", "Cuota media por sección (%)",
                "Lideró entre siete partidos", "Partido a ≤5 pp del primero", "ML: liderazgo puntual"]]
            if candidaturas_locales is not None:
                vista_perfiles["Candidatura ya lideró"] = perfil_partido.candidatura_lidero
            st.dataframe(vista_perfiles, hide_index=True, width="stretch",
                         alt="Perfiles censales de secciones y resultados partidarios observados")
            st.caption("Margen partidario entre siete partidos con reparto fraccionario. «ML: liderazgo puntual» describe un error retrospectivo y no usa el intervalo: puede cruzar el empate. La candidatura local puede haber ganado aunque uno de sus partidos no liderara. Hipótesis de reversión, sin prueba.")
            cercanas = detalle_perfil.loc[detalle_perfil.DERROTA_CERCANA].copy()
            if len(cercanas):
                cercanas["Distancia partidaria observada (pp)"] = -cercanas.MARGEN_OBSERVADO_PP
                cercanas["ML: liderazgo puntual"] = cercanas.FALSO_LIDERAZGO_ML
                if candidaturas_locales is not None:
                    cercanas["Candidatura local"] = cercanas.MARGEN_CANDIDATURA_PP.map(
                        lambda m: "Lideró" if m > 0 else "Empató" if m == 0 else "No lideró")
                cercanas = cercanas.sort_values(["PERFIL_CPV", "ID_SECCION"]).rename(columns={
                    "ID_SECCION": "Sección", "PERFIL_CPV": "Perfil",
                })
                columnas_cercanas = ["Sección", "Perfil", "Distancia partidaria observada (pp)",
                                     "ML: liderazgo puntual"]
                if candidaturas_locales is not None:
                    columnas_cercanas += ["Candidatura local", "MARGEN_CANDIDATURA_PP"]
                    cercanas = cercanas.rename(columns={
                        "MARGEN_CANDIDATURA_PP": "Margen candidatura local (pp)"})
                    columnas_cercanas[-1] = "Margen candidatura local (pp)"
                st.dataframe(cercanas[columnas_cercanas], hide_index=True, width="stretch",
                             alt="Secciones donde el partido quedó a cinco puntos o menos del primero entre siete")
    with st.expander("Avanzado · método y límites"):
        st.write("Ridge aprende de la transición 2018→2021 y estima 2024 con cuota, participación y lista nominal de 2021. "
                 "Su intervalo se calibró con errores históricos; CPV 2020 no entra a Ridge. "
                 "El ensayo ML separado sí usa CPV 2020. El bloque «¿Por qué?» describe asociaciones, sin explicación causal.")
        st.write(f"Semianchura del intervalo: {partido_info['intervalo_90_semianchura_pp']:.1f} pp. "
                 f"Cobertura observada en 2024: {partido_info['cobertura_empirica_intervalo_pct']:.1f} %. ")
        st.caption("Los 19 IDs desaparecidos y 81 nuevos se auditan por separado. El domicilio de casilla no redistribuye electores ni votos. "
                   "NO VERIFICADO: equivalencia exacta del marco 2018, desempeño prospectivo, reparto entero distrital y reasignación de personas en las secciones modificadas.")
        if all((carpeta / name).exists() for name in (
            "benchmark_ml_cpv_2024.json", "benchmark_ml_cpv_2024_seccion.parquet"
        )):
            st.write("El ensayo ML entrena un árbol de gradiente por partido con 2018→2021: siete cuotas previas, participación, logaritmo de lista nominal y 15 tasas CPV 2020. Evalúa 2021→2024 sin ajustar el modelo con votos 2024. El CPV faltante queda nulo; el algoritmo admite nulos.")
