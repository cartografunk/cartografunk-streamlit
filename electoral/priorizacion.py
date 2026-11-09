"""Cuentas de costo y capacidad para un escenario de movilización, sin pronóstico."""

import pandas as pd


def preparar_priorizacion(secciones: pd.DataFrame, costo_por_voto: float) -> pd.DataFrame:
    """Copia pérdidas y empates con abstención positiva y sin exceso de votos."""
    if costo_por_voto < 0:
        raise ValueError("El costo por voto debe ser no negativo")
    d = secciones.loc[
        secciones["resultado"].isin(("perdida", "empate"))
        & secciones["abstencion"].gt(0)
        & secciones["votos_sobre_lista"].eq(False),
        ["ID_SECCION", "MUNICIPIO", "ID_DISTRITO_FEDERAL", "votos_para_ganar", "abstencion"],
    ].copy()
    d["costo_por_voto"] = float(costo_por_voto)
    d["descartar"] = False
    return calcular_costos(d)


def calcular_costos(tabla: pd.DataFrame) -> pd.DataFrame:
    """Recalcula el costo a partir de los importes editados por sección."""
    d = tabla.copy()
    d["costo_por_voto"] = pd.to_numeric(d["costo_por_voto"], errors="raise")
    if d["costo_por_voto"].isna().any() or d["costo_por_voto"].lt(0).any():
        raise ValueError("Cada costo por voto debe ser no negativo y no vacío")
    d["costo_estimado"] = d["votos_para_ganar"] * d["costo_por_voto"]
    return d


def presupuestar(tabla: pd.DataFrame, presupuesto: float) -> tuple[pd.DataFrame, float]:
    """Marca filas que caben en el presupuesto, de menor a mayor costo."""
    if presupuesto < 0:
        raise ValueError("El presupuesto debe ser no negativo")
    d = calcular_costos(tabla)
    d["seleccionada"] = False
    activas = d.loc[~d["descartar"].astype(bool)].sort_values(
        ["costo_estimado", "ID_SECCION"], kind="stable"
    )
    acumulado = activas["costo_estimado"].cumsum()
    elegidas = activas.index[acumulado.le(presupuesto)]
    d.loc[elegidas, "seleccionada"] = True
    return d, float(d.loc[d["seleccionada"], "costo_estimado"].sum())


def meta_distrital(distritos: pd.DataFrame, distrito: int) -> int | None:
    """Faltante agregado más uno; None si el distrito ya está ganado."""
    fila = distritos.loc[distritos["ID_DISTRITO_FEDERAL"].eq(distrito)]
    if len(fila) != 1:
        raise ValueError(f"Distrito ausente o duplicado: {distrito}")
    faltante = fila["faltante_votos"].iloc[0]
    return int(faltante) + 1 if pd.notna(faltante) else None


def cubrir_meta(tabla: pd.DataFrame, distrito: int, meta: int) -> tuple[int | None, float]:
    """Cuenta secciones activas por costo hasta cubrir la meta de capacidad."""
    if meta <= 0:
        raise ValueError("La meta debe ser positiva")
    d = calcular_costos(tabla)
    activas = d.loc[
        d["ID_DISTRITO_FEDERAL"].eq(distrito) & ~d["descartar"].astype(bool)
    ].sort_values(["costo_estimado", "ID_SECCION"], kind="stable")
    capacidad = activas["abstencion"].clip(lower=0)
    total = float(capacidad.sum())
    if total < meta:
        return None, total
    return int(capacidad.cumsum().lt(meta).sum()) + 1, total
