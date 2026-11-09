"""Resultados de casilla de Presidencia 2024, sin alterar las columnas del CSV."""

from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd

from electoral.config import CANDIDATURAS
from electoral.datos import _leer_csv


LLAVE_CASILLA = (
    "ID_ESTADO", "SECCION", "TIPO_CASILLA", "ID_CASILLA", "EXT_CONTIGUA",
    "ACTA_CASILLA-MEC",
)


def cargar_casillas(zip_path: str | Path) -> pd.DataFrame:
    """Lee _CAS y excluye ``TRIBUNAL=ANULADA``.

    ``ID_CASILLA_LEGIBLE`` tiene formato
    ``EE-SSSS-TIPO-ID_CASILLA-EXT_CONTIGUA-ACTA_CASILLA-MEC``.
    El último componente distingue las 52 llaves de cinco campos repetidas
    en el ZIP de Presidencia 2024.
    """
    with ZipFile(zip_path) as archivo:
        cas = _leer_csv(archivo, "_CAS.CSV")

    requeridas = set(LLAVE_CASILLA) | {"TRIBUNAL", "NUM_VOTOS_VALIDOS", "TOTAL_VOTOS", "LISTA_NOMINAL"}
    requeridas.update(columna for grupo in CANDIDATURAS.values() for columna in grupo)
    faltantes = requeridas.difference(cas.columns)
    if faltantes:
        raise ValueError(f"Columnas faltantes en _CAS.csv: {sorted(faltantes)}")
    if cas[list(LLAVE_CASILLA)].isna().any().any():
        raise ValueError("Llave de casilla con valores nulos")
    if cas.duplicated(list(LLAVE_CASILLA)).any():
        raise ValueError("Llave de casilla duplicada")

    n_anuladas = int(cas["TRIBUNAL"].eq("ANULADA").sum())
    cas = cas.loc[cas["TRIBUNAL"].ne("ANULADA")].copy()
    cas["ID_SECCION"] = (
        cas["ID_ESTADO"].astype("int64").astype(str).str.zfill(2) + "-"
        + cas["SECCION"].astype("int64").astype(str).str.zfill(4)
    )
    cas["ID_CASILLA_LEGIBLE"] = (
        cas["ID_SECCION"] + "-" + cas["TIPO_CASILLA"].astype(str) + "-"
        + cas["ID_CASILLA"].astype("int64").astype(str) + "-"
        + cas["EXT_CONTIGUA"].astype("int64").astype(str) + "-"
        + cas["ACTA_CASILLA-MEC"].astype(str)
    )
    if not cas["ID_CASILLA_LEGIBLE"].is_unique:
        raise ValueError("ID_CASILLA_LEGIBLE duplicado")

    cas["estado"] = np.where(
        cas["SECCION"].eq(0), "extranjero",
        np.where(cas["NUM_VOTOS_VALIDOS"].isna() | cas["NUM_VOTOS_VALIDOS"].eq(0),
                 "sin_resultado", "con_resultado"),
    )
    for nombre, columnas in CANDIDATURAS.items():
        cas[f"cand_{nombre}"] = cas[list(columnas)].sum(axis=1, min_count=1)

    # La lista nominal de S es 0: no se calcula su abstención ni participación.
    cas["votos_en_lista"] = cas["TOTAL_VOTOS"].where(cas["TIPO_CASILLA"].ne("S"))
    cas.attrs["n_anuladas"] = n_anuladas
    return cas
