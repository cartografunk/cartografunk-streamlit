"""Comparaciones de secciones: CPV 2020 vs votos 2024; asociación, no causa."""

from __future__ import annotations

import numpy as np
import pandas as pd

from electoral.cpv import ETIQUETAS

OBJETIVOS = {"ventaja_firmada", "faltante_pct", "alcanzable_por_abstencion", "piso_pct"}
NOMBRES_CLASE = {
    "ganada_solida": "Victoria sólida", "perdida_competitiva": "Derrota competitiva",
    "perdida_lejana": "Derrota lejana", "Bastión": "Bastión",
    "Base fuerte": "Base fuerte", "Resto": "Resto",
}


def piso_candidatura(elecciones: dict[str, pd.DataFrame], candidatura: str) -> pd.DataFrame:
    """Mínimo de la misma candidatura activa en las tres boletas de 2024."""
    if set(elecciones) != {"presidencia", "diputaciones", "senadurias"}:
        raise ValueError("Se requieren las tres elecciones de 2024")
    piezas = []
    for nombre, df in elecciones.items():
        if candidatura not in df:
            return pd.DataFrame(columns=["ID_SECCION", "ID_ESTADO", "piso_pct"])
        validos = pd.to_numeric(df.NUM_VOTOS_VALIDOS, errors="coerce")
        votos = pd.to_numeric(df[candidatura], errors="coerce")
        pct = (100 * votos / validos.where(validos.gt(0))).where(df.estado.eq("con_resultado"))
        piezas.append(df[["ID_SECCION", "ID_ESTADO"]].assign(**{nombre: pct}))
    salida = piezas[0]
    for pieza in piezas[1:]:
        salida = salida.merge(pieza.drop(columns="ID_ESTADO"), on="ID_SECCION", validate="one_to_one")
    salida["piso_pct"] = salida[list(elecciones)].min(axis=1, skipna=False)
    return salida[["ID_SECCION", "ID_ESTADO", "piso_pct"]]


def ventaja_firmada(resultados: pd.DataFrame) -> pd.Series:
    """Margen en victoria, menos faltante en derrota, cero en empate."""
    valor = pd.Series(np.nan, index=resultados.index, dtype=float)
    valor.loc[resultados.resultado.eq("ganada")] = pd.to_numeric(resultados.margen_pct, errors="coerce")
    valor.loc[resultados.resultado.eq("perdida")] = -pd.to_numeric(resultados.faltante_pct, errors="coerce")
    valor.loc[resultados.resultado.eq("empate")] = 0.0
    return valor.where(resultados.estado.eq("con_resultado"))


def _muestra(resultados: pd.DataFrame, censo: pd.DataFrame, estado: int,
             columnas: list[str]) -> pd.DataFrame:
    if resultados.ID_SECCION.duplicated().any() or censo.ID_SECCION.duplicated().any():
        raise ValueError("ID_SECCION debe ser único")
    return resultados.loc[resultados.ID_ESTADO.eq(estado)].merge(
        censo[["ID_SECCION", *columnas]], on="ID_SECCION", how="inner", validate="one_to_one")


def perfil_clases(resultados: pd.DataFrame, censo: pd.DataFrame, estado: int,
                  clases: tuple[str, str, str], referencia: str,
                  max_frases: int = 5) -> dict:
    """Medias y diferencias estandarizadas entre clases de secciones.

    Cada diferencia usa la desviación combinada de las dos clases comparadas.
    Cada variable usa sus casos disponibles; no se imputan datos CPV.
    """
    if referencia not in clases or len(set(clases)) != 3:
        raise ValueError("Se requieren tres clases distintas y una referencia incluida")
    columnas = list(ETIQUETAS)
    if not set(columnas).issubset(censo):
        raise ValueError("Faltan variables CPV")
    base = _muestra(resultados, censo, estado, columnas)
    base = base.loc[base.clase.astype(str).isin(clases)].copy()
    filas = []
    for nombre in columnas:
        valores = pd.to_numeric(base[nombre], errors="coerce")
        grupos = {clase: valores[base.clase.astype(str).eq(clase)].dropna() for clase in clases}
        fila = {"variable": nombre, "etiqueta": ETIQUETAS[nombre]}
        for clase, grupo in grupos.items():
            fila[f"media_{clase}"] = float(grupo.mean()) if len(grupo) else np.nan
            fila[f"n_{clase}"] = len(grupo)
        for clase in clases:
            if clase == referencia:
                continue
            a, b = grupos[clase], grupos[referencia]
            if len(a) < 2 or len(b) < 2:
                diferencia = np.nan
            else:
                var = ((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (len(a) + len(b) - 2)
                diferencia = (a.mean() - b.mean()) / np.sqrt(var) if var > 0 else np.nan
            fila[f"dif_est_{clase}_vs_{referencia}"] = float(diferencia)
        filas.append(fila)
    tabla = pd.DataFrame(filas)
    frases = []
    for clase in (c for c in clases if c != referencia):
        col = f"dif_est_{clase}_vs_{referencia}"
        orden = tabla.assign(magnitud=tabla[col].abs()).sort_values("magnitud", ascending=False).head(max_frases)
        for _, fila in orden.iterrows():
            if pd.notna(fila[col]):
                direccion = "mayor" if fila[col] > 0 else "menor"
                frases.append(
                    f"Las secciones de «{NOMBRES_CLASE.get(clase, clase)}» tienen una proporción "
                    f"{direccion} de {fila['etiqueta'].lower()} que las de «{NOMBRES_CLASE.get(referencia, referencia)}»."
                )
    return {"tabla": tabla, "frases": frases,
            "n_por_clase": {clase: int(base.clase.astype(str).eq(clase).sum()) for clase in clases}}


def explicar(resultados: pd.DataFrame, censo: pd.DataFrame, candidatura: str,
             estado: int, objetivo: str = "ventaja_firmada") -> dict:
    """Correlación y regresión ridge estandarizada para el panel Avanzado.

    Faltante y alcanzabilidad usan exclusivamente derrotas. Alcanzabilidad
    es binaria (0/1); su regresión expresa asociación lineal descriptiva.
    """
    if objetivo not in OBJETIVOS:
        raise ValueError("Objetivo desconocido")
    if objetivo != "piso_pct" and candidatura not in resultados:
        raise ValueError("Candidatura ausente")
    columnas = [c for c in ETIQUETAS if c in censo]
    base = _muestra(resultados, censo, estado, columnas)
    if objetivo == "ventaja_firmada":
        base[objetivo] = ventaja_firmada(base)
    elif objetivo in {"faltante_pct", "alcanzable_por_abstencion"}:
        base = base.loc[base.resultado.eq("perdida")].copy()
    base[objetivo] = pd.to_numeric(base[objetivo], errors="coerce")
    base = base.dropna(subset=[objetivo])
    utiles = []
    for columna in columnas:
        base[columna] = pd.to_numeric(base[columna], errors="coerce")
        if base[columna].notna().sum() >= 20 and base[columna].std() > 0:
            utiles.append(columna)
    completa = base[[objetivo, *utiles]].dropna()
    if len(completa) < 30 or not utiles:
        return {"objetivo": objetivo, "n": len(completa), "variables": [], "nota": "Datos insuficientes."}
    utiles = [c for c in utiles if completa[c].std(ddof=0) > 0]
    x = completa[utiles].to_numpy(dtype=float)
    y = completa[objetivo].to_numpy(dtype=float)
    if not utiles or np.std(y) == 0:
        return {"objetivo": objetivo, "n": len(y), "variables": [], "nota": "El resultado no varía."}
    x = (x - x.mean(axis=0)) / x.std(axis=0)
    y = (y - y.mean()) / y.std()
    correlaciones = (x * y[:, None]).mean(axis=0)
    beta = np.linalg.solve(x.T @ x + 0.1 * len(y) * np.eye(len(utiles)), x.T @ y)
    variables = [{"variable": nombre, "etiqueta": ETIQUETAS[nombre],
                  "correlacion": float(correlaciones[i]), "beta_estandarizada": float(beta[i])}
                 for i, nombre in enumerate(utiles)]
    return {"objetivo": objetivo, "n": len(y), "variables": variables,
            "nota": "asociación, no causa"}
