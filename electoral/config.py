"""Rutas de entrada y definiciones de candidaturas de 2024."""

from pathlib import Path


PRESIDENCIA_ZIP = Path(
    r"D:\(5) WORK\CONJUNTOS DE DATOS\INE_SICEE\FEDERALES_2024\PRESIDENCIA_2024.zip"
)
DIPUTACIONES_ZIP = Path(
    r"D:\(5) WORK\CONJUNTOS DE DATOS\INE_SICEE\FEDERALES_2024\DIPUTACIONES_FED_MR_2024.zip"
)
SENADURIAS_ZIP = Path(
    r"D:\(5) WORK\CONJUNTOS DE DATOS\INE_SICEE\FEDERALES_2024\SENADURÍAS_MR_2024.zip"
)
MGE_ZIP = Path(r"D:\(5) WORK\CONJUNTOS DE DATOS\INE MGE\MGE 2024-20240515T221823Z-001.zip")
GEOMETRIA_TOLERANCIA_M = 25.0
GEOMETRIA_PARQUET = (
    Path(__file__).resolve().parents[1] / "data" / "electoral" / "secciones_2024_geom.parquet"
)
ENTIDADES_VISUAL_PARQUET = (
    Path(__file__).resolve().parents[1] / "data" / "geometria" / "estatal.parquet"
)
MUNICIPIOS_VISUAL_PARQUET = (
    Path(__file__).resolve().parents[1] / "data" / "geometria" / "municipal_visual_500m.parquet"
)
PRESIDENCIA_PARQUET = (
    Path(__file__).resolve().parents[1] / "data" / "electoral" / "presidencia_2024_seccion.parquet"
)
DIPUTACIONES_PARQUET = (
    Path(__file__).resolve().parents[1] / "data" / "electoral" / "diputaciones_2024_seccion.parquet"
)
SENADURIAS_PARQUET = (
    Path(__file__).resolve().parents[1] / "data" / "electoral" / "senadurias_2024_seccion.parquet"
)

CANDIDATURAS = {
    "PAN_PRI_PRD": ("PAN", "PRI", "PRD", "PAN_PRI_PRD", "PAN_PRI", "PAN_PRD", "PRI_PRD"),
    "PVEM_PT_MORENA": (
        "PVEM", "PT", "MORENA", "PVEM_PT_MORENA", "PVEM_PT", "PVEM_MORENA", "PT_MORENA"
    ),
    "MC": ("MC",),
}

NOTAS_CALIDAD_DEMO = (
    "56 secciones sin resultado en Presidencia 2024.",
    "249 polígonos sin fila de resultados; aparecen en gris.",
    "32 filas de voto en el extranjero están fuera del mapa.",
    "19 secciones siguen con más votos en lista que personas en lista nominal; la diferencia no está explicada.",
    "La geometría usa EPSG:32614 como supuesto de trabajo; el CRS original no está confirmado por metadatos.",
    "La victoria presidencial no se determina por sección ni por distrito: estas escalas sirven para explorar resultados.",
    "CPV no integrado.",
)

REGLAS_METODOLOGIA_DEMO = (
    "En caso de victoria, el margen es la ventaja sobre el segundo lugar.",
    "En caso de derrota, el faltante es la distancia al primer lugar.",
    "Votos para ganar = faltante + 1; en empate se necesita 1 voto.",
    "Abstención = lista nominal menos votos en lista, descontando casillas especiales.",
    "Derrota competitiva: faltante menor a 5 puntos; intermedia: de 5 a menos de 15; lejana: desde 15.",
    "Victoria sólida: margen de al menos 15 puntos; las demás victorias son ajustadas.",
    "Es un diagnóstico sobre Presidencia 2024, no un pronóstico.",
)
