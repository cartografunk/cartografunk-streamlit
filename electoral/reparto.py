"""Repartos experimentales de votos combinados entre partidos."""

import numpy as np
import pandas as pd


COALICIONES = {
    "PAN_PRI_PRD": {
        "partidos": ("PAN", "PRI", "PRD"),
        "combinaciones": {
            "PAN_PRI_PRD": ("PAN", "PRI", "PRD"),
            "PAN_PRI": ("PAN", "PRI"),
            "PAN_PRD": ("PAN", "PRD"),
            "PRI_PRD": ("PRI", "PRD"),
        },
    },
    "PVEM_PT_MORENA": {
        "partidos": ("PVEM", "PT", "MORENA"),
        "combinaciones": {
            "PVEM_PT_MORENA": ("PVEM", "PT", "MORENA"),
            "PVEM_PT": ("PVEM", "PT"),
            "PVEM_MORENA": ("PVEM", "MORENA"),
            "PT_MORENA": ("PT", "MORENA"),
        },
    },
}
VARIANTES = ("A_propios", "B_propios")


def _sumar_reparto(
    asignados: np.ndarray,
    propios: np.ndarray,
    votos: np.ndarray,
    integrantes: tuple[int, ...],
) -> None:
    """Suma cocientes iguales y entrega todo el residuo al primer máximo propio."""
    cociente, residuo = np.divmod(votos, len(integrantes))
    for indice in integrantes:
        asignados[:, indice] += cociente
    ganador = np.asarray(integrantes)[np.argmax(propios[:, integrantes], axis=1)]
    asignados[np.arange(len(votos)), ganador] += residuo


def _repartir_grupo(filas: pd.DataFrame, definicion: dict, variante: str) -> np.ndarray:
    partidos = definicion["partidos"]
    propios = filas[list(partidos)].to_numpy(dtype="int64")
    asignados = propios.copy()
    if variante == "A_propios":
        for columna, integrantes in definicion["combinaciones"].items():
            indices = tuple(partidos.index(partido) for partido in integrantes)
            _sumar_reparto(
                asignados, propios, filas[columna].to_numpy(dtype="int64"), indices
            )
    else:
        combinaciones = list(definicion["combinaciones"])
        votos = filas[combinaciones].sum(axis=1).to_numpy(dtype="int64")
        _sumar_reparto(asignados, propios, votos, tuple(range(len(partidos))))
    return asignados


def repartir_coalicion(df: pd.DataFrame, variante: str = "A_propios") -> pd.DataFrame:
    """Reparte votos combinados por fila de _SEC, sin mutar la entrada.

    A_propios divide cada combinación entre sus integrantes; B_propios junta
    todas las combinaciones de cada coalición antes de dividir entre sus tres
    partidos. El residuo entero va al integrante con más votos propios en la
    fila; un empate se rompe por el orden fijo de ``COALICIONES``. Ninguna
    variante está verificada como la regla oficial.
    """
    if variante not in VARIANTES:
        raise ValueError(f"Variante desconocida: {variante}")
    salida = df.copy()
    calculables = salida["estado"].eq("con_resultado")
    filas = salida.loc[calculables]
    for definicion in COALICIONES.values():
        asignados = _repartir_grupo(filas, definicion, variante)
        for indice, partido in enumerate(definicion["partidos"]):
            columna = f"rep_{partido}"
            salida[columna] = pd.Series(pd.NA, index=salida.index, dtype="Int64")
            salida.loc[calculables, columna] = asignados[:, indice]
    return salida
