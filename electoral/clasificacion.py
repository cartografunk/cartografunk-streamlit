"""Clasificación de rentabilidad de candidaturas por sección."""

from dataclasses import dataclass

import numpy as np
import pandas as pd


CLASES = (
    "ganada_solida",
    "ganada_ajustada",
    "empate",
    "perdida_competitiva",
    "perdida_intermedia",
    "perdida_lejana",
)


@dataclass(frozen=True)
class Umbrales:
    solida_pp: float = 15.0
    competitiva_pp: float = 5.0
    lejana_pp: float = 15.0
    votos_alcanzables: int = 100

    def __post_init__(self) -> None:
        valores = (
            self.solida_pp,
            self.competitiva_pp,
            self.lejana_pp,
            self.votos_alcanzables,
        )
        if any(not valor > 0 for valor in valores):
            raise ValueError("Todos los umbrales deben ser mayores que cero")
        if self.competitiva_pp > self.lejana_pp:
            raise ValueError("competitiva_pp no puede superar lejana_pp")


def clasificar(df: pd.DataFrame, umbrales: Umbrales = Umbrales()) -> pd.DataFrame:
    """Agrega clases y alcances sin modificar la salida de rentabilidad."""
    d = df.copy()
    con_resultado = d["estado"].eq("con_resultado")
    ganada = con_resultado & d["resultado"].eq("ganada") & d["margen_pct"].notna()
    con_faltante = con_resultado & d["faltante_pct"].notna()
    empate = con_faltante & d["resultado"].eq("empate")
    perdida = con_faltante & d["resultado"].eq("perdida")

    condiciones = (
        ganada & d["margen_pct"].ge(umbrales.solida_pp),
        ganada & d["margen_pct"].lt(umbrales.solida_pp),
        empate,
        perdida & d["faltante_pct"].lt(umbrales.competitiva_pp),
        perdida & d["faltante_pct"].ge(umbrales.competitiva_pp) & d["faltante_pct"].lt(umbrales.lejana_pp),
        perdida & d["faltante_pct"].ge(umbrales.lejana_pp),
    )
    d["clase"] = pd.Categorical(
        np.select(condiciones, CLASES, default=None), categories=CLASES, ordered=True
    )

    elegible = con_resultado & d["resultado"].isin(("perdida", "empate"))
    abstencion_util = (
        elegible
        & d["abstencion"].gt(0)
        & d["votos_sobre_lista"].eq(False).fillna(False)
        & d["rescatable_vs_abst"].notna()
    )
    d["alcanzable_por_abstencion"] = pd.Series(pd.NA, index=d.index, dtype="boolean")
    d.loc[abstencion_util, "alcanzable_por_abstencion"] = d.loc[
        abstencion_util, "rescatable_vs_abst"
    ].le(1)

    votos_disponibles = elegible & d["votos_para_ganar"].notna()
    d["alcanzable_en_votos"] = pd.Series(pd.NA, index=d.index, dtype="boolean")
    d.loc[votos_disponibles, "alcanzable_en_votos"] = d.loc[
        votos_disponibles, "votos_para_ganar"
    ].le(umbrales.votos_alcanzables)
    return d
