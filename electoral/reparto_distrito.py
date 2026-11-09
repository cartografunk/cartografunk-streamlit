"""Reparto experimental de votos combinados agregados por distrito."""

import numpy as np
import pandas as pd

from electoral.reparto import COALICIONES, VARIANTES


CLAVES = ("ID_ESTADO", "ID_DISTRITO_FEDERAL")


def _repartir_votos(
    asignados: np.ndarray,
    propios: np.ndarray,
    votos: np.ndarray,
    integrantes: tuple[int, ...],
) -> None:
    cociente, residuo = np.divmod(votos, len(integrantes))
    for indice in integrantes:
        asignados[:, indice] += cociente
    primero = np.asarray(integrantes)[np.argmax(propios[:, integrantes], axis=1)]
    asignados[np.arange(len(votos)), primero] += residuo


def repartir_distrito(df: pd.DataFrame, variante: str = "A_propios") -> pd.DataFrame:
    """Suma _SEC por distrito y reparte combinaciones usando votos propios.

    Incluye las filas de extranjero del distrito federal 0 y las filas sin
    resultado tal como aparecen en _SEC. A divide cada combinación entre sus
    integrantes; B junta las combinaciones de cada coalición y divide entre
    sus tres partidos. El residuo entero va al integrante con más votos
    propios del distrito; un empate sigue el orden fijo de ``COALICIONES``.
    Ninguna variante está verificada como la regla oficial.
    """
    if variante not in VARIANTES:
        raise ValueError(f"Variante desconocida: {variante}")

    columnas_votos = ["MC"]
    for grupo in COALICIONES.values():
        columnas_votos.extend(grupo["partidos"])
        columnas_votos.extend(grupo["combinaciones"])
    sumas = df.groupby(list(CLAVES), dropna=False, sort=True)[columnas_votos].sum().reset_index()
    salida = sumas[list(CLAVES)].copy()
    salida["rep_MC"] = sumas["MC"].astype("int64")

    for nombre, grupo in COALICIONES.items():
        partidos = grupo["partidos"]
        combinaciones = grupo["combinaciones"]
        propios = sumas[list(partidos)].to_numpy(dtype="int64")
        asignados = propios.copy()
        salida[f"suma_original_{nombre}"] = sumas[list(partidos) + list(combinaciones)].sum(axis=1).astype("int64")
        if variante == "A_propios":
            for columna, integrantes in combinaciones.items():
                indices = tuple(partidos.index(partido) for partido in integrantes)
                _repartir_votos(
                    asignados, propios, sumas[columna].to_numpy(dtype="int64"), indices
                )
        else:
            votos = sumas[list(combinaciones)].sum(axis=1).to_numpy(dtype="int64")
            _repartir_votos(asignados, propios, votos, tuple(range(len(partidos))))
        for indice, partido in enumerate(partidos):
            salida[f"rep_{partido}"] = asignados[:, indice]
    return salida
