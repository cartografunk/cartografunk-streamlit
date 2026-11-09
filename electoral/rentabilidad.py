"""Métricas de rentabilidad por candidatura y sección."""

import numpy as np
import pandas as pd


def rentabilidad(df: pd.DataFrame, candidaturas: list[str] | tuple[str, ...], evaluar: str) -> pd.DataFrame:
    """Calcula resultados y distancias de una candidatura sin modificar ``df``."""
    candidaturas = list(candidaturas)
    if len(candidaturas) < 2:
        raise ValueError("Se requieren al menos dos candidaturas")
    if evaluar not in candidaturas:
        raise ValueError("La candidatura evaluada debe estar en candidaturas")

    d = df.copy()
    ok = d["estado"].eq("con_resultado")
    votos = d[candidaturas].to_numpy(dtype=float)
    orden = np.sort(np.where(np.isnan(votos), -np.inf, votos), axis=1)[:, ::-1]
    primero, segundo = orden[:, 0], orden[:, 1]
    propio = d[evaluar].to_numpy(dtype=float)

    gana = (propio == primero) & (propio > segundo)
    empate = (propio == primero) & (propio == segundo)
    d["resultado"] = np.select([gana, empate], ["ganada", "empate"], default="perdida")
    d["margen_votos"] = np.where(gana, propio - segundo, np.nan)
    d["faltante_votos"] = np.where(~gana, primero - propio, np.nan)

    validos = d["NUM_VOTOS_VALIDOS"].where(d["NUM_VOTOS_VALIDOS"].ne(0))
    d["margen_pct"] = 100 * d["margen_votos"] / validos
    d["faltante_pct"] = 100 * d["faltante_votos"] / validos
    d["votos_para_ganar"] = d["faltante_votos"] + 1
    votos_en_lista = d["votos_en_lista"] if "votos_en_lista" in d.columns else d["TOTAL_VOTOS"]
    d["abstencion"] = d["LISTA_NOMINAL"] - votos_en_lista
    d["votos_sobre_lista"] = d["abstencion"].lt(0).astype("boolean")
    d["participacion_pct"] = 100 * votos_en_lista / d["LISTA_NOMINAL"].where(d["LISTA_NOMINAL"].ne(0))
    d["rescatable_vs_abst"] = d["votos_para_ganar"] / d["abstencion"].where(d["abstencion"].gt(0))

    columnas = [
        "resultado", "margen_votos", "faltante_votos", "margen_pct", "faltante_pct",
        "votos_para_ganar", "abstencion", "votos_sobre_lista", "participacion_pct", "rescatable_vs_abst",
    ]
    d.loc[~ok, columnas] = np.nan
    return d
