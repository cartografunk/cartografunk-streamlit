"""Lectura y clasificación del ensayo retrospectivo IEEQ 2024 por sección."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


MODELOS_CON_INTERVALO = ("persistencia", "ridge")
PARTIDOS = ("PAN", "PRI", "PRD", "MC", "PVEM", "MORENA", "PT")


def cargar_benchmark(carpeta: Path) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    informe = json.loads((carpeta / "benchmark_partidos_2024.json").read_text(encoding="utf-8"))
    predicciones = pd.read_parquet(carpeta / "benchmark_partidos_2024_seccion.parquet")
    cruce = pd.read_parquet(carpeta / "crosswalk_qro_2018_2021_2024_referencias.parquet")
    if informe.get("estado") != "calculado" or cruce.ID_SECCION.duplicated().any():
        raise ValueError("Benchmark o cruce territorial incompleto")
    return informe, predicciones, cruce


def diagnostico_secciones(informe: dict, predicciones: pd.DataFrame,
                          cruce: pd.DataFrame, partido: str, modelo: str) -> pd.DataFrame:
    """Incluye todas las secciones 2024; abstiene las modificadas y empates."""
    if partido not in PARTIDOS or modelo not in MODELOS_CON_INTERVALO:
        raise ValueError("Partido o modelo sin intervalo histórico")
    ancho = informe["resultados"][modelo]["por_partido"][partido]["intervalo_90_semianchura_pp"]
    base = cruce[["ID_SECCION", "CATEGORIA"]].copy()
    muestra = predicciones.loc[
        predicciones.PARTIDO.eq(partido) & predicciones.MODELO.eq(modelo),
        ["ID_SECCION", "CUOTA_OBSERVADA_PCT", "CUOTA_PREDICHA_PCT",
         "MARGEN_OBSERVADO_PP", "MARGEN_PREDICHO_PP"],
    ]
    if muestra.ID_SECCION.duplicated().any():
        raise ValueError("Predicción duplicada por sección")
    datos = base.merge(muestra, on="ID_SECCION", how="left", validate="one_to_one")
    estable = datos.CATEGORIA.eq("sin_cambio_cartografico_referencia")
    if datos.loc[estable, "MARGEN_PREDICHO_PP"].isna().any() or datos.loc[~estable, "MARGEN_PREDICHO_PP"].notna().any():
        raise ValueError("La cobertura de predicciones no coincide con el cruce")
    datos["LIMITE_INFERIOR_PP"] = datos.MARGEN_PREDICHO_PP - ancho
    datos["LIMITE_SUPERIOR_PP"] = datos.MARGEN_PREDICHO_PP + ancho
    datos["LECTURA"] = "Sin modelo: sección modificada"
    datos.loc[estable, "LECTURA"] = "Indeterminado: intervalo cruza empate"
    datos.loc[estable & datos.LIMITE_INFERIOR_PP.gt(0), "LECTURA"] = "Lidera entre siete partidos"
    datos.loc[estable & datos.LIMITE_SUPERIOR_PP.lt(0), "LECTURA"] = "No lidera entre siete partidos"
    return datos.sort_values("ID_SECCION").reset_index(drop=True)
