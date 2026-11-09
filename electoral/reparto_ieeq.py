"""Atribución analítica fraccionaria de marcas múltiples a partidos IEEQ.

El residuo entero pertenece al cómputo distrital. No se inventa una sección
para él: las secciones conservan fracciones y las sumas preservan cada voto.
"""

from __future__ import annotations

import pandas as pd


PARTIDOS_COMUNES = ("PAN", "PRI", "PRD", "MC", "PVEM", "MORENA", "PT")

PROPIOS = {
    2018: ("PAN", "PRI", "PRD", "MC", "NA", "PVEM", "ES", "MORENA", "PT", "CQ", "QI"),
    2021: ("PAN", "PRI", "PRD", "MC", "PVEM", "MORENA", "PT", "QI", "PES", "RSP", "FM"),
    2024: ("PAN", "PRI", "PRD", "MC", "PVEM", "MORENA", "PT", "QS"),
}

COMBINACIONES = {
    2018: {
        "MORENA_PT_ES": ("MORENA", "PT", "ES"),
        "MORENA_PT": ("MORENA", "PT"),
        "MORENA_ES": ("MORENA", "ES"),
        "PT_ES": ("PT", "ES"),
        "PRI_PVEM": ("PRI", "PVEM"),
        "C_COMUN_PAN_PRD_MC": ("PAN", "PRD", "MC"),
        "PAN_PRD": ("PAN", "PRD"),
        "PAN_MC": ("PAN", "MC"),
        "PRD_MC": ("PRD", "MC"),
        "C_COMUN_PAN_PRD": ("PAN", "PRD"),
    },
    2021: {
        "PAN_QI": ("PAN", "QI"),
        "PRI_PVEM": ("PRI", "PVEM"),
        "PVEM_PT": ("PVEM", "PT"),
    },
    2024: {
        "PVEM-MORENA-PT": ("PVEM", "MORENA", "PT"),
        "PVEM-MORENA": ("PVEM", "MORENA"),
        "PVEM-PT": ("PVEM", "PT"),
        "MORENA-PT": ("MORENA", "PT"),
        "PAN-PRI-PRD": ("PAN", "PRI", "PRD"),
        "PAN-PRI": ("PAN", "PRI"),
        "PAN-PRD": ("PAN", "PRD"),
        "PRI-PRD": ("PRI", "PRD"),
    },
}

INDEPENDIENTES = {
    2018: tuple(f"CAND_IND{i}" for i in range(1, 8)),
    2021: ("CI_13", "CI_14"),
    2024: ("EMC", "JBLL", "RHR", "LDBG", "ATV", "SSP", "MRGH", "SMG"),
}


def atribuir_partidos(secciones: pd.DataFrame, anio: int) -> pd.DataFrame:
    """Devuelve votos fraccionarios por partido y valida conservación de votos."""
    if anio not in PROPIOS:
        raise ValueError(f"Año IEEQ no soportado: {anio}")
    columnas = (*PROPIOS[anio], *COMBINACIONES[anio], *INDEPENDIENTES[anio])
    faltantes = set(columnas) - set(secciones)
    if faltantes:
        raise ValueError(f"Faltan columnas IEEQ: {sorted(faltantes)}")
    salida = secciones[["ID_SECCION"]].copy()
    for partido in PROPIOS[anio]:
        salida[partido] = pd.to_numeric(secciones[partido], errors="raise").astype(float)
    for columna, integrantes in COMBINACIONES[anio].items():
        parte = pd.to_numeric(secciones[columna], errors="raise").astype(float) / len(integrantes)
        for partido in integrantes:
            salida[partido] += parte
    independientes = secciones[list(INDEPENDIENTES[anio])].sum(axis=1).astype(float)
    total_opciones = secciones[list(columnas)].sum(axis=1).astype(float)
    diferencia = (salida[list(PROPIOS[anio])].sum(axis=1) + independientes - total_opciones).abs()
    if (diferencia > 1e-7).any():
        raise ValueError("El reparto fraccionario no conserva los votos")
    salida["VOTOS_VALIDOS"] = total_opciones
    salida["LISTA_NOMINAL"] = secciones["LISTA_NOMINAL"].astype(float)
    salida["TOTAL_VOTOS"] = secciones["TOTAL_VOTOS"].astype(float)
    if anio in (2018, 2021):
        if not (total_opciones == secciones["NUM_VOTOS_VALIDOS"]).all():
            raise ValueError("Opciones y votos válidos IEEQ no cuadran")
    else:
        if not (total_opciones + secciones["NULOS"] + secciones["NO_REGISTRADAS"] == secciones["TOTAL_VOTOS"]).all():
            raise ValueError("Opciones, nulos y no registrados no cuadran")
    return salida
