"""Agregados territoriales de resultados y rentabilidad electoral."""

import pandas as pd

from electoral.clasificacion import CLASES, Umbrales, clasificar
from electoral.rentabilidad import rentabilidad
from electoral.rentabilidad_partido import rentabilidad_partido


CLAVES = {
    "pais": (),
    "distrito": ("ID_ESTADO", "ID_DISTRITO_FEDERAL"),
    "municipio": ("ID_ESTADO", "ID_MUNICIPIO", "MUNICIPIO"),
    "estado": ("ID_ESTADO",),
}


def agregar(
    df: pd.DataFrame,
    nivel: str,
    candidaturas: list[str] | tuple[str, ...],
    evaluar: str,
    umbrales: Umbrales = Umbrales(),
    partido: str | None = None,
) -> pd.DataFrame:
    """Suma secciones terrestres y recalcula el ranking sobre cada suma."""
    if nivel not in CLAVES:
        raise ValueError(f"Nivel desconocido: {nivel}")
    claves = list(CLAVES[nivel])
    candidaturas = list(candidaturas)
    territoriales = df.copy() if nivel == "pais" else df.loc[df["estado"].ne("extranjero")].copy()
    if nivel == "pais":
        territoriales["__pais"] = "México"
        claves = ["__pais"]
    con_resultado = territoriales.loc[territoriales["estado"].eq("con_resultado")]
    para_sumas = territoriales.loc[territoriales["estado"].isin(("con_resultado", "extranjero"))] if nivel == "pais" else con_resultado

    grupos = territoriales.groupby(claves, dropna=False, sort=True)
    conteos = grupos["estado"].agg(
        n_secciones="size",
        n_con_resultado=lambda s: s.eq("con_resultado").sum(),
        n_sin_resultado=lambda s: s.eq("sin_resultado").sum(),
    ).reset_index()

    sumables = [*candidaturas, "NUM_VOTOS_VALIDOS", "TOTAL_VOTOS", "LISTA_NOMINAL"]
    sumables = list(dict.fromkeys(sumables))
    votadas = para_sumas[claves + sumables].copy()
    for clase in CLASES:
        votadas[f"n_{clase}"] = para_sumas["clase"].eq(clase).astype("int64")
    votadas["votos_para_ganar_perdida_competitiva"] = para_sumas[
        "votos_para_ganar"
    ].where(para_sumas["clase"].eq("perdida_competitiva"), 0).fillna(0)
    votadas["n_votos_sobre_lista"] = para_sumas["votos_sobre_lista"].eq(True).fillna(False).astype("int64")
    columnas_suma = votadas.columns.difference(claves).tolist()
    sumas = votadas.groupby(claves, dropna=False, sort=True)[columnas_suma].sum(min_count=1 if partido else 0).reset_index()

    agregado = conteos.merge(sumas, on=claves, how="left", validate="one_to_one")
    rellenar = [columna for columna in columnas_suma if not (partido and columna.startswith("cand_"))]
    agregado[rellenar] = agregado[rellenar].fillna(0)
    for columna in [f"n_{clase}" for clase in CLASES] + ["n_votos_sobre_lista"]:
        agregado[columna] = agregado[columna].astype("int64")
    agregado["estado"] = "con_resultado"
    resultado = (rentabilidad_partido(agregado, partido, umbrales) if partido
                 else clasificar(rentabilidad(agregado, candidaturas, evaluar), umbrales))
    return resultado.rename(columns={"__pais": "pais"}) if nivel == "pais" else resultado
