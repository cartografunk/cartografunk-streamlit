"""Variables seccionales del ECEG 2020 (INEGI-INE)."""

from __future__ import annotations

import pandas as pd


# Nombre, etiqueta, numerador, denominador. Porcentajes de 0 a 100.
VARIABLES = (
    ("pct_mujeres", "Mujeres", "POBFEM", "POBTOT"),
    ("pct_menores_18", "Menores de 18 años", "P_0A17", "POBTOT"),
    ("pct_60_mas", "Personas de 60 años o más", "P_60YMAS", "POBTOT"),
    ("pct_18_24", "Personas de 18 a 24 años", "P_18A24", "POBTOT"),
    ("pct_lengua_indigena", "Habla lengua indígena (3+)", "P3YM_HLI", "P_3YMAS"),
    ("pct_afromexicana", "Población afromexicana", "POB_AFRO", "POBTOT"),
    ("pct_analfabeta", "Analfabetismo (15+)", "P15YM_AN", "P_15YMAS"),
    ("pct_posbasica", "Educación posbásica (18+)", "P18YM_PB", "P_18YMAS"),
    ("pct_pea", "Población económicamente activa (12+)", "PEA", "P_12YMAS"),
    ("pct_sin_salud", "Sin afiliación a salud", "PSINDER", "POBTOT"),
    ("pct_piso_tierra", "Viviendas con piso de tierra", "VPH_PISOTI", "VIVPAR_HAB"),
    ("pct_sin_agua", "Viviendas sin agua entubada", "VPH_AGUAFV", "VIVPAR_HAB"),
    ("pct_sin_drenaje", "Viviendas sin drenaje", "VPH_NODREN", "VIVPAR_HAB"),
    ("pct_internet", "Viviendas con Internet", "VPH_INTER", "VIVPAR_HAB"),
    ("pct_automovil", "Viviendas con automóvil", "VPH_AUTOM", "VIVPAR_HAB"),
)
ETIQUETAS = {nombre: etiqueta for nombre, etiqueta, _, _ in VARIABLES}


def preparar_variables(censo: pd.DataFrame) -> pd.DataFrame:
    """Construye tasas; conserva nulos y evita dividir entre cero.

    La llave es entidad (dos dígitos) + guion + sección (cuatro dígitos). No usa
    municipio ni distrito porque sus límites pueden cambiar entre años.
    """
    requeridas = {"ENTIDAD", "SECCION"} | {c for _, _, n, d in VARIABLES for c in (n, d)}
    faltan = requeridas - set(censo)
    if faltan:
        raise ValueError(f"Faltan columnas ECEG: {sorted(faltan)}")
    entidad = pd.to_numeric(censo["ENTIDAD"], errors="coerce")
    seccion = pd.to_numeric(censo["SECCION"], errors="coerce")
    if entidad.isna().any() or seccion.isna().any():
        raise ValueError("Llaves ECEG inválidas")
    salida = pd.DataFrame({"ID_SECCION": entidad.astype(int).astype(str).str.zfill(2) + "-"
                           + seccion.astype(int).astype(str).str.zfill(4)})
    if salida["ID_SECCION"].duplicated().any():
        raise ValueError("ID_SECCION duplicado en ECEG")
    for nombre, _, numerador, denominador in VARIABLES:
        num = pd.to_numeric(censo[numerador], errors="coerce")
        den = pd.to_numeric(censo[denominador], errors="coerce")
        tasa = 100 * num / den.where(den.gt(0))
        salida[nombre] = tasa.where(tasa.between(0, 100))
    return salida
