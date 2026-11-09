"""Preparación de vistas por candidatura para el demo de 2024."""

import pandas as pd

from electoral.clasificacion import Umbrales, clasificar
from electoral.rentabilidad import rentabilidad
from electoral.reparto import repartir_coalicion


MIEMBROS_COALICION = {
    "cand_PAN_PRI_PRD": ("PAN", "PRI", "PRD"),
    "cand_PVEM_PT_MORENA": ("PVEM", "PT", "MORENA"),
}


def analizar_candidatura(
    secciones: pd.DataFrame, evaluar: str, umbrales: Umbrales = Umbrales()
) -> pd.DataFrame:
    """Clasifica la candidatura activa sin asignarle derrotas donde no compitió."""
    candidaturas = [col for col in secciones if col.startswith("cand_")]
    if evaluar not in candidaturas:
        raise ValueError(f"Candidatura ausente: {evaluar}")
    temporal = secciones.copy()
    temporal.loc[temporal[evaluar].isna(), "estado"] = "sin_resultado"
    salida = clasificar(rentabilidad(temporal, candidaturas, evaluar), umbrales)
    salida["estado"] = secciones["estado"]
    return salida


def aportes_coalicion(
    resultados: pd.DataFrame, evaluar: str, partidos: list[str] | tuple[str, ...]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Atribuye votos con A_propios; conserva el resultado de la candidatura."""
    miembros = MIEMBROS_COALICION[evaluar]
    if not partidos or any(partido not in miembros for partido in partidos):
        raise ValueError("Selecciona integrantes de la coalición")
    repartido = repartir_coalicion(resultados, variante="A_propios")
    activo = repartido.loc[
        repartido["estado"].eq("con_resultado") & repartido[evaluar].notna()
    ].copy()
    for partido in partidos:
        votos = activo[f"rep_{partido}"].astype(float)
        activo[f"pct_candidatura_{partido}"] = 100 * votos / activo[evaluar].where(
            activo[evaluar].gt(0)
        )
        activo[f"pct_validos_{partido}"] = 100 * votos / activo["NUM_VOTOS_VALIDOS"].where(
            activo["NUM_VOTOS_VALIDOS"].gt(0)
        )
    totales = activo[[f"rep_{p}" for p in partidos]].sum().astype(float)
    total_candidatura = float(activo[evaluar].sum())
    total_validos = float(activo["NUM_VOTOS_VALIDOS"].sum())
    estado = pd.DataFrame({
        "Partido": partidos,
        "Votos atribuidos": [totales[f"rep_{p}"] for p in partidos],
        "% de la candidatura": [
            100 * totales[f"rep_{p}"] / total_candidatura if total_candidatura else float("nan")
            for p in partidos
        ],
        "% de votos válidos": [
            100 * totales[f"rep_{p}"] / total_validos if total_validos else float("nan")
            for p in partidos
        ],
    })
    return activo, estado
