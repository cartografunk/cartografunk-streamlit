"""Diagnóstico local IEEQ por sección, sin inferencias entre personas ni años."""

from pathlib import Path

import pandas as pd
import streamlit as st


@st.cache_data(max_entries=4)
def _cargar_parquet(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def mostrar_piloto_local(estado: int, root: Path) -> None:
    st.subheader("Diputaciones locales MR · diagnóstico por sección")
    st.caption("Muestra: Querétaro. Cada año usa sus propias secciones. Casillas especiales y voto anticipado se contabilizan aparte de la sección residencial.")
    if estado != 22:
        st.info("Selecciona Querétaro en el filtro de muestra para abrir el piloto local.")
        return
    local_dir = root / "data/electoral/ieeq_local"
    required = [local_dir / f"dip_local_mr_{y}_seccion_bce.parquet" for y in (2018, 2021, 2024)]
    crosswalk_path = local_dir / "crosswalk_qro_2018_2021_2024_referencias.parquet"
    if not all(path.exists() for path in required) or not crosswalk_path.exists():
        st.info("El piloto local requiere los Parquet IEEQ y el cruce cartográfico local; este bloque se oculta cuando faltan.")
        return

    anio_local = st.selectbox("Año local", (2018, 2021, 2024), index=2)
    local = _cargar_parquet(local_dir / f"dip_local_mr_{anio_local}_seccion_bce.parquet")
    seccion_local = st.selectbox("Sección", sorted(local.ID_SECCION.unique()))
    row = local.set_index("ID_SECCION").loc[seccion_local]
    votos_validos = (row["NUM_VOTOS_VALIDOS"] if "NUM_VOTOS_VALIDOS" in row.index
                     else row["TOTAL_VOTOS"] - row["NULOS"] - row["NO_REGISTRADAS"])
    a, b, c = st.columns(3)
    a.metric("Votos B+C+E", f"{int(row['TOTAL_VOTOS']):,}")
    b.metric("Votos válidos B+C+E", f"{int(votos_validos):,}")
    c.metric("Lista nominal B+C+E", f"{int(row['LISTA_NOMINAL']):,}")
    excluded = {
        "ANIO", "TOTAL_VOTOS", "LISTA_NOMINAL", "NUM_VOTOS_VALIDOS",
        "NUM_VOTOS_CAN_NREG", "NUM_VOTOS_NULOS", "NULOS", "NO_REGISTRADAS",
        "CASILLAS_BCE_VALIDAS", "CASILLAS_BCE_TOTALES", "ID_SECCION",
    }
    options = pd.DataFrame([
        {"Opción registrada": name, "Votos": int(row[name])}
        for name in local.columns if name not in excluded and pd.notna(row[name])
    ]).sort_values("Votos", ascending=False)
    st.dataframe(options, hide_index=True, width="stretch", alt="Votos por opción registrada en la sección seleccionada")
    especiales = local_dir / f"dip_local_mr_{anio_local}_especial_mr.parquet"
    if especiales.exists():
        s = _cargar_parquet(especiales)
        s = s.loc[s.ID_SECCION_INSTALACION.eq(seccion_local)]
        if not s.empty:
            st.info(f"Casillas especiales instaladas en esta sección, no residentes: {int(s.VOTOS_MR.sum()):,} votos MR en {len(s)} casilla(s). Se contabilizan fuera de los porcentajes residenciales B+C+E.")
    if anio_local == 2024:
        cross = _cargar_parquet(crosswalk_path).set_index("ID_SECCION").loc[seccion_local]
        stable = cross["CATEGORIA"] == "sin_cambio_cartografico_referencia"
        st.caption("CPV 2020 vs votos 2024 · asociación, no causa. La comparación territorial usa el SHP ECEG del 20-ene-2021 y el polígono original de 2024.")
        if stable:
            st.info("Geometría prácticamente igual (IoU ≥ 0.995) entre cortes cartográficos ECEG 2021 y 2024. La composición de votantes no se puede verificar.")
        else:
            st.warning("Polígono modificado o reconfigurado frente al ECEG: no se atribuye aquí un perfil CPV 2020 a esta sección de 2024.")
        with st.expander("Avanzado · cruce territorial y fuentes"):
            st.write({"Categoría": cross["CATEGORIA"],
                      "Intersección/unión de la misma clave": round(float(cross["IOU_MISMA_CLAVE"]), 6),
                      "Referencia INE 30-sep-2019 → ECEG 20-ene-2021": cross["CATEGORIA_2019_A_2021"]})
            st.caption("La referencia INE 30-sep-2019 no acredita por sí misma el perímetro exacto de la elección 2018. El piloto de ML no pasó el umbral de 70 % de lista nominal comparable en los tres cortes.")
            st.markdown("[Sentencia ST-JRC-216/2024](https://www.te.gob.mx/sentenciasHTML/convertir/expediente/ST-JRC-0216-2024-): totales de casilla coinciden; votos por partido NO VERIFICADOS.")
    else:
        st.caption("Resultado del año seleccionado. Se evita compararlo como una serie territorial hasta verificar su perímetro contra los otros cortes.")
