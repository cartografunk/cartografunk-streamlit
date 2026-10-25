# Cartografunk · Explorador público

Aplicación Streamlit para consultar indicadores del Censo 2020/SCINCE por estado, municipio y metrópoli. Incluye mapa, clasificación, tabla, descarga CSV y compass estatal. No utiliza Supabase ni login.

## Filtro municipal

1. Al elegir **Municipio**, aparece **Filtro por estado** debajo de **Nivel**.
2. Se puede escoger cualquiera de las 32 entidades; el valor inicial es **Elige un estado**. No existe opción **Todos los estados**.
3. Mientras no se elija un estado, la app no consulta ni dibuja municipios.
4. Con un estado elegido, **Buscar y marcar municipios** permite seleccionar uno o varios por nombre o CVEGEO; sin marcas se muestran todos los municipios de ese estado.
5. Al limpiar las marcas, vuelve el estado completo. Al volver a **Elige un estado**, deja de mostrarse el mapa municipal.

## Archivos

`data/publico/` contiene las tablas por nivel y tema. `data/geometria/` contiene únicamente copias de visualización. `data/dim_*.parquet` guarda las dimensiones. `data/agrupacion_excepciones.csv` es la configuración de dos agrupaciones de variables. `static/municipal_visual_1000m.json` es la geometría estática que el componente municipal carga una vez. `components/municipal_map/dist/municipal_map.js` es el front-end ya compilado; no hace falta npm en el servidor. `assets/img/favicon.webp` es el icono de la app.

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

Datos y geografía: INEGI, Censo de Población y Vivienda 2020 (SCINCE) y Marco Geoestadístico. Paletas: ColorBrewer 2.0. Estas atribuciones también se muestran dentro de la app.
