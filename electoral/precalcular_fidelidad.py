"""Precalcula el apoyo mínimo observado de las tres elecciones de 2024.

Ejecutar desde la raíz: python -m electoral.precalcular_fidelidad
Los Parquet resultantes son derivados locales; no se agregan al commit.
"""

from pathlib import Path

import pandas as pd

from electoral.config import (
    DIPUTACIONES_PARQUET, PRESIDENCIA_PARQUET, SENADURIAS_PARQUET,
)
from electoral.fidelidad import analizar_fidelidad


SALIDAS = {
    "estado": "fidelidad_estado.parquet",
    "nacional": "fidelidad_nacional.parquet",
}
COLUMNAS_PANTALLA = (
    "ID_SECCION", "ID_ESTADO", "partido", "piso_pct", "piso_votos",
    "rango_pp", "percentil_piso", "n_grupo", "clase", "volatil",
    "umbral_rango_pp", "primera_en_todas", "coalicion_distinta", "ambito",
)
LIMITE_BYTES = 50 * 1024 * 1024


def cargar_elecciones() -> dict[str, pd.DataFrame]:
    """Lee las tres tablas de secciones ya generadas."""
    return {
        "presidencia": pd.read_parquet(PRESIDENCIA_PARQUET),
        "diputaciones": pd.read_parquet(DIPUTACIONES_PARQUET),
        "senadurias": pd.read_parquet(SENADURIAS_PARQUET),
    }


def generar(destino: Path, elecciones: dict[str, pd.DataFrame]) -> dict[str, dict]:
    """Escribe ambos ámbitos; reduce a columnas visibles si exceden 50 MiB."""
    destino.mkdir(parents=True, exist_ok=True)
    salidas = {}
    for ambito, nombre in SALIDAS.items():
        tabla = analizar_fidelidad(elecciones, ambito=ambito)
        ruta = destino / nombre
        tabla.to_parquet(ruta, index=False, compression="zstd")
        salidas[ambito] = {"ruta": str(ruta), "filas": len(tabla), "columnas": list(tabla.columns)}
        del tabla
    total = sum((destino / nombre).stat().st_size for nombre in SALIDAS.values())
    if total > LIMITE_BYTES:
        for ambito, nombre in SALIDAS.items():
            ruta = destino / nombre
            tabla = pd.read_parquet(ruta, columns=list(COLUMNAS_PANTALLA))
            tabla.to_parquet(ruta, index=False, compression="zstd")
            salidas[ambito]["columnas"] = list(COLUMNAS_PANTALLA)
    for ambito, nombre in SALIDAS.items():
        salidas[ambito]["bytes"] = (destino / nombre).stat().st_size
    return salidas


if __name__ == "__main__":
    carpeta = Path(__file__).resolve().parents[1] / "data" / "electoral"
    for clave, detalle in generar(carpeta, cargar_elecciones()).items():
        print(clave, detalle)
