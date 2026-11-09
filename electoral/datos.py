"""Lectura de resultados por sección sin alterar las columnas de origen."""

from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd

from electoral.config import CANDIDATURAS
from electoral.candidaturas import candidaturas_por_distrito


def _id_seccion(sec: pd.DataFrame) -> pd.Series:
    estado = sec["ID_ESTADO"].astype("int64").astype(str).str.zfill(2)
    seccion = sec["SECCION"].astype("int64").astype(str).str.zfill(4)
    return estado + "-" + seccion


def _estado(sec: pd.DataFrame) -> np.ndarray:
    sin_votos_validos = sec["NUM_VOTOS_VALIDOS"].isna() | sec["NUM_VOTOS_VALIDOS"].eq(0)
    return np.where(
        sec["SECCION"].eq(0),
        "extranjero",
        np.where(sin_votos_validos, "sin_resultado", "con_resultado"),
    )


def _leer_csv(archivo: ZipFile, sufijo: str, usecols: list[str] | None = None,
             **opciones) -> pd.DataFrame:
    miembros = [nombre for nombre in archivo.namelist() if nombre.upper().endswith(sufijo)]
    if len(miembros) != 1:
        raise ValueError(f"Se esperaba un {sufijo}; encontrados: {len(miembros)}")
    with archivo.open(miembros[0]) as csv:
        if csv.peek(3)[:3] == b"\xef\xbb\xbf":
            csv.read(3)
        return pd.read_csv(csv, encoding="cp1252", usecols=usecols, low_memory=False, **opciones)


def _sumar_casillas_s(cas: pd.DataFrame) -> pd.DataFrame:
    s = cas.loc[cas["TIPO_CASILLA"].eq("S") & cas["TRIBUNAL"].ne("ANULADA")]
    return s.groupby(["ID_ESTADO", "SECCION"], dropna=False).agg(
        votos_casillas_s=("TOTAL_VOTOS", "sum"),
        n_casillas_s=("TOTAL_VOTOS", "size"),
    ).reset_index()


def cargar_sec(zip_path: str | Path, eleccion: str = "presidencia") -> pd.DataFrame:
    """Carga _SEC y casillas S no anuladas del ZIP con codificación cp1252."""
    if eleccion not in ("presidencia", "diputaciones", "senadurias"):
        raise ValueError(f"Elección desconocida: {eleccion}")
    with ZipFile(zip_path) as archivo:
        sec = _leer_csv(archivo, "_SEC.CSV")
        discand = (
            _leer_csv(archivo, "_DISCAND.CSV", dtype=str, keep_default_na=False)
            if eleccion != "presidencia" else None
        )
        cas = _leer_csv(
            archivo,
            "_CAS.CSV",
            ["ID_ESTADO", "SECCION", "TIPO_CASILLA", "TOTAL_VOTOS", "TRIBUNAL"],
        )

    columnas = {"ID_ESTADO", "SECCION", "NUM_VOTOS_VALIDOS"}
    columnas.update(columna for grupo in CANDIDATURAS.values() for columna in grupo)
    faltantes = columnas.difference(sec.columns)
    if faltantes:
        raise ValueError(f"Columnas faltantes en _SEC.csv: {sorted(faltantes)}")

    sec["ID_SECCION"] = _id_seccion(sec)
    if not sec["ID_SECCION"].is_unique:
        raise ValueError("ID_SECCION duplicado en _SEC.csv")
    sec["estado"] = _estado(sec)
    if discand is None:
        for candidatura, columnas_votos in CANDIDATURAS.items():
            sec[f"cand_{candidatura}"] = sec[list(columnas_votos)].sum(axis=1, min_count=1)
    else:
        sec = candidaturas_por_distrito(sec, discand)
        if eleccion == "diputaciones":
            discrepancias = {(2, 9), (9, 6), (9, 22), (14, 8), (19, 11),
                             (19, 14), (22, 1), (26, 2), (30, 5)}
            sec["discrepancia_sec_dispp"] = [
                (int(estado), int(distrito)) in discrepancias
                for estado, distrito in sec[["ID_ESTADO", "ID_DISTRITO_FEDERAL"]].itertuples(index=False, name=None)
            ]
    sec = sec.merge(_sumar_casillas_s(cas), on=["ID_ESTADO", "SECCION"], how="left", validate="one_to_one")
    sec[["votos_casillas_s", "n_casillas_s"]] = sec[["votos_casillas_s", "n_casillas_s"]].fillna(0).astype("int64")
    sec["votos_en_lista"] = (sec["TOTAL_VOTOS"] - sec["votos_casillas_s"]).where(sec["estado"].eq("con_resultado"))
    return sec
