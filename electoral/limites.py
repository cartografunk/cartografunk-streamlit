"""Capas de referencia de entidad y municipios para el mapa electoral."""

import json

import geopandas as gpd


def limites_estado(
    entidades: gpd.GeoDataFrame, municipios: gpd.GeoDataFrame, estado: int
) -> tuple[dict, dict, tuple[float, float], int]:
    """Devuelve los límites en WGS84 y una posición interior para la etiqueta."""
    if entidades.crs is None or municipios.crs is None:
        raise ValueError("Las capas de límites deben declarar CRS")
    clave = f"{int(estado):02d}"
    entidad = entidades.loc[entidades["cvegeo"].astype(str).eq(clave), ["cvegeo", "geometry"]]
    municipales = municipios.loc[
        municipios["cvegeo"].astype(str).str.startswith(clave), ["cvegeo", "geometry"]
    ]
    if len(entidad) != 1 or municipales.empty:
        raise ValueError(f"Límites ausentes o duplicados para entidad {clave}")
    if entidad.crs.to_epsg() != 4326:
        entidad = entidad.to_crs(4326)
    if municipales.crs.to_epsg() != 4326:
        municipales = municipales.to_crs(4326)
    punto = entidad.geometry.iloc[0].representative_point()
    return (
        json.loads(entidad.to_json(drop_id=True)),
        json.loads(municipales.to_json(drop_id=True)),
        (float(punto.x), float(punto.y)),
        len(municipales),
    )
