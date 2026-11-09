"""Candidaturas registradas por distrito según las columnas pobladas de DISCAND."""

from __future__ import annotations

import pandas as pd

from electoral.config import CANDIDATURAS


PARTIDOS = ("PAN", "PRI", "PRD", "PVEM", "PT", "MC", "MORENA")
COALICIONES = ("PAN_PRI_PRD", "PVEM_PT_MORENA")
CLAVES = ("ID_ESTADO", "ID_DISTRITO_FEDERAL")


def _columnas_candidatura(discand: pd.DataFrame) -> list[str]:
    columnas = list(discand.columns)
    inicio = columnas.index("ACTAS_CASILLA-MEC") + 1
    fin = columnas.index("NUM_VOTOS_VALIDOS")
    return columnas[inicio:fin]


def actividad_distrital(discand: pd.DataFrame) -> dict[tuple[int, int], tuple[str, ...]]:
    """Devuelve las columnas no vacías de candidatura para cada distrito."""
    columnas = _columnas_candidatura(discand)
    filas = discand.loc[
        discand["ID_ESTADO"].astype(str).str.strip().ne("")
        & discand["ID_DISTRITO_FEDERAL"].astype(str).str.strip().ne("")
    ]
    actividad: dict[tuple[int, int], tuple[str, ...]] = {}
    for fila in filas.itertuples(index=False, name=None):
        valores = dict(zip(discand.columns, fila))
        clave = (int(valores["ID_ESTADO"]), int(valores["ID_DISTRITO_FEDERAL"]))
        if clave in actividad:
            raise ValueError(f"Distrito duplicado en DISCAND: {clave}")
        actividad[clave] = tuple(
            columna for columna in columnas if str(valores[columna]).strip()
        )
    return actividad


def candidaturas_por_distrito(sec: pd.DataFrame, discand: pd.DataFrame) -> pd.DataFrame:
    """Copia SEC y añade cand_* solo donde cada candidatura compitió."""
    actividad = actividad_distrital(discand)
    claves_sec = set(map(tuple, sec[list(CLAVES)].drop_duplicates().to_numpy()))
    if claves_sec != set(actividad):
        raise ValueError(f"Claves SEC/DISCAND distintas: {len(claves_sec - set(actividad))} sin DISCAND")
    d = sec.copy()
    nombres = _columnas_candidatura(discand)
    for nombre in nombres:
        d[f"cand_{nombre}"] = float("nan")
    for clave, activos in actividad.items():
        mascara = d["ID_ESTADO"].eq(clave[0]) & d["ID_DISTRITO_FEDERAL"].eq(clave[1])
        for nombre in activos:
            columnas = CANDIDATURAS[nombre] if nombre in COALICIONES else (nombre,)
            if any(columna not in d.columns for columna in columnas):
                raise ValueError(f"Columnas SEC ausentes para {nombre}: {columnas}")
            d.loc[mascara, f"cand_{nombre}"] = (
                d.loc[mascara, list(columnas)].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1)
            )
    return d


def resolver_candidatura(df: pd.DataFrame, partido: str) -> pd.Series:
    """Nombre de la columna de candidatura activa que contiene al partido por fila."""
    if partido not in PARTIDOS:
        raise ValueError(f"Partido desconocido: {partido}")
    resultado = pd.Series(pd.NA, index=df.index, dtype="string")
    coalicion = next((nombre for nombre in COALICIONES if partido in nombre.split("_")), None)
    if coalicion is not None and f"cand_{coalicion}" in df.columns:
        activa = df[f"cand_{coalicion}"].notna()
        resultado.loc[activa] = f"cand_{coalicion}"
    individual = f"cand_{partido}"
    if individual in df.columns:
        activa = resultado.isna() & df[individual].notna()
        resultado.loc[activa] = individual
    return resultado
