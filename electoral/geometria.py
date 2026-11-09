"""Geometría de secciones del MGE 2024."""

from pathlib import Path

import geopandas as gpd

from electoral.config import GEOMETRIA_TOLERANCIA_M


COLUMNAS = ("ID_SECCION", "ENTIDAD", "DISTRITO", "DISTRITO_L", "MUNICIPIO", "TIPO", "geometry")


def _preparar_geometria(origen: gpd.GeoDataFrame, tolerancia_m: float) -> gpd.GeoDataFrame:
    if tolerancia_m < 0:
        raise ValueError("La tolerancia debe ser mayor o igual que cero")
    metros = origen.set_crs(32614, allow_override=True)
    if tolerancia_m > 0:
        metros = metros.set_geometry(metros.geometry.simplify(tolerancia_m, preserve_topology=True))
    final = metros.to_crs(4326)
    final["ID_SECCION"] = (
        final["ENTIDAD"].astype("int64").astype(str).str.zfill(2)
        + "-"
        + final["SECCION"].astype("int64").astype(str).str.zfill(4)
    )
    return final[list(COLUMNAS)]


def cargar_geometria(gpkg_path: str | Path, tolerancia_m: float = GEOMETRIA_TOLERANCIA_M) -> gpd.GeoDataFrame:
    """Lee la capa, interpreta sus metros como EPSG:32614 y devuelve EPSG:4326."""
    origen = gpd.read_file(gpkg_path, layer="SECCIONES_2024")
    return _preparar_geometria(origen, tolerancia_m)
