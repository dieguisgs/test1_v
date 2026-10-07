# Comparar backtests en un notebook con MLflow

[English](MLFLOW.md) · [Notebook](notebooks/backtest_mlflow.ipynb) · [Método del backtest](BACKTEST.es.md) · [README](README.es.md)

Este notebook ejecuta el comparador de parámetros existente y registra los experimentos en
un servicio local de MLflow. Puedes empezar con el ejemplo sintético y usar después el mismo
notebook en el ordenador que tiene tus VWAPs y EEX. MLflow organiza las pruebas; el comparador
decide qué combinación gana. No añade una técnica de relleno ni cambia el criterio de selección.

El [visor de curvas](NOTEBOOK.es.md) es otro notebook: muestra curvas ya guardadas. Este
notebook de experimentos carga datos, ejecuta backtests y guarda informes en `output/mlflow`.
Ambos notebooks están íntegramente en inglés: explicaciones, código, comentarios, etiquetas
y mensajes. Las guías Markdown independientes siguen disponibles en inglés y español.

## 1. Instalar y abrir

Desde la raíz del repositorio, con Python 3.11 o posterior:

```powershell
uv sync --group notebook --group experiment
uv run --group notebook --group experiment jupyter lab notebooks/backtest_mlflow.ipynb
```

En VS Code, abre la carpeta del repositorio, abre el notebook y selecciona el kernel de
`.venv`. En Windows su intérprete es `.venv\Scripts\python.exe`. Si no aparece:

```powershell
uv run --group notebook --group experiment python -m ipykernel install --user --name vwaps --display-name "Python (VWAPS .venv)"
```

Reinicia el kernel después de instalar dependencias. Sin uv, instala las dependencias del
proyecto y las herramientas opcionales en el mismo entorno que usa el kernel:

```powershell
python -m pip install "numpy>=1.26" "pandas>=2.2" "openpyxl>=3.1" "jupyterlab>=4" "ipywidgets>=8" "plotly>=5" "mlflow>=3.5,<4" "psutil>=6"
python -m jupyter lab notebooks/backtest_mlflow.ipynb
```

Ejecuta las celdas en orden. La demo genera sus propios datos, mapping e histórico EEX en
memoria. Necesita `config.toml` como configuración base, pero no lee sus ficheros reales de
input, mapping ni EEX. Sus cambios se aplican a un objeto de configuración independiente.
La demo inventa dos curvas: una con relación propia/EEX aditiva y otra proporcional, ambas
con ruido y ajustes cambiantes. Esa construcción favorece deliberadamente esas familias de
modelos; no es un benchmark de mercado neutral.

## 2. Los controles que puedes editar

| Control del notebook | Significado |
| --- | --- |
| `PROJECT_ROOT` | `None` busca el proyecto desde la carpeta actual o sus padres. Puedes indicar una ruta absoluta al repositorio. |
| `CONFIG_PATH` | `None` utiliza `config.toml`; una ruta relativa parte de la raíz del proyecto. |
| `DATA_MODE` | `"synthetic"` por defecto; cambia a `"real"` en el ordenador con tus ficheros. |
| `VWAP_PATH` | Input real alternativo opcional. `None` usa el definido en el TOML. Una ruta relativa alternativa parte de la raíz del proyecto. |
| `START_DATE`, `END_DATE` | Fechas ISO como `"2026-09-01"`, incluidas ambas. `None` utiliza los límites del dataset. |
| `EEX_OFFSET_DAYS` | `None` respeta `[eex].offset_days` tanto en modo sintético como real. `0` permite publicación en T; `-1` solo hasta T-1 día natural o anteriores. Debe ser un entero no positivo. |
| `VALIDATION_DAYS` | Número de últimas fechas de observación elegibles reservadas para validar; el ejemplo usa **5**. Son fechas con observaciones, no necesariamente cinco días naturales. |
| `MAX_TRIALS` | Máximo de combinaciones cartesianas; el ejemplo usa **24**. Un grid mayor falla antes de arrancar el experimento. |
| `DEMO_SEED`, `DEMO_PERIODS` | Generación sintética reproducible; semilla 7 y 30 periodos por defecto. No afectan al modo real. |
| `MLFLOW_PORT` | Puerto del servicio local, inicialmente **5000**. |
| `MLFLOW_STORAGE` | Carpeta local de experimentos, inicialmente `output/mlflow`, relativa a la raíz del proyecto. |
| `EXPERIMENT_NAME` | Agrupa ejecuciones relacionadas en MLflow. Mantén el nombre para comparar nuevas ejecuciones. |
| `LOG_PREDICTIONS` | Guarda o no los detalles de predicciones del backtest. Con datos reales pueden contener precios propios. |
| `PARAMETER_GRID` | Listas explícitas de valores candidatos, explicadas debajo. |
| `STOP_SERVER` | Última celda: `False` mantiene abierta la interfaz. Pon `True` y ejecuta esa celda para detener el servicio gestionado. |

`run.warmup_days` debe ser **0** al comparar parámetros para poder reproducir todo el propio
anterior suministrado. En modo real se conserva tu configuración y se rechaza un valor
distinto de cero; no se cambia a escondidas. Puede haber histórico anterior a `START_DATE`:
el rango limita las fechas evaluadas, no ordena descartar el histórico disponible.

### Comparar EEX del mismo día o solo anterior

Usa `EEX_OFFSET_DAYS=0` para permitir EEX publicado en T, o `-1` para excluir T aunque exista
en el archivo. El corte es `T + offset` en **días naturales**. En lunes, -1 significa domingo:
la última publicación disponible puede ser la del viernes. Tiene tres días de antigüedad
respecto al lunes, no dos respecto al domingo. Sigue aplicándose el límite de antigüedad
(`max_stale_days=0` significa ilimitado). Los tenors se siguen resolviendo desde T.

Es un escenario fijo **fuera de `PARAMETER_GRID`**, no un trigésimo campo del grid. Ejecuta
el notebook dos veces, por ejemplo con `EXPERIMENT_NAME="vwaps-offset-0"` y
`"vwaps-offset-minus-1"`, conservando las fechas previstas y el grid. La preparación muestra
la política efectiva; el snapshot del config y los metadatos la guardan. Los archivos de
predicciones emparejadas incluyen `eex_offset_days`, `eex_cutoff_date`, `eex_asof` si se activa
su registro. Benchmark EEX, refill y ventanas completas de medias respetan el mismo corte.

Las parejas históricas Propio_h/EEX_h se liberan con retraso solo si `h<T` y `h<=corte`,
manteniendo sus fechas originales para caducidad/decaimiento. LOCAL puede usar propios
actuales frente a la referencia anterior permitida. **No hay ajuste CROSS actual con offset
negativo**, porque su sorpresa exige EEX del mismo día; sus relaciones sí pueden aprender
parejas históricas exactas. HIST y los pesos aprendidos de correlación local siguen siendo
utilizables si hay evidencia suficiente.

Cambiar disponibilidad puede modificar muestra evaluable, cobertura y referencia. Un score
menor en otro escenario no es automáticamente mejor: revisa casos ocultados comunes y
cobertura. Es una convención diaria sobre CSVs suministrados, no un reloj de publicación
intradía ni una reconstrucción de las revisiones disponibles históricamente.

## 3. ¿Qué parámetros se pueden comparar?

El ejemplo inicial tiene seis combinaciones:

```python
PARAMETER_GRID = {
    "basis_mode": ["auto", "ratio", "additive"],
    "layer_hist": ["off", "auto"],
}
```

El producto cartesiano prueba cada modo con cada opción de histórico: **3 × 2 = 6**.
No son seis grids separados. Los parámetros omitidos mantienen el valor de la configuración
del dataset. El notebook muestra el número de combinaciones antes de ejecutar.

El notebook de experimentos admite los siguientes **nombres planos de campos Python**.
Algunos difieren del TOML: `fallback_price_window` corresponde a
`[eex_fallback].price_window`. El comando `tune` habitual sigue exponiendo sus seis campos
originales; el grid ampliado pertenece al notebook/API de experimentos.

| Campo del grid | Valores admitidos | Qué cambia |
| --- | --- | --- |
| `basis_mode` | `"auto"`, `"ratio"`, `"additive"` | Cómo se expresa la diferencia entre propio y EEX. |
| `tau_log` | Números finitos positivos | La rapidez con que pierde peso un ancla al aumentar la distancia logarítmica de entrega. |
| `shrink_k` | Números finitos positivos | Cuánto se acerca la señal local a su prior permitido cuando hay poca evidencia. |
| `layer_hist` | `"off"`, `"auto"`, `"on"` | Si/cómo se habilita la capa histórica existente; sigue necesitando observaciones anteriores utilizables. |
| `layer_correlation` | `False`, `True` | La ponderación existente aprendida de correlaciones entre basis propios. No busca el mejor ancla usando solo EEX. |
| `layer_cross` | `False`, `True` | El prior entre curvas existente, sujeto a sus requisitos de elegibilidad y evidencia. |
| `layer_local`, `layer_arbitrage` | `False`, `True` | Activan las capas local o arbitrage existentes. |
| `other_kind_weight` | Números finitos >= 0 | Peso previo de anclas de otra familia. Cero es una elección de peso, no una política general de elegibilidad entre familias. |
| `ewma_halflife_days` | Números finitos positivos | Semivida del basis histórico propio (`method.ewma_halflife_days`). |
| `hist_max_age_days` | Enteros >= 1 | Caducidad desde el último propio histórico utilizable. |
| `hist_auto_min_obs` | Números finitos >= 0 | Umbral de evidencia efectiva para la selección histórica automática. |
| `corr_halflife_days`, `corr_prior_obs` | Semivida positiva y prior no negativo, ambos finitos | Decaimiento y fuerza del prior (`correlation.halflife_days`, `correlation.prior_obs`). |
| `cross_min_corr` | Números finitos entre -1 y 1 | Correlación mínima entre curvas para utilizar cross. |
| `cross_min_obs`, `cross_halflife_days` | Evidencia no negativa y semivida positiva, ambas finitas | Umbral de evidencia y decaimiento entre curvas. |
| `fallback_price_method` | `"simple"`, `"ewma"` | Pesos iguales o exponenciales dentro de la ventana de precios del fallback. |
| `fallback_price_window`, `fallback_spread_window` | Enteros >= 2 | Publicaciones EEX para promediar precios y para promediar spreads. |
| `fallback_ewma_halflife` | Números finitos positivos | Semivida exponencial dentro de la ventana de precios del fallback. |
| `fallback_anchor_months` | Enteros >= 1 | Primeros vencimientos mensuales promediados directamente antes de propagar spreads. |
| `shape_mode` | `"off"`, `"audit"`, `"adjust"` | Desactivar, proponer o aplicar la capa shape existente. |
| `shape_adjust_originals` | `False`, `True` | Permiso explícito para mover precios finales derivados de observaciones propias. |
| `shape_smoothness_weight`, `shape_coherence_weight` | Números finitos >= 0 | Penalizaciones suaves por basis irregular e incoherencia entre meses y agregados. |
| `shape_max_abs_adjustment` | Números finitos positivos | Cambio máximo de shape en unidades de precio. |
| `shape_original_weight` | Números finitos >= 1 | Fidelidad a los originales cuando se permite modificarlos. |
| `shape_coherence_tolerance` | Números finitos >= 0 | Tolerancia diagnóstica; cambiarla sola no modifica el objetivo ni los precios. |

`GRID_EXAMPLES` incluye alternativas pequeñas con nombre: modos, modos más histórico,
distancia más contracción, alcance local, memoria histórica, promedios del fallback, shape y
capas aprendidas opcionales. Para elegir una, sustituye la
asignación de `PARAMETER_GRID`, por ejemplo por
`deepcopy(GRID_EXAMPLES["distance_and_shrinkage"])`. Sus valores son candidatos para estudiar,
no recomendaciones demostradas con datos reales.
`fallback_isolated` además desactiva local/histórico/cross para ejercitar explícitamente el
fallback: es una comparación controlada de esa rama, no de toda la configuración de producción.

Todo campo omitido permanece fijo. No pueden ser campos del grid las rutas, mapping/identidad,
tenors, convenciones de entrega, filtros de volumen/extremos, protecciones del ratio, antigüedad
EEX, offset de disponibilidad ni fechas de evaluación. Cambiarlos podría cambiar las observaciones que se comparan.
Una clave no admitida genera error. Para estudiar ese cambio, diseña otra evaluación con un
universo de verdad explícitamente comparable; no presentes muestras distintas como la misma
competición.

Es más fácil interpretar grids pequeños centrados en una pregunta que multiplicar todas
las listas. Por ejemplo, los parámetros del fallback pueden empatar porque al ocultar un
propio quedan otras anclas y el fallback nunca entra. Ese empate **no demuestra qué fallback
es mejor**. Asimismo, `shape_mode="audit"` no cambia predicciones y su tolerancia de coherencia
es diagnóstica. Para estudiar huecos que requieran fallback o bloques ausentes hace falta un
enmascarado apropiado; el notebook no crea automáticamente esa evidencia.

## 4. Cómo se elige al ganador

Imagina que tapamos un precio propio conocido, pedimos al relleno que lo recupere y comparamos
la respuesta con ese precio. Los demás propios disponibles ese día siguen visibles. Se tapan
juntos los alias del mismo periodo físico de entrega para que otro nombre no revele la
respuesta. Se evalúa un periodo ocultado cada vez; no se reproducen todos los posibles bloques
de huecos que podrían aparecer en producción.

Las fechas se dividen cronológicamente: las anteriores son **calibración** y las últimas
`VALIDATION_DAYS` fechas elegibles con propios son **validación**. Se prueban las combinaciones
en calibración, se elige una y se evalúa **solo esa ganadora** en validación. Sus parámetros
permanecen fijos, aunque los propios de fechas de validación ya pasadas pueden alimentar el
histórico de fechas posteriores, como en una ejecución diaria en orden cronológico.

El orden de selección es:

1. Preferir las combinaciones con máxima cobertura de predicciones en calibración sobre el
   mismo universo de referencia EEX. Un método no gana por abstenerse en los casos difíciles.
2. Entre ellas, preferir el menor score en los casos predichos por **todos** los candidatos
   de calibración. Para cada curva `(product, region, unit)` se calcula
   `MAE_model / MAE_EEX`; después se promedian esos cocientes dando el mismo peso a cada curva.
3. Ante un empate exacto, elegir según el orden de las combinaciones del grid.

Menor `score` es mejor. Por debajo de 1 mejora la referencia EEX bajo esta medida de igual
peso por curva; por encima de 1 empeora. **No** es un porcentaje de error del precio. Si el
MAE de EEX es cero en una curva, el cociente es 1 si el modelo también acierta exactamente,
y es infinito en caso contrario. `normalized_skill = 1 - score`. La demo puede tener empates
y no demuestra cuáles son los mejores parámetros reales.

La verdad contra la que se compara es **tu VWAP ocultado**, no EEX. EEX es información de
referencia y benchmark. MAE, RMSE y sesgo absolutos se muestran separados por unidad; la fila
global deja esos campos vacíos para no mezclar monedas o unidades. Mira también cobertura,
tamaño de muestra, fechas y resultados por unidad. La muestra común usada para precisión
puede ser menor que todas las predicciones disponibles de un candidato. Si faltan fechas
con comparaciones suficientes, se devuelve un error, no un ranking inventado.

Si cambias repetidamente el grid después de mirar la misma validación, esa validación pasa a
formar parte de tu investigación. Reserva fechas posteriores intactas o usa una evaluación
temporal separada antes de afirmar que generaliza. [BACKTEST.es.md](BACKTEST.es.md) explica
por qué ocultar conocidos es útil y también sus límites si los huecos reales tienen otra liquidez.

## 5. Qué verás en MLflow y en el notebook

El notebook arranca el servicio gestionado en **`127.0.0.1`** y muestra un enlace. Ejecuta la
comparación, enlaza con la ejecución en MLflow, muestra el ranking de calibración, los
parámetros propuestos y la tabla de validación del ganador. MLflow permite comparar parámetros,
métricas y archivos guardados entre ejecuciones. Los campos `eligible_for_selection` y
`selected` del notebook explican la elección; ordenar solo por precisión en la interfaz de
MLflow no reproduce la selección que prioriza cobertura.

El almacenamiento y los informes se guardan bajo `MLFLOW_STORAGE`. Cada ejecución del
notebook tiene una carpeta nueva de informes. Esos informes y los metadatos de configuración
permiten revisar qué se probó. Los parámetros elegidos son una **propuesta**: no se aplican
automáticamente a `config.toml`. Tampoco se regeneran ni sobrescriben curvas de producción.

La ejecución padre de MLflow agrupa las ejecuciones hijas de cada candidato. Se guardan
métricas de calibración por candidato; las de validación se registran solo para la combinación
ganadora y el padre. Los archivos incluyen informes CSV, snapshots del grid y configuración,
huellas de datos y procedencia del código/entorno. Los detalles opcionales de predicciones
permiten auditar errores concretos. Las huellas identifican los datos suministrados; no son
una copia del dataset ni sustituyen conservar los datos para reproducir una ejecución real.
`LOG_PREDICTIONS=False` omite los archivos individuales de precios/predicciones emparejados;
se siguen guardando informes agregados y metadatos de configuración/procedencia.

Se usa un servicio local con archivos locales; no hace falta una cuenta de MLflow en la nube.
Con datos reales, los archivos pueden contener precios propios e identificadores. Permanecen
en la carpeta elegida salvo que expresamente los copies/compartas o cambies el flujo. No se
genera ni se sube ningún ZIP. Detener el servicio conserva el histórico de experimentos.
La documentación oficial explica el [servidor de tracking](https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/)
y [MLflow Tracking](https://mlflow.org/docs/latest/ml/tracking/).

### Leer un experimento en la interfaz

1. Abre el enlace MLflow del notebook y la lista de ejecuciones del experimento. Localiza
   la ejecución padre y muestra sus hijas, llamadas `calibration-001`, `calibration-002`,
   etc. Compara esas hijas entre sí; el padre resume al ganador, no es otro candidato.
2. Añade a la tabla los parámetros que has variado y las métricas
   **`calibration.overall.coverage`** y **`calibration.overall.score`**. Primero conserva la
   cobertura máxima y, entre esas filas, gana el score menor. La etiqueta de la hija
   **`vwaps.selected` = `true`** identifica al ganador real. Si hay empate exacto, revisa
   `trial_id` y el orden del grid en el informe.
   El parámetro fijo **`eex_offset_days`** se guarda en el padre y en cada hija: muéstralo
   o fíltralo para distinguir los escenarios 0 y -1 antes de comparar ejecuciones.
3. Selecciona ejecuciones hijas para comparar sus parámetros y métricas. Mira también
   `calibration.overall.n_paired` y `calibration.overall.n_missing`. Las métricas
   **`validation.*` aparecen solo en la hija ganadora y el padre**: su ausencia en las demás
   significa que no se evaluaron en el periodo reservado. El resultado del padre no cuenta
   como una segunda prueba independiente.
4. Abre los archivos de la ejecución. **`reports/`** contiene los resúmenes CSV;
   `reports/calibration_report.csv` del padre contiene todo el grid. **`audit/`** guarda JSON
   de configuración, grid, fechas, parámetros elegidos, huellas y procedencia, según abras
   el padre o una hija. **`predictions/`** en las hijas guarda observaciones/predicciones
   individuales emparejadas cuando se habilitan. Con `LOG_PREDICTIONS=False` no se generan
   esos archivos; permanecen informes y metadatos. La etiqueta `vwaps.predictions` de cada
   hija registra `enabled` o `disabled`.
5. Revisa cobertura y score de validación de la ganadora y después los errores por unidad.
   Los nombres de métricas por unidad usan una etiqueta normalizada y un hash;
   `audit/*_metric_states.json` permite recuperar la unidad original. Ese archivo también
   registra métricas no finitas omitidas de los gráficos numéricos de MLflow. Un score
   ausente/infinito no es un cero: revisa el CSV/JSON.

La tabla ordenada del notebook muestra directamente la política de selección. MLflow ayuda
a inspeccionar y comparar ejecuciones; ordenar la interfaz no elige parámetros por sí mismo.

## 6. Usarlo en el ordenador con datos reales

Copia o clona el repositorio e instala allí los dos grupos opcionales. Configura tu input,
mapping revisado y carpeta EEX en `config.toml`, como explica el [README](README.es.md).
Después cambia estas celdas:

```python
DATA_MODE = "real"
VWAP_PATH = r"C:\Data\VWAPS\observations.xlsx"  # Or None to use config.toml.
START_DATE = "2026-08-10"
END_DATE = "2026-10-06"
EEX_OFFSET_DAYS = -1  # Example policy: exclude same-date EEX; None retains the TOML.
VALIDATION_DAYS = 5
EXPERIMENT_NAME = "vwaps-real-first-review"
```

Esas rutas y fechas son ejemplos, no ficheros incluidos ni un periodo obligatorio. El modo
real carga propios normalizados junto con el mapping y los libros EEX configurados. Solo
participan curvas del mapping activas para rellenar. Elige fechas con suficientes propios
elegibles y referencias EEX: tener días naturales en el rango no basta. Conserva suficiente
histórico previo para las técnicas que quieras comparar.

## 7. Problemas habituales

- **Error de importación:** instala ambos grupos en el kernel real del notebook y reinícialo.
  El Python del terminal puede ser distinto; la celda de preparación imprime el del notebook.
- **Puerto ocupado:** reejecutar el arranque en el mismo kernel puede reutilizar su servicio gestionado.
  Si el puerto lo ocupa un proceso ajeno, se rechaza. Prueba `MLFLOW_PORT=5001` en lugar de
  terminar un proceso que no has arrancado.
- **Arranque agotado o interfaz inaccesible:** revisa el `log_path` mostrado por el servicio
  y el error de arranque; comprueba el puerto y el entorno. La función espera a que el
  servicio responda antes de continuar.
- **Kernel reiniciado:** repite preparación y arranque. La propiedad del servicio pertenece
  al kernel: uno nuevo no adopta ni detiene un servicio dejado por otro proceso. La limpieza
  normal detiene el servicio propio; si uno anterior sigue ocupando el puerto, elige otro o
  detenlo desde la sesión propietaria. Los experimentos siguen guardados en disco.
- **Grid demasiado grande:** reduce las listas o aumenta deliberadamente `MAX_TRIALS`.
  El notebook muestra el producto cartesiano, no solo el número de campos.
- **Histórico/comparaciones insuficientes:** revisa fechas, mapping, tenors, propios finitos
  y publicaciones EEX. Cinco fechas de validación necesitan además calibración anterior
  utilizable. Activar histórico/correlación/cross no crea evidencia que no existe.
- **Detener la interfaz:** pon `STOP_SERVER=True` y ejecuta la última celda, o llama a
  `server.stop()`. Déjalo en `False` al usar Run All para poder consultar la interfaz al terminar.

## 8. Ejecución comprobada

En Windows con Python **3.14.2** y MLflow **3.17.0**, la suite completa pasó **715 tests** en
44,70 segundos, con un aviso de deprecación de MLflow/SQLAlchemy. Se ejecutó el notebook en
el kernel Jupyter real de `.venv` tanto con el offset predeterminado **0** como con **-1**
explícito. La ejecución -1 completó las seis hijas candidatas bajo un padre, con **25 fechas
de calibración / 290 casos emparejados** y **5 fechas de validación / 58 casos** solo para
la ganadora. Se revisaron los CSV guardados de predicciones emparejadas para comprobar que
cada publicación admitida cumple **`eex_asof <= eex_cutoff_date = T - 1 día natural`**.

La ejecución -1 comprobó también respuesta HTTP 200 de la interfaz local y parada limpia
del servicio. Las pruebas anteriores con offset predeterminado verificaron subida/descarga
de informes y conservación de registros al detener y volver a arrancar el servicio.

Estas comprobaciones validan el flujo local probado, no la precisión con propios reales que
no tenemos, la optimalidad de los parámetros ganadores sintéticos ni la ejecución en todas
las versiones de Python y sistemas operativos admitidos. El notebook guardado en Git no
contiene outputs.
