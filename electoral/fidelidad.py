"""Bloques base para medir voto consolidado por partido entre elecciones.

Este módulo NO fija la definición de "fidelidad". Calcula, por sección y
partido, el porcentaje de votos válidos de cada elección con el reparto de
coaliciones ``A_propios`` (partes iguales; el residuo entero va al integrante
con más votos propios) y resume su estabilidad entre elecciones. El umbral o
criterio que convierte estos números en "sección fiel" queda pendiente.
"""

from __future__ import annotations

import pandas as pd

from electoral.candidaturas import resolver_candidatura
from electoral.reparto import COALICIONES, repartir_coalicion

PARTIDOS = tuple(
    partido for grupo in COALICIONES.values() for partido in grupo["partidos"]
) + ("MC",)


def votos_por_partido(df: pd.DataFrame) -> pd.DataFrame:
    """Votos por partido y sección con coaliciones repartidas (A_propios).

    Solo filas ``con_resultado``; la llave ``ID_SECCION`` debe ser única.
    """
    d = df.loc[df["estado"].eq("con_resultado")]
    if d["ID_SECCION"].duplicated().any():
        raise ValueError("ID_SECCION duplicado entre filas con resultado")
    r = repartir_coalicion(d, "A_propios")
    salida = pd.DataFrame(index=r["ID_SECCION"].to_numpy())
    salida.index.name = "ID_SECCION"
    for partido in PARTIDOS:
        columna = "MC" if partido == "MC" else f"rep_{partido}"
        salida[partido] = r[columna].astype("int64").to_numpy()
    salida["VALIDOS"] = r["NUM_VOTOS_VALIDOS"].astype("int64").to_numpy()
    return salida


def porcentaje_por_partido(df: pd.DataFrame) -> pd.DataFrame:
    """Porcentaje de votos válidos por partido y sección (0-100)."""
    v = votos_por_partido(df)
    validos = v["VALIDOS"].where(v["VALIDOS"] > 0)
    return v[list(PARTIDOS)].div(validos, axis=0) * 100


def panel(elecciones: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Porcentajes en formato largo: ID_SECCION, partido, eleccion, pct, votos.

    Solo conserva secciones con resultado en todas las elecciones dadas.
    """
    if len(elecciones) < 2:
        raise ValueError("Se necesitan al menos dos elecciones")
    pcts = {n: porcentaje_por_partido(d) for n, d in elecciones.items()}
    votos = {n: votos_por_partido(d) for n, d in elecciones.items()}
    comunes = None
    for tabla in pcts.values():
        comunes = tabla.index if comunes is None else comunes.intersection(tabla.index)
    piezas = []
    for nombre in elecciones:
        p = pcts[nombre].loc[comunes].stack().rename("pct").reset_index()
        p.columns = ["ID_SECCION", "partido", "pct"]
        v = votos[nombre].loc[comunes, list(PARTIDOS)].stack().rename("votos").reset_index()
        v.columns = ["ID_SECCION", "partido", "votos"]
        p = p.merge(v, on=["ID_SECCION", "partido"])
        p["eleccion"] = nombre
        piezas.append(p)
    return pd.concat(piezas, ignore_index=True)


def estabilidad(largo: pd.DataFrame) -> pd.DataFrame:
    """Resumen por sección y partido entre elecciones.

    ``piso_pct`` y ``piso_votos`` son el mínimo observado entre elecciones: lo
    que el partido conserva en todas. ``rango_pp`` es máximo menos mínimo en
    puntos porcentuales. Son métricas candidatas, no una definición validada.
    """
    g = largo.groupby(["ID_SECCION", "partido"])
    salida = g["pct"].agg(
        media_pct="mean", desv_pct=lambda s: s.std(ddof=0), piso_pct="min", techo_pct="max"
    )
    salida["rango_pp"] = salida["techo_pct"] - salida["piso_pct"]
    salida["piso_votos"] = g["votos"].min()
    salida["n_elecciones"] = g["pct"].count()
    return salida.reset_index()


def _candidatura_primera(df: pd.DataFrame, partido: str) -> tuple[pd.Series, pd.Series]:
    """Victoria única de la candidatura activa y presencia en coalición."""
    columnas = [c for c in df if c.startswith("cand_")]
    votos = df[columnas].apply(pd.to_numeric, errors="coerce")
    activa = resolver_candidatura(df, partido)
    propios = pd.Series(float("nan"), index=df.index)
    for columna in activa.dropna().unique():
        mascara = activa.eq(columna)
        propios.loc[mascara] = votos.loc[mascara, columna]
    maximo = votos.max(axis=1)
    unica = votos.eq(maximo, axis=0).sum(axis=1).eq(1)
    primera = propios.eq(maximo) & unica
    coalicion = activa.isin(("cand_PAN_PRI_PRD", "cand_PVEM_PT_MORENA"))
    return primera, coalicion


def analizar_fidelidad(
    elecciones: dict[str, pd.DataFrame],
    ambito: str = "estado",
    ln_min: int = 100,
    pct_bastion: float = 90,
    pct_base: float = 75,
    k_tukey: float = 1.5,
) -> pd.DataFrame:
    """Clasificación provisional Scouter con reparto experimental ``A_propios``.

    Conserva solo secciones con resultado y lista nominal >= ``ln_min`` en
    todas las elecciones. El percentil es el rango promedio de pandas, 0-100,
    dentro de cada partido y ámbito. Una candidatura debe ganar sin empate en
    las tres elecciones para cumplir ``primera_en_todas``.
    """
    if ambito not in ("estado", "nacional"):
        raise ValueError("ambito debe ser 'estado' o 'nacional'")
    if set(elecciones) != {"presidencia", "diputaciones", "senadurias"}:
        raise ValueError("Se requieren presidencia, diputaciones y senadurias")
    filtradas = {
        nombre: df.loc[
            df["estado"].eq("con_resultado")
            & pd.to_numeric(df["LISTA_NOMINAL"], errors="coerce").ge(ln_min)
        ]
        for nombre, df in elecciones.items()
    }
    largo = panel(filtradas)
    salida = estabilidad(largo)
    salida["voto_duro_pct"] = salida["piso_pct"]
    estados = filtradas["presidencia"].set_index("ID_SECCION")["ID_ESTADO"]
    salida["ID_ESTADO"] = salida["ID_SECCION"].map(estados)

    comunes = set(salida["ID_SECCION"])
    primeras: dict[str, pd.Series] = {}
    coaliciones: dict[str, pd.Series] = {}
    for partido in PARTIDOS:
        victorias = []
        participa_coalicion = []
        for df in filtradas.values():
            d = df.loc[df["ID_SECCION"].isin(comunes)].set_index("ID_SECCION")
            primera, coalicion = _candidatura_primera(d, partido)
            victorias.append(primera)
            participa_coalicion.append(coalicion)
        primeras[partido] = pd.concat(victorias, axis=1).all(axis=1)
        c = pd.concat(participa_coalicion, axis=1)
        coaliciones[partido] = c.any(axis=1) & ~c.all(axis=1)
    claves = pd.MultiIndex.from_frame(salida[["ID_SECCION", "partido"]])
    primeras_largas = pd.concat(primeras, names=["partido", "ID_SECCION"])
    primeras_largas.index = primeras_largas.index.swaplevel()
    coaliciones_largas = pd.concat(coaliciones, names=["partido", "ID_SECCION"])
    coaliciones_largas.index = coaliciones_largas.index.swaplevel()
    salida["primera_en_todas"] = primeras_largas.reindex(claves).to_numpy(dtype=bool)
    salida["coalicion_distinta"] = coaliciones_largas.reindex(claves).to_numpy(dtype=bool)

    grupo = ["partido", "ID_ESTADO"] if ambito == "estado" else ["partido"]
    g = salida.groupby(grupo, sort=False)
    salida["n_grupo"] = g["piso_pct"].transform("size")
    salida["percentil_piso"] = g["piso_pct"].rank(method="average", pct=True) * 100
    q1 = g["rango_pp"].transform(lambda s: s.quantile(0.25))
    q3 = g["rango_pp"].transform(lambda s: s.quantile(0.75))
    salida["umbral_rango_pp"] = q3 + k_tukey * (q3 - q1)
    salida["volatil"] = salida["rango_pp"] > salida["umbral_rango_pp"]
    salida["clase"] = "Resto"
    salida.loc[salida["percentil_piso"].ge(pct_base), "clase"] = "Base fuerte"
    salida.loc[
        salida["percentil_piso"].ge(pct_bastion) & salida["primera_en_todas"],
        "clase",
    ] = "Bastión"
    salida["ambito"] = ambito
    return salida
