"""Evaluación de un partido mediante su candidatura activa en cada fila."""

import pandas as pd

from electoral.candidaturas import resolver_candidatura
from electoral.clasificacion import Umbrales, clasificar
from electoral.rentabilidad import rentabilidad


def rentabilidad_partido(
    df: pd.DataFrame, partido: str, umbrales: Umbrales | None = None
) -> pd.DataFrame:
    """Copia y evalúa la candidatura del partido; no atribuye votos a partidos."""
    candidaturas = [columna for columna in df if columna.startswith("cand_")]
    resuelta = resolver_candidatura(df, partido)
    temporal = "__candidatura_evaluada"
    if temporal in df.columns:
        raise ValueError(f"Columna reservada presente: {temporal}")
    d = df.copy()
    d[temporal] = float("nan")
    for columna in candidaturas:
        mascara = resuelta.eq(columna).fillna(False)
        d.loc[mascara, temporal] = d.loc[mascara, columna]
        d.loc[mascara, columna] = float("nan")
    sin_candidatura = resuelta.isna()
    d.loc[sin_candidatura, "estado"] = "sin_resultado"
    r = clasificar(rentabilidad(d, [*candidaturas, temporal], temporal), umbrales or Umbrales())
    r["estado"] = df["estado"]
    r[candidaturas] = df[candidaturas]
    r["candidatura_resuelta"] = resuelta
    return r.drop(columns=temporal)
