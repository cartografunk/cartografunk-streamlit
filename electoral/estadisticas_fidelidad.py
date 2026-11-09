"""Estadísticas de apoyo para validar el indicador de fidelidad (2024).

Trabaja sobre las tablas de ``electoral.fidelidad``: ``panel`` (formato largo)
y ``estabilidad``. No clasifica secciones ni fija umbrales.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd


def icc_consistencia(X: np.ndarray) -> tuple[float, float]:
    """ICC(1) e ICC(3, consistencia) de una matriz secciones x elecciones.

    ICC(1) penaliza diferencias de nivel entre elecciones; ICC(3) mide solo si
    las secciones conservan su orden relativo.
    """
    n, k = X.shape
    if n < 2 or k < 2:
        raise ValueError("Se necesitan al menos 2 secciones y 2 elecciones")
    media_i = X.mean(axis=1)
    gran = X.mean()
    msb = k * ((media_i - gran) ** 2).sum() / (n - 1)
    msw = ((X - media_i[:, None]) ** 2).sum() / (n * (k - 1))
    sse = ((X - media_i[:, None] - X.mean(axis=0)[None, :] + gran) ** 2).sum()
    mse = sse / ((n - 1) * (k - 1))
    return (
        float((msb - msw) / (msb + (k - 1) * msw)),
        float((msb - mse) / (msb + (k - 1) * mse)),
    )


def _ancho(largo: pd.DataFrame, partido: str) -> pd.DataFrame:
    d = largo.loc[largo["partido"].eq(partido)]
    return d.pivot(index="ID_SECCION", columns="eleccion", values="pct").dropna()


def icc_por_partido(largo: pd.DataFrame) -> pd.DataFrame:
    """ICC por partido sobre el panel largo."""
    filas = []
    for partido in sorted(largo["partido"].unique()):
        ancho = _ancho(largo, partido)
        icc1, icc3 = icc_consistencia(ancho.to_numpy())
        filas.append(
            {"partido": partido, "n": len(ancho), "icc1": icc1, "icc3_consistencia": icc3}
        )
    return pd.DataFrame(filas)


def correlaciones_pares(largo: pd.DataFrame) -> pd.DataFrame:
    """Pearson y Spearman por partido y par de elecciones (sección a sección)."""
    filas = []
    for partido in sorted(largo["partido"].unique()):
        ancho = _ancho(largo, partido)
        for a, b in combinations(ancho.columns, 2):
            filas.append(
                {
                    "partido": partido,
                    "par": f"{a} vs {b}",
                    "n": len(ancho),
                    "pearson": ancho[a].corr(ancho[b], method="pearson"),
                    "spearman": ancho[a].corr(ancho[b], method="spearman"),
                }
            )
    return pd.DataFrame(filas)


def distribucion_rango(estab: pd.DataFrame, por: list[str] | None = None) -> pd.DataFrame:
    """Percentiles 10/50/90 de ``rango_pp`` y ``piso_pct`` por partido (y ``por``)."""
    claves = ["partido", *(por or [])]
    g = estab.groupby(claves)
    salida = pd.concat(
        {
            f"{col}_p{int(q * 100)}": g[col].quantile(q)
            for col in ("rango_pp", "piso_pct")
            for q in (0.10, 0.50, 0.90)
        },
        axis=1,
    )
    salida.insert(0, "n_secciones", g.size())
    return salida.reset_index()
