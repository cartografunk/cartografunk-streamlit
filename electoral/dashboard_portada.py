"""Portada ejecutiva: navegación y magnitudes medidas desde archivos locales."""

from pathlib import Path

import pandas as pd
import streamlit as st


PREGUNTAS = (
    ("1 · Dónde ganar", "¿Dónde estamos fuertes o cerca de ganar?",
     "Resultados observados de diputaciones locales 2024 por sección y casilla."),
    ("2 · Por qué", "¿Por qué vemos esos patrones?",
     "Contrastes entre el CPV 2020 y las clases de resultado electoral."),
    ("3 · Confianza", "¿Qué tan confiable es la evidencia?",
     "Cobertura y errores de la evaluación retrospectiva; sin probabilidad futura."),
    ("4 · Esfuerzo", "¿Dónde vale la pena investigar una acción?",
     "Lista exploratoria de casillas con criterios y supuestos visibles."),
)


@st.cache_data(max_entries=1)
def _inventario(root: Path) -> tuple[int | None, int | None, int | None]:
    carpeta = root / "data/electoral/ieeq_local"
    path = carpeta / "ayuntamiento_2024_casilla.parquet"
    puntos_path = carpeta / "casillas_2024_puntos.parquet"
    if not path.exists():
        return None, None, None
    casillas = pd.read_parquet(path, columns=["ID_SECCION", "CASILLA_ETIQUETA"])
    secciones = int(casillas.ID_SECCION.nunique())
    puntos = None
    if puntos_path.exists():
        sedes = pd.read_parquet(
            puntos_path, columns=["ID_SECCION", "CASILLA_ETIQUETA", "CALIDAD"])
        puntos = int(sedes.CALIDAD.isin((
            "clave_domicilio_y_poligono", "domicilio_y_revision_manual",
            "sede_revisada_visual_usuario",
        )).sum())
    return secciones, len(casillas), puntos


def _abrir_pregunta(clave: str) -> None:
    st.session_state["dashboard_pregunta"] = clave
    st.session_state["dashboard_vista"] = "Cuatro preguntas"


def _abrir_boletas() -> None:
    st.session_state["dashboard_vista"] = "Boletas y apoyo mínimo"


def mostrar_portada_dashboard(root: Path) -> None:
    st.html('<div class="electoral-eyebrow">Síntesis electoral</div>')
    st.title("Querétaro, sección por sección")
    st.write("Explora resultados por boleta y cargo; después abre las cuatro preguntas "
             "del piloto de diputaciones locales. Cada afirmación lleva a sus datos y límites.")
    st.caption("Municipio y estado filtran la muestra. Los resultados se muestran por sección "
               "y, para Ayuntamiento 2024, también por casilla.")

    secciones, casillas, puntos = _inventario(root)
    if secciones is None:
        st.info("Los archivos locales de Ayuntamiento 2024 no están disponibles en esta sesión.")
    else:
        a, b, c = st.columns(3)
        a.metric("Secciones · Ayuntamiento 2024", f"{secciones:,}", border=True)
        b.metric("Casillas B/C/E · Ayuntamiento 2024", f"{casillas:,}", border=True)
        c.metric("Casillas con punto de sede", f"{puntos:,}" if puntos is not None else "Sin dato",
                 border=True)
        st.caption("Conteos calculados desde los Parquet locales. El punto indica sede de instalación, "
                   "no residencia de votantes ni área atendida.")

    st.subheader("Cuatro preguntas para decidir qué revisar")
    columnas = st.columns(2)
    for indice, (clave, titulo, descripcion) in enumerate(PREGUNTAS):
        with columnas[indice % 2]:
            with st.container(border=True):
                st.markdown(f"**{titulo}**")
                st.caption(descripcion)
                st.button("Abrir análisis", key=f"portada_pregunta_{indice}",
                          icon=":material/arrow_forward:", width="stretch",
                          on_click=_abrir_pregunta, args=(clave,))

    with st.container(border=True):
        st.markdown("**Boletas y apoyo mínimo**")
        st.write("Consulta Ayuntamiento 2018/2021/2024, Gubernatura 2021 y Senado 2024 "
                 "sin mezclar cargos. El apoyo mínimo compara marcas directas al partido "
                 "en cinco boletas de 2024 por sección.")
        st.button("Explorar boletas", icon=":material/ballot:", width="stretch",
                  on_click=_abrir_boletas)

    st.caption("CPV 2020 vs votos 2024 · asociación, no causa. "
               "Los resultados de 2024 son observados; ninguna vista afirma victoria futura.")
