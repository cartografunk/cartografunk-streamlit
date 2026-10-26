# SESNSP · fuero común

Corte de la descarga: septiembre de 2026; años de registro: 2015–2025. Los 12 meses de 2025 tienen datos. Los hechos son registros de averiguaciones previas o carpetas de investigación, no necesariamente fecha de ocurrencia.

`fuero_comun_estatal` y `fuero_comun_municipal` cuentan delitos registrados; `victimas_estatal` cuenta víctimas. `sexo` y `grupo_edad` contienen también categorías No identificado/No especificado: no son subtotales. Los valores -1 y vacíos se preservan. La fuente no incluye población; la app usa POB1 del CPV 2020 como denominador fijo para tasas etiquetadas de 2020–2025, sin interpretarlas como tasas con población anual observada.

`dim_delito.parquet` cataloga las cuatro categorías jerárquicas. `codigo_delito` es interno a Cartografunk. El origen y SHA-256 de cada ZIP se registran en `catalogo_fuentes.json`; el detalle de archivos en `manifiesto.json`.
