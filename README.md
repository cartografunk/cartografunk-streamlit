# Cartografunk · Explorador público

Aplicación Streamlit para consultar indicadores del Censo 2020/SCINCE, registros del fuero común del SESNSP (2015–2025), producción agrícola, pecuaria y pesquera de SIACON, Defunciones Registradas del INEGI (2012–2024) y elecciones federales del INE (2024). Incluye mapa, gráfica, tabla, descarga CSV y compass. No utiliza Supabase ni login.

En **Fuente → Elecciones federales · INE** se consultan Presidencia, Diputaciones federales de mayoría relativa y Senadurías de mayoría relativa de 2024 por estado o distrito federal. Los 300 polígonos distritales vienen del MGE 2024 y tienen una copia simplificada de visualización; la geometría original permanece en el archivo fuente. Presidencia y Senadurías registran voto en el extranjero bajo distrito 00; esos registros no tienen polígono y se guardan aparte. Los resultados de casilla tienen claves de casilla, pero no contamos con coordenadas o puntos de casilla para dibujarlas. Los distritos locales y las secciones del MGE no se usan en esta primera integración. `data/ine/catalogo_fuentes.json` documenta los ZIP de entrada y los archivos publicados con SHA-256.

## Fuente EDR

En **Fuente → Defunciones registradas · INEGI** se exploran los años de registro 2012–2024 según la residencia habitual de la persona fallecida. El mapa ofrece entidad y municipio, filtro por capítulo CIE o grupo de la Lista Mexicana, sexo y edad agrupada. La gráfica presenta conteos anuales; Compass compara dos grupos de causas entre estados. Las tasas de 2020–2024 usan `POB1` del CPV 2020 como denominador fijo y están etiquetadas así; no son tasas ajustadas por edad. En los conteos estatales entran los registros con municipio de residencia desconocido; siete claves municipales históricas sin geometría actual quedan en los Parquet pero no se dibujan. El consolidado individual de 271 MB **no se publica**: `data/edr/` contiene solo agregados anuales y catálogos. El manifiesto documenta procedencia, tamaños y SHA-256.

## Fuente SIACON

En **Fuente → Producción agropecuaria y pesquera · SIACON** se elige Agricultura, Ganadería o Pesca. Agricultura y Ganadería tienen mapas estatales y municipales; Pesca solo tiene mapa estatal. La gráfica muestra series anuales y Compass compara dos indicadores de un mismo producto o especie entre estados en un año. Los años disponibles en esta copia son 1980–2024 para Agricultura y Ganadería estatales, 2003–2024 para Agricultura municipal, 2006–2024 para Ganadería municipal y 2011–2018 para Pesca estatal. Los archivos conservan todas las columnas numéricas y de clasificación del SQLite; la interfaz suma solo superficies, volúmenes y valores dentro del producto elegido. El inventario se muestra por un año. Algunas unidades de pesca no están documentadas dentro de la base y se indican como tales en pantalla. Procedencia y SHA-256 en `data/siacon/manifiesto.json`.

## Fuente SESNSP

En **Fuente → Delitos · SESNSP**, el mapa muestra incidencia estatal o municipal y víctimas estatales. La gráfica presenta la serie histórica mensual o anual; Compass compara un indicador fijo del CPV 2020 con un delito en el año elegido, o dos delitos, con cortes fijos. Los porcentajes disponibles son participación del municipio en el estado y participación del periodo en el historial 2015–2025 para el mismo delito. Las tasas de 2020–2025 utilizan `POB1` del CPV 2020 como denominador fijo y lo indican en pantalla; para varios años se muestra el promedio anual. Los tres ZIP de origen, el diccionario metodológico y los SHA-256 constan en `data/crimen_sesnsp/catalogo_fuentes.json`. El año 2025 tiene los 12 meses registrados.

## Filtro municipal

1. Al elegir **Municipio**, aparece **Filtro por estado** debajo de **Nivel**.
2. Se puede escoger cualquiera de las 32 entidades; el valor inicial es **Elige un estado**. No existe opción **Todos los estados**.
3. Mientras no se elija un estado, la app no consulta ni dibuja municipios.
4. Con un estado elegido, **Buscar y marcar municipios** permite seleccionar uno o varios por nombre o CVEGEO; sin marcas se muestran todos los municipios de ese estado.
5. Al limpiar las marcas, vuelve el estado completo. Al volver a **Elige un estado**, deja de mostrarse el mapa municipal.

## Archivos

`data/publico/` contiene las tablas del Censo por nivel y tema. `data/crimen_sesnsp/` contiene los Parquet SESNSP por fuente y año, la dimensión de delitos, el catálogo de procedencia y el manifiesto. `data/siacon/` contiene los cinco cierres anuales, sus catálogos y el manifiesto. `data/edr/` contiene solo conteos agregados anuales, catálogos y manifiesto. `data/geometria/` contiene únicamente copias de visualización. `data/dim_*.parquet` guarda las dimensiones geográficas y del Censo. `data/agrupacion_excepciones.csv` es la configuración de dos agrupaciones de variables. `static/municipal_visual_1000m.json` es la geometría estática que el componente municipal carga una vez. `components/municipal_map/dist/municipal_map.js` es el front-end ya compilado; no hace falta npm en el servidor. `assets/img/favicon.webp` es el icono de la app.

## Ejecución local

Desde esta carpeta, con PowerShell:

```powershell
& 'D:\Conda\envs\cartografunk\python.exe' -m streamlit run explorador.py --server.port 8502
```

Para usar el mapa PyDeck de respaldo en Municipio:

```powershell
$env:CARTOGRAFUNK_MUNICIPAL_MAP = 'pydeck'
& 'D:\Conda\envs\cartografunk\python.exe' -m streamlit run explorador.py --server.port 8502
```

## Despliegue desde tu cuenta

1. En GitHub, crea un repositorio vacío llamado `cartografunk-streamlit` en tu cuenta. Puede ser público o privado; conserva `.streamlit/config.toml` en la raíz. No agregues un README inicial en GitHub porque ya está aquí.
2. `deploy_streamlit` está dentro de otro repositorio Git. Desde la carpeta superior del proyecto, cópiala a una carpeta hermana nueva para que sea un repositorio independiente. Sustituye `TU_USUARIO` por tu usuario de GitHub y ejecuta estos comandos en orden:

```powershell
Copy-Item -LiteralPath .\deploy_streamlit -Destination ..\cartografunk_streamlit_deploy -Recurse
Set-Location ..\cartografunk_streamlit_deploy
git init
git branch -M main
git add .
git commit -m "Publicar explorador Streamlit"
git remote add origin https://github.com/TU_USUARIO/cartografunk-streamlit.git
git push -u origin main
```

3. En [Streamlit Community Cloud](https://share.streamlit.io/), conecta tu GitHub, pulsa **Create app** → **Yup, I have an app** y selecciona el repositorio `TU_USUARIO/cartografunk-streamlit`, rama `main`, archivo `explorador.py`.
4. En **Advanced settings**, elige Python **3.12**, la versión usada para preparar este paquete; guarda y pulsa **Deploy**. No hay secretos que configurar. La geometría municipal se sirve desde `app/static/municipal_visual_1000m.json` gracias a `enableStaticServing = true` en `.streamlit/config.toml`.

## Atribuciones

Fuentes: Censo de Población y Vivienda INEGI (2020), Marco Geoestadístico Nacional INEGI (2025), incidencia delictiva y víctimas del fuero común SESNSP (descarga con corte de septiembre de 2026), producción agrícola, pecuaria y pesquera SIACON (copia local con datos hasta 2024; pesca hasta 2018), Defunciones Registradas INEGI (2012–2024), resultados electorales SICEE y MGE 2024 del INE. Paletas: ColorBrewer 2.0. Estas atribuciones también se muestran dentro de la app.
