"""Margen de candidatura local MR 2024 a partir de opciones de voto IEEQ."""

from __future__ import annotations

import pandas as pd

from electoral.reparto_ieeq import COMBINACIONES, INDEPENDIENTES, PARTIDOS_COMUNES, PROPIOS


PARTICIPANTE_PARTIDOS = {
    1: ("PAN",), 2: ("PRI",), 3: ("PRD",), 4: ("MC",),
    5: ("PVEM",), 6: ("MORENA",), 7: ("PT",), 8: ("QS",),
    18: ("PVEM", "MORENA", "PT"), 21: ("MORENA", "PT"),
    22: ("PAN", "PRI", "PRD"), 23: ("PAN", "PRI"), 24: ("PAN", "PRD"),
}


def margenes_candidatura(secciones: pd.DataFrame, distritos: pd.DataFrame,
                        candidaturas: dict[int, list[dict]]) -> pd.DataFrame:
    """Suma marcas propias y combinadas al candidato activo de cada distrito.

    Una opción con votos debe pertenecer a una sola candidatura. Los márgenes
    son contra la candidatura rival más votada, no contra otro partido.
    """
    if secciones.ID_SECCION.duplicated().any() or distritos.ID_SECCION.duplicated().any():
        raise ValueError("ID_SECCION duplicado")
    base = secciones.merge(distritos[["ID_SECCION", "ID_DISTRITO_LOCAL"]],
                          on="ID_SECCION", validate="one_to_one")
    if len(base) != len(secciones):
        raise ValueError("Falta distrito local para alguna sección")
    columnas = {p: (p,) for p in PROPIOS[2024]} | COMBINACIONES[2024]
    if not set(columnas).issubset(base):
        raise ValueError("Faltan opciones de voto IEEQ")
    filas = []
    for _, row in base.iterrows():
        votos = row.to_dict()
        distrito = int(votos["ID_DISTRITO_LOCAL"])
        if distrito not in candidaturas:
            raise ValueError(f"Faltan candidaturas del distrito {distrito}")
        inscritos = candidaturas[distrito]
        grupos = {int(c["id_participante"]): set(PARTICIPANTE_PARTIDOS[int(c["id_participante"])])
                  for c in inscritos}
        totales = {cid: 0.0 for cid in grupos}
        for opcion, miembros in columnas.items():
            valor = float(votos[opcion])
            if valor == 0:
                continue
            destino = [cid for cid, grupo in grupos.items() if set(miembros).issubset(grupo)]
            if len(destino) != 1:
                raise ValueError(f"Opción {opcion} con votos sin candidatura única en distrito {distrito}")
            totales[destino[0]] += valor
        if any(float(votos[p]) != 0 for p in INDEPENDIENTES[2024]):
            raise ValueError("Candidatura independiente con votos sin mapeo")
        validos = float(votos["TOTAL_VOTOS"] - votos["NULOS"] - votos["NO_REGISTRADAS"])
        if abs(sum(totales.values()) - validos) > 1e-7:
            raise ValueError("Los votos por candidatura no conservan el total válido")
        for partido in PARTIDOS_COMUNES:
            destino = [cid for cid, grupo in grupos.items() if partido in grupo]
            if len(destino) != 1:
                raise ValueError(f"Partido {partido} sin candidatura única en distrito {distrito}")
            cid = destino[0]
            rival = max(v for other, v in totales.items() if other != cid)
            filas.append({"ID_SECCION": votos["ID_SECCION"], "PARTIDO": partido,
                          "ID_DISTRITO_LOCAL": distrito, "ID_CANDIDATURA": cid,
                          "VOTOS_CANDIDATURA": totales[cid], "VOTOS_RIVAL_CANDIDATURA": rival,
                          "MARGEN_CANDIDATURA_PP": 100 * (totales[cid] - rival) / validos
                          if validos > 0 else float("nan")})
    return pd.DataFrame(filas)
