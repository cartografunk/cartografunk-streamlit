"""Reparto fraccionario experimental de votos combinados por sección."""

import numpy as np
import pandas as pd

from electoral.reparto import COALICIONES


def repartir_fraccionario(df: pd.DataFrame) -> pd.DataFrame:
    """Suma a cada partido su fracción de cada combinación, sin redondear.

    Solo calcula filas ``con_resultado``. No es una regla oficial verificada.
    """
    salida = df.copy()
    calculables = salida["estado"].eq("con_resultado")
    filas = salida.loc[calculables]
    for grupo in COALICIONES.values():
        partidos = grupo["partidos"]
        propios = filas[list(partidos)].to_numpy(dtype="float64")
        asignados = propios.copy()
        for columna, integrantes in grupo["combinaciones"].items():
            fraccion = filas[columna].to_numpy(dtype="float64") / len(integrantes)
            for partido in integrantes:
                asignados[:, partidos.index(partido)] += fraccion
        for indice, partido in enumerate(partidos):
            columna = f"frac_{partido}"
            salida[columna] = np.nan
            salida.loc[calculables, columna] = asignados[:, indice]
    return salida
