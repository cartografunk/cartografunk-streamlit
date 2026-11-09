"""Diagnóstico descriptivo por casilla IEEQ y CPV seccional 2020.

Las casillas B/C/E aportan votos propios. El CPV describe la sección y se
comparte entre sus casillas; los perfiles cuentan cada sección una vez por
clase. No se infiere el voto de grupos demográficos.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from electoral.cpv import ETIQUETAS
from electoral.reparto_ieeq import PARTIDOS_COMUNES, atribuir_partidos

CLASES = ("ganada_solida", "perdida_competitiva", "perdida_lejana")
ESTABLE = "sin_cambio_cartografico_referencia"
NOMBRES_CLASE = {"ganada_solida": "victoria sólida",
                 "perdida_competitiva": "derrota competitiva",
                 "perdida_lejana": "derrota lejana"}


def preparar_casillas(casillas: pd.DataFrame, cruce: pd.DataFrame,
                     cpv: pd.DataFrame, encarte: pd.DataFrame | None = None) -> pd.DataFrame:
    """Atribuye votos por partido y añade CPV sólo a perímetros comparables."""
    if cruce.ID_SECCION.duplicated().any() or cpv.ID_SECCION.duplicated().any():
        raise ValueError("ID_SECCION duplicado en cruce o CPV")
    base = casillas.loc[casillas.TIPO_NORMALIZADO.isin(("B", "C", "E"))
                        & casillas.INCLUIR_SECCION.eq(True)].copy()
    if base.empty:
        raise ValueError("No hay casillas B/C/E incluidas")
    if base.FILA_FUENTE.duplicated().any():
        raise ValueError("Fila de fuente IEEQ duplicada")
    if "CASILLA_ETIQUETA" not in base or base.duplicated(
        ["ID_DISTRITO_LOCAL", "ID_SECCION", "CASILLA_ETIQUETA"]
    ).any():
        raise ValueError("La etiqueta de casilla IEEQ falta o no es única")
    votos = atribuir_partidos(base, 2024)
    columnas = ["ID_SECCION", "FILA_FUENTE", "CASILLA_ETIQUETA", "ID_CASILLA",
                "TIPO_NORMALIZADO", "ID_DISTRITO_LOCAL"]
    salida = pd.concat([base[columnas].reset_index(drop=True),
                        votos.drop(columns="ID_SECCION").reset_index(drop=True)], axis=1)
    salida = salida.merge(cruce[["ID_SECCION", "CATEGORIA"]], on="ID_SECCION",
                          how="left", validate="many_to_one")
    if encarte is not None:
        lugar = encarte[["ID_SECCION", "CASILLA", "LOCALIDAD_INE", "LOCALIDAD_NOMBRE"]].rename(
            columns={"CASILLA": "CASILLA_ETIQUETA", "LOCALIDAD_INE": "LOCALIDAD_INE_INSTALACION",
                     "LOCALIDAD_NOMBRE": "LOCALIDAD_INSTALACION"})
        salida = salida.merge(lugar, on=["ID_SECCION", "CASILLA_ETIQUETA"], how="left",
                              validate="one_to_one", indicator="_encarte_cruce")
        if not salida._encarte_cruce.eq("both").all():
            raise ValueError("Hay casillas B/C/E sin clave en encarte 2024")
        salida = salida.drop(columns="_encarte_cruce")
    else:
        salida["LOCALIDAD_INE_INSTALACION"] = np.nan
        salida["LOCALIDAD_INSTALACION"] = pd.NA
    salida["CPV_COMPARABLE"] = salida.CATEGORIA.eq(ESTABLE)
    salida = salida.merge(cpv[["ID_SECCION", *ETIQUETAS]], on="ID_SECCION",
                          how="left", validate="many_to_one", indicator="_cpv_cruce")
    salida["CPV_COMPARABLE"] &= salida._cpv_cruce.eq("both")
    salida.loc[~salida.CPV_COMPARABLE, list(ETIQUETAS)] = np.nan
    salida = salida.drop(columns="_cpv_cruce")
    if not np.isclose(salida.LISTA_NOMINAL.sum(), base.LISTA_NOMINAL.sum()):
        raise ValueError("La lista nominal cambió durante el cruce")
    return salida


def evaluar_partido(casillas: pd.DataFrame, partido: str,
                    umbral_solida_pp: float = 10.0,
                    umbral_competitiva_pp: float = 10.0) -> pd.DataFrame:
    """Mide liderazgo *entre partidos atribuidos*, no victoria de candidatura."""
    if partido not in PARTIDOS_COMUNES:
        raise ValueError("Partido fuera del conjunto comparable")
    d = casillas.copy()
    otros = [p for p in PARTIDOS_COMUNES if p != partido]
    d["VOTOS_PARTIDO"] = d[partido]
    d["VOTOS_RIVAL"] = d[otros].max(axis=1)
    d["RIVAL"] = d[otros].idxmax(axis=1)
    d["VENTAJA_VOTOS"] = d.VOTOS_PARTIDO - d.VOTOS_RIVAL
    d["MARGEN_PP"] = 100 * d.VENTAJA_VOTOS / d.VOTOS_VALIDOS.where(d.VOTOS_VALIDOS.gt(0))
    d["CUOTA_PARTIDO_PCT"] = 100 * d.VOTOS_PARTIDO / d.VOTOS_VALIDOS.where(d.VOTOS_VALIDOS.gt(0))
    d["VOTOS_SOBRE_LISTA"] = d.TOTAL_VOTOS.gt(d.LISTA_NOMINAL)
    d["ABSTENCION"] = (d.LISTA_NOMINAL - d.TOTAL_VOTOS).where(~d.VOTOS_SOBRE_LISTA)
    d["VOTOS_PARA_LIDERAR"] = np.floor((-d.VENTAJA_VOTOS).clip(lower=0)) + 1
    d.loc[d.VENTAJA_VOTOS.gt(0), "VOTOS_PARA_LIDERAR"] = 0
    d["CLASE"] = "sin_resultado"
    valido = d.VOTOS_VALIDOS.gt(0) & d.MARGEN_PP.notna()
    d.loc[~valido, "VOTOS_PARA_LIDERAR"] = np.nan
    d["ALCANZABLE_ABSTENCION"] = d.VOTOS_PARA_LIDERAR.le(d.ABSTENCION) & d.VOTOS_PARA_LIDERAR.gt(0)
    d.loc[valido & d.MARGEN_PP.ge(umbral_solida_pp), "CLASE"] = "ganada_solida"
    d.loc[valido & d.MARGEN_PP.gt(0) & d.MARGEN_PP.lt(umbral_solida_pp), "CLASE"] = "ganada_ajustada"
    d.loc[valido & d.MARGEN_PP.eq(0), "CLASE"] = "empate"
    d.loc[valido & d.MARGEN_PP.lt(0) & d.MARGEN_PP.ge(-umbral_competitiva_pp), "CLASE"] = "perdida_competitiva"
    d.loc[valido & d.MARGEN_PP.lt(-umbral_competitiva_pp), "CLASE"] = "perdida_lejana"
    return d


def cobertura(casillas: pd.DataFrame) -> dict:
    """Cobertura de CPV comparable respecto de todas las B/C/E incluidas."""
    secciones = casillas.ID_SECCION.nunique()
    comparables = casillas.loc[casillas.CPV_COMPARABLE]
    nominal = float(casillas.LISTA_NOMINAL.sum())
    return {
        "casillas": len(casillas), "casillas_cpv": len(comparables),
        "secciones": secciones, "secciones_cpv": comparables.ID_SECCION.nunique(),
        "lista_nominal": nominal, "lista_nominal_cpv": float(comparables.LISTA_NOMINAL.sum()),
        "lista_nominal_pct": 100 * comparables.LISTA_NOMINAL.sum() / nominal if nominal else np.nan,
        "sin_cpv_por_clase": casillas.loc[~casillas.CPV_COMPARABLE].CLASE.value_counts().to_dict()
        if "CLASE" in casillas else {},
    }


def perfil_cpv(casillas: pd.DataFrame, referencia: str = "perdida_lejana",
               max_frases: int = 5) -> dict:
    """Contrasta 15 variables; una sección aporta una observación por clase."""
    if referencia not in CLASES:
        raise ValueError("Referencia inválida")
    base = casillas.loc[casillas.CPV_COMPARABLE & casillas.CLASE.isin(CLASES),
                        ["ID_SECCION", "CLASE", *ETIQUETAS]].drop_duplicates(["ID_SECCION", "CLASE"])
    filas = []
    for variable, etiqueta in ETIQUETAS.items():
        grupos = {clase: pd.to_numeric(base.loc[base.CLASE.eq(clase), variable], errors="coerce").dropna()
                  for clase in CLASES}
        fila = {"variable": variable, "etiqueta": etiqueta}
        for clase, valores in grupos.items():
            fila[f"media_{clase}"] = float(valores.mean()) if len(valores) else np.nan
            fila[f"n_secciones_{clase}"] = len(valores)
        for clase in CLASES:
            if clase == referencia:
                continue
            a, b = grupos[clase], grupos[referencia]
            var = (((len(a)-1)*a.var(ddof=1)+(len(b)-1)*b.var(ddof=1))/(len(a)+len(b)-2)
                   if len(a) >= 2 and len(b) >= 2 else np.nan)
            fila[f"dif_est_{clase}_vs_{referencia}"] = (
                float((a.mean()-b.mean())/np.sqrt(var)) if pd.notna(var) and var > 0 else np.nan)
        filas.append(fila)
    tabla = pd.DataFrame(filas)
    frases = []
    for clase in (c for c in CLASES if c != referencia):
        col = f"dif_est_{clase}_vs_{referencia}"
        for _, fila in tabla.assign(magnitud=tabla[col].abs()).nlargest(max_frases, "magnitud").iterrows():
            if pd.notna(fila[col]):
                direccion = "mayor" if fila[col] > 0 else "menor"
                frases.append(f"En casillas de «{NOMBRES_CLASE[clase]}», las secciones tienen una proporción "
                              f"{direccion} de {fila.etiqueta.lower()} que en «{NOMBRES_CLASE[referencia]}».")
    return {"tabla": tabla, "frases": frases,
            "n_secciones_por_clase": base.groupby("CLASE").ID_SECCION.nunique().to_dict(),
            "n_secciones_en_varias_clases": int(base.ID_SECCION.duplicated().sum())}


def proponer_esfuerzo(casillas: pd.DataFrame) -> pd.DataFrame:
    """Hipótesis operativa descriptiva; no estima votos ganables ni retorno."""
    d = casillas.copy()
    d["ACCION_HIPOTESIS"] = "Revisar datos"
    d.loc[d.CLASE.eq("ganada_solida"), "ACCION_HIPOTESIS"] = "Presencia ligera y conservación"
    d.loc[d.CLASE.eq("ganada_ajustada"), "ACCION_HIPOTESIS"] = "Defender ventaja cercana"
    d.loc[d.CLASE.eq("perdida_competitiva") & d.ALCANZABLE_ABSTENCION,
          "ACCION_HIPOTESIS"] = "Probar movilización focalizada"
    d.loc[d.CLASE.eq("perdida_competitiva") & ~d.ALCANZABLE_ABSTENCION,
          "ACCION_HIPOTESIS"] = "Investigar persuasión y barreras"
    d.loc[d.CLASE.eq("perdida_lejana"), "ACCION_HIPOTESIS"] = "Observar antes de invertir"
    d.loc[d.CLASE.eq("empate"), "ACCION_HIPOTESIS"] = "Definir meta mínima y defender"
    d.loc[d.VOTOS_SOBRE_LISTA, "ACCION_HIPOTESIS"] = "Revisar votos sobre lista"
    return d


def incorporar_apoyo_minimo(casillas: pd.DataFrame, apoyo: pd.DataFrame,
                            partido: str) -> pd.DataFrame:
    """Añade el menor porcentaje federal 2024 observado en la sección."""
    piso = apoyo.loc[apoyo.partido.eq(partido), ["ID_SECCION", "piso_pct"]]
    if piso.ID_SECCION.duplicated().any():
        raise ValueError("Apoyo mínimo duplicado por sección y partido")
    return casillas.merge(piso.rename(columns={"piso_pct": "APOYO_MINIMO_FEDERAL_2024_PCT"}),
                          on="ID_SECCION", how="left", validate="many_to_one")


def costo_hipotetico(casillas: pd.DataFrame, costo_por_voto: float) -> pd.DataFrame:
    """Multiplica la distancia al liderazgo por un supuesto del usuario."""
    if not np.isfinite(costo_por_voto) or costo_por_voto < 0:
        raise ValueError("El costo supuesto debe ser finito y no negativo")
    d = casillas.copy()
    d["COSTO_SUPUESTO_POR_VOTO"] = float(costo_por_voto)
    d["COSTO_HIPOTETICO"] = (d.VOTOS_PARA_LIDERAR * costo_por_voto).where(
        d.VOTOS_PARA_LIDERAR.gt(0) & ~d.VOTOS_SOBRE_LISTA)
    return d


def lista_revision(casillas: pd.DataFrame, presupuesto: float | None = None) -> pd.DataFrame:
    """Selecciona casos para revisión de campo con reglas visibles, sin estimar retorno.

    La selección compara partidos atribuidos, no candidaturas MR. El presupuesto
    opcional sólo contrasta un costo supuesto; no pronostica votos captables.
    """
    if presupuesto is not None and (not np.isfinite(presupuesto) or presupuesto < 0):
        raise ValueError("El presupuesto supuesto debe ser finito y no negativo")
    d = casillas.copy()
    if d.duplicated(["ID_SECCION", "CASILLA_ETIQUETA"]).any():
        raise ValueError("Casilla duplicada en lista de revisión")
    competitiva = d.CLASE.eq("perdida_competitiva")
    defensa = d.CLASE.eq("ganada_ajustada")
    d["TIPO_REVISION"] = ""
    d.loc[competitiva & d.ALCANZABLE_ABSTENCION, "TIPO_REVISION"] = "Examinar pérdida cercana"
    d.loc[competitiva & ~d.ALCANZABLE_ABSTENCION, "TIPO_REVISION"] = "Examinar barreras"
    d.loc[defensa, "TIPO_REVISION"] = "Defender ventaja cercana"
    d.loc[d.CLASE.eq("empate"), "TIPO_REVISION"] = "Examinar empate"
    d.loc[d.VOTOS_SOBRE_LISTA, "TIPO_REVISION"] = "Revisar dato electoral"
    d["MOTIVO_REVISION"] = ""
    d.loc[competitiva & d.ALCANZABLE_ABSTENCION, "MOTIVO_REVISION"] = (
        "Distancia partidaria menor o igual a la abstención observada; comprobar en campo.")
    d.loc[competitiva & ~d.ALCANZABLE_ABSTENCION, "MOTIVO_REVISION"] = (
        "Pérdida partidaria cercana; la abstención registrada no cubre la distancia.")
    d.loc[defensa, "MOTIVO_REVISION"] = (
        "Ventaja partidaria menor de 10 pp; revisar cómo conservar apoyo.")
    d.loc[d.CLASE.eq("empate"), "MOTIVO_REVISION"] = (
        "Empate partidario observado; revisar votos y definir una meta mínima.")
    d.loc[d.VOTOS_SOBRE_LISTA, "MOTIVO_REVISION"] = (
        "Votos sobre lista nominal: revisar antes de planear esfuerzo.")
    d["DENTRO_PRESUPUESTO_SUPUESTO"] = pd.NA
    if presupuesto is not None and "COSTO_HIPOTETICO" in d:
        valido = d.COSTO_HIPOTETICO.notna() & ~d.VOTOS_SOBRE_LISTA
        d.loc[valido, "DENTRO_PRESUPUESTO_SUPUESTO"] = d.loc[valido, "COSTO_HIPOTETICO"].le(presupuesto)
    orden = {"Examinar pérdida cercana": 0, "Examinar empate": 1,
             "Defender ventaja cercana": 2, "Examinar barreras": 3,
             "Revisar dato electoral": 4}
    d = d.loc[d.TIPO_REVISION.ne("")].copy()
    d["_orden"] = d.TIPO_REVISION.map(orden)
    return d.sort_values(["_orden", "ID_SECCION", "CASILLA_ETIQUETA"]).drop(columns="_orden")
