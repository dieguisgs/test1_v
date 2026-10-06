# Relleno de curvas VWAP


[Diccionario de outputs](OUTPUT.es.md) · [Output dictionary](OUTPUT.md)
[English](README.md) · [Algoritmo](ALGORITMO.md) · [Algorithm in English](ALGORITHM.md)

[Repositorio en GitHub](https://github.com/dieguisgs/test1_v)

Completa los precios que faltan para cada **fecha de referencia, producto, región, unidad y
tenor objetivo**, utilizando VWAPs observados y settlements de EEX. El output enriquecido
conserva filas y columnas originales, añade puntos ausentes e indica origen y método del precio.

La identidad de una curva es **`(product, region, unit)`**. Un mismo nombre en otra región o
unidad tiene mapeo, anclas, historia y resultados independientes. Los valores originales se
conservan; el cruce interno recorta espacios exteriores sin cambiar mayúsculas ni escritura.
Región/unidad vacías son valores literales, nunca comodines. El producto no puede estar vacío.

## Configuración mínima para empezar

No necesitas ajustar las 46 entradas. **19 son rutas, nombres de columnas y zonas horarias**;
no son parámetros estadísticos. Para arrancar, revisa `[paths]`, genera y revisa el mapping,
elige `[targets].tenors` y deja `method.basis_mode = "auto"`. Mantén los demás valores
iniciales, incluidas `correlation = false` y `cross = false`.

La referencia completa documenta controles avanzados para auditoría y cambios deliberados.
`tune` admite seis controles del modelo, pero sin opciones adicionales compara solo los tres
modos y mantiene el resto fijo. No busca automáticamente entre todas las entradas del TOML.

## Instalación

Requiere Python 3.11 o posterior. Desde la carpeta del proyecto, utiliza una de estas opciones:

```powershell
uv sync
```

o un entorno virtual con pip:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install "numpy>=1.26" "pandas>=2.2" "openpyxl>=3.1" "pytest>=8.0"
```

Los ejemplos siguientes usan el `python` de ese entorno. En PowerShell, actívalo con `.venv\Scripts\Activate.ps1`, utiliza directamente `.venv\Scripts\python.exe` o antepón `uv run` a los comandos si utilizas uv.

## Configurar el input real

Hay **un único archivo de configuración, `config.toml`**, tanto aquí como en el ZIP portable.
La ruta inicial es `data/vwaps.xlsx`: cámbiala por el input real acumulado de la máquina de
destino. Todos los comandos habituales `python run.py ...` utilizan ese único config.
Para una prueba independiente, usa expresamente `--vwap data/synthetic_vwaps.csv` si has
generado ese fichero; el valor por defecto nunca selecciona la demo silenciosamente.

El ZIP portable excluye el mapeo local, los inputs sintéticos, los datos de EEX, el entorno virtual y los outputs generados. Instala las dependencias en la máquina de destino, incorpora tus archivos de entrada y EEX, y genera allí el mapeo.

Edita `[paths]` en la configuración elegida:

```toml
[paths]
vwap_input = "data/vwaps.xlsx"
mapping = "mappings/products.csv"
eex_curves_dir = "../eex_scraper/output/curves/POWER"
output_dir = "output"
```

Las rutas son relativas al archivo de configuración; también se admiten rutas absolutas. El input puede ser CSV o Excel, incluido un patrón como `data/vwaps_*.csv`. `--vwap` cambia esa ruta para un comando concreto.

El input tiene formato largo, con una observación por fila:

| Columnas | Significado |
|---|---|
| `reference_date`, `product`, `region`, `unit`, `tenor2`, `vwap` | Fecha, identidad completa de curva, tenor y precio: columnas obligatorias. Región/unidad deben existir, aunque corresponda un valor vacío literal. Fechas válidas; los precios vacíos o inválidos pueden completarse. |
| `total_volume` | Volumen opcional para combinar observaciones y ponderar anclas. |
| `weekday`, `country`, `classification`, `periodicity_2`, `n_trades` | Otros metadatos: se conservan junto con todas las columnas originales. Región/unidad son claves de identidad, no solo metadatos descriptivos. |

Ejemplos de tenors: `D+1`, `WE`, `M+1`, `Q+1` y `Cal+1`. Ajusta `[vwap_columns]` si tus columnas tienen otros nombres y `[targets]` para los tenors que quieres completar. Los archivos de EEX necesitan `tradeDate`, `maturityType`, `deliveryStart` y `settlPx`.

`curves/POWER/<área>/Base.csv` y `Peak.csv` son archivos largos con el histórico acumulado
localmente de cada producto EEX, no solo una fecha. Es normal que una fecha se repita: tiene
varios contratos de entrega. El scraper reconstruye estas vistas desde los contratos de
`table_data/`; no añade simplemente filas al final del CSV de curvas. Un fichero por
área/producto encaja con el tamaño pequeño actual y el lector VWAP. No hace falta separarlo
por días; pasar en el futuro a particiones mensuales o Parquet exigiría adaptar escritura y lectura.

La lista objetivo se edita directamente en la configuración, sin cambiar Python:

```toml
[targets]
tenors = ["D+1", "D+2", "WE", "M+1", "M+2", "M+3", "Q+1", "Cal+1"]
```

Edita la sección existente para ampliar o reducir la lista. Se aplica a todos los productos `fill`. Se conservan los originales fuera de la lista, pero no se crean sus filas ausentes. Incluir un tenor permite estimarlo cuando hay datos suficientes; no garantiza que pueda calcularse.

## Elegir el modo de cálculo

Edita la sección `[method]` existente de `config.toml`:

```toml
[method]
basis_mode = "auto"
```

| Valor | Cálculo |
|---|---|
| `auto`, por defecto | Elige ratio o additive para cada objetivo con el árbol siguiente |
| `ratio` | Estima `basis = Own/EEX − 1` y calcula `precio = EEX × (1 + basis)`; no cambia automáticamente |
| `additive` | Estima `basis = Own − EEX` y calcula `precio = EEX + basis`; no cambia automáticamente |

En auto se aplica la primera regla que se cumpla:

1. Si `abs(EEX del objetivo) < ratio_eex_floor`, usa additive (`auto_additive_low_eex`).
2. Si no, cuando no quedan anclas ratio pero sí additive, usa additive
   (`auto_additive_no_ratio_anchors`).
3. Si no, cuando ninguno tiene anclas y solo additive tiene historia vigente y permitida por
   `[layers].hist`, usa additive (`auto_additive_history_only`).
4. En el resto de los casos, usa ratio.

Los VWAPs originales finitos, incluidos cero y negativos, siempre se conservan. Las anclas
ratio exigen `abs(EEX) >= ratio_eex_floor`, `Own/EEX > 0` y
`abs(Own/EEX − 1) <= max_ratio_deviation`; additive admite pares finitos que superen los
filtros comunes de volumen/desviación. −10/−12 puede ser un ancla ratio válida; 2/0 no.
Un objetivo auto próximo a cero elige additive aunque otras anclas permitan usar ratio.
Forzando ratio, un objetivo con EEX = 0 sigue dando 0.

`max_ratio_deviation` también puede rechazar anclas ratio aunque sus precios sean distintos de
cero y tengan el mismo signo. Auto puede usar después sus diferencias aditivas si pasan los
filtros comunes. `max_ratio_deviation` protege solo ratio; `max_anchor_dev` filtra ambos modos
y está apagado por defecto. Auto no detecta outliers ni elige el modelo local de menor error.

Cada modo tiene sus propias historias, puntuaciones y estadísticas de correlación/cross.
No se suma un porcentaje directamente a un precio. `[layers].hist = "auto"` es otra opción:
decide si ayuda usar la historia dentro de cada modo, no cuál de las dos fórmulas elegir.

Por ejemplo, Own = 2 frente a EEX = 0 aporta una diferencia aditiva de 2. Con objetivo EEX = 1,
sin historia, suma de pesos locales W = 1 y `shrink_k = 1`, auto elige additive y reduce esa
diferencia con `w = 0.5`: precio = `1 + 0.5 × 2 = 2`. Sin esa reducción, la fórmula pura daría 3.
W depende en realidad del volumen y la distancia de entrega. El documento del algoritmo
detalla las ponderaciones y el aprendizaje; auto es una regla que debe validarse, no una
garantía de menor error predictivo.

## Referencia completa de configuración

Los valores siguientes son los del `config.toml` entregado. Edita sus secciones existentes,
sin duplicar secciones TOML. No hace falta cambiar Python. Las rutas relativas parten de la
carpeta del config, salvo `eex_file` del mapeo, que parte de `eex_curves_dir`.

### Rutas (`[paths]`)

| Parámetro | Valor entregado | Efecto de cambiarlo |
|---|---|---|
| `vwap_input` | `data/vwaps.xlsx` | Elige originales acumulados CSV/Excel o un patrón entre comillas; no apuntes al output enriquecido |
| `mapping` | `mappings/products.csv` | Elige el mapeo (product, region, unit)→EEX que se genera/lee |
| `eex_curves_dir` | `../eex_scraper/output/curves/POWER` | Elige la raíz con CSV largos de EEX, por ejemplo `DE/Base.csv` |
| `output_dir` | `output` | Carpeta donde se escriben curvas diarias/acumuladas, enriquecidos, informes y logs |

### Capas (`[layers]`)

| Parámetro | Defecto | Efecto de cambiarlo |
|---|---|---|
| `local` | `true` | `false` apaga el ajuste con anclas de hoy; los originales se conservan |
| `hist` | `"auto"` | `"on"` usa historia vigente; `"off"` la desactiva; `"auto"` compara errores anteriores frente a EEX, por separado para cada modo/grupo |
| `correlation` | `false` | `true` sustituye pesos fijos entre grupos por relaciones medidas entre sorpresas, con un peso previo de respaldo |
| `cross` | `false` | `true` permite sorpresas de otros productos correlacionados; necesita historia interna y EEX del objetivo, con estadísticas separadas por modo |
| `arbitrage` | `true` | `false` apaga la construcción por strips/residuos con contratos ya disponibles cuando EEX no puede valorar el objetivo |

Apagar capas no elimina originales. `hist = off` no apaga por sí solo cross: cross puede usar
su historia interna para calcular sorpresas, sin sumar esa media al precio. Elegir additive
en auto no enciende una capa local/hist/cross apagada.

### Antigüedad EEX (`[eex]`)

| Parámetro | Defecto | Efecto de cambiarlo |
|---|---|---|
| `max_stale_days` | `0` | 0 admite cualquier publicación anterior; N positivo rechaza curvas con más de N días naturales de antigüedad; nunca selecciona EEX futuro |
| `warn_stale_days` | `3` | A esta antigüedad el mensaje pasa a ERROR; informa del problema, pero este umbral no rechaza por sí mismo la curva ni hace fallar la ejecución |

Solo EEX del mismo día permite aprender historia, aunque se admita una curva antigua para valorar.

### Zonas horarias del borrador de mapeo (`[timezones]`)

| Parámetro | Defecto | Efecto de cambiarlo |
|---|---|---|
| `default` | `"Europe/Berlin"` | Zona de entrega por defecto para nuevas filas propuestas del mapeo |
| `GB` | `"Europe/London"` | Excepción para el borrador de GB |
| `IE` | `"Europe/Dublin"` | Excepción para IE |
| `PT` | `"Europe/Lisbon"` | Excepción para PT |
| `GR` | `"Europe/Athens"` | Excepción para GR |
| `RO` | `"Europe/Bucharest"` | Excepción para RO |
| `BG` | `"Europe/Sofia"` | Excepción para BG |
| `FI` | `"Europe/Helsinki"` | Excepción para FI |

Puedes añadir otras áreas. Una `timezone` explícita del mapeo manda; si está vacía se utiliza
el respaldo configurado. Cambiar esta sección no sobrescribe zonas explícitas revisadas. Base incluye los cambios de hora. Peak Day/Weekend
cuenta 12 horas todos los días; los demás tipos Peak cuentan solo lunes a viernes.

### Objetivos y convenciones (`[targets]`, `[conventions]`)

| Parámetro | Defecto | Efecto de cambiarlo |
|---|---|---|
| `targets.tenors` | `D+1..D+3`, `WE..WE+3`, `BOW`, `W+1..W+4`, `BOM`, `M+1..M+10`, `Q+1..Q+8`, `Sum+1..Sum+3`, `Win+1..Win+3`, `Cal+1..Cal+3` | Edita la lista de etiquetas para añadir/quitar filas objetivo de todos los productos `fill`; se conservan los originales fuera de ella |
| `conventions.day` | `"calendar"` | `"business"` interpreta D+n contando lunes a viernes; no se incorpora un calendario de festivos |
| `conventions.weekend_offset` | `0` | Desplaza WE+n propio este número de fines de semana al resolver la entrega |

Los rangos de la tabla abrevian la lista entregada; en TOML se escriben las etiquetas una a una,
como en el ejemplo inicial. Añadir un tenor no garantiza cobertura. `detect-conventions` ayuda
a comparar las interpretaciones.

### Cálculo e historia (`[method]`)

| Parámetro | Defecto | Efecto de cambiarlo |
|---|---|---|
| `basis_mode` | `"auto"` | Utiliza el árbol por objetivo o fuerza `"ratio"` / `"additive"` |
| `min_volume` | `0` | Un volumen conocido inferior no sirve de ancla; volumen desconocido no equivale a estar por debajo de un umbral conocido; los originales permanecen intactos |
| `tau_log` | `0.5` | Un valor positivo mayor permite más influencia de anclas lejanas |
| `other_kind_weight` | `0.6` | Peso de anclas de otro tipo de contrato, antes del ajuste de correlación entre grupos si está activado |
| `shrink_k` | `1.0` | Un valor positivo mayor reduce `w = W/(W+k)` y favorece la historia permitida o el ajuste cero si no hay respaldo |
| `ewma_halflife_days` | `10` | Un valor positivo mayor hace más lenta la actualización de las historias ratio/additive; cuenta días con observaciones válidas, no días transcurridos |
| `max_anchor_dev` | `0` | 0 apaga este filtro común; N positivo excluye anclas con `abs(Own−EEX)/max(abs(EEX),ratio_eex_floor) > N`; entre valores positivos, aumentarlo admite más desviaciones |
| `ratio_eex_floor` | `1.0` | Mínimo positivo de abs(EEX) para anclas ratio; en auto, un objetivo por debajo elige additive. Está en unidades de precio y no modifica EEX |
| `max_ratio_deviation` | `1.0` | Máximo positivo de abs(Own/EEX−1) en anclas ratio y del ajuste ratio final absoluto; no limita diferencias aditivas |
| `hist_max_age_days` | `60` | Caducidad positiva en días naturales: se elimina cada media tipo/grupo/global cuando pasan más de estos días desde su última observación válida |
| `hist_auto_min_obs` | `10` | Masa efectiva de comparaciones antes de decidir en hist-auto; antes se permite la historia vigente. Aumentarlo retrasa la decisión |

Ambos modelos históricos aprenden de anclas originales con EEX del mismo día, después de
predecir ese día. Los estimados nunca alimentan historia. Si falta la media de un tipo, se
puede usar la de su grupo/global vigente dentro del mismo modo. Excluir una observación ratio
por EEX próximo a cero no descarta su diferencia aditiva válida. Revisa las unidades y valida
con datos reales antes de cambiar límites; auto no demuestra que una diferencia aditiva grande
sea una buena predicción.

### Correlación (`[correlation]`) y ayuda entre productos (`[cross]`)

| Parámetro | Defecto | Efecto de cambiarlo |
|---|---|---|
| `correlation.halflife_days` | `20` | Un valor mayor conserva más tiempo evidencia de sorpresas emparejadas; cada actualización descuenta los días naturales desde la pareja anterior |
| `correlation.prior_obs` | `8` | Un valor mayor mantiene más tiempo el peso cerca de `other_kind_weight` antes de que domine la correlación medida |
| `cross.min_corr` | `0.5` | Correlación mínima más alta para admitir un producto ayudante |
| `cross.min_obs` | `8` | Masa efectiva mínima más alta de observaciones conjuntas antes de admitir la ayuda |
| `cross.halflife_days` | `20` | Memoria de correlación y β del ayudante, descontando los intervalos naturales entre parejas |

Estos parámetros afectan a la predicción cuando la capa correspondiente está activa. Los
ayudantes pueden ser productos mapeados como `fill` o `helper`. Sorpresas, covarianzas y β
se mantienen separadas por modo.

### Calentamiento (`[run]`)

| Parámetro | Defecto | Efecto de cambiarlo |
|---|---|---|
| `warmup_days` | `0` | 0 reconstruye desde toda la historia original suministrada; N positivo limita el calentamiento a N días naturales y puede hacer que daily difiera de un refill más largo |

Esta opción no recupera archivos que falten. En la máquina de destino deben estar los
originales acumulados y la historia EEX correspondiente.

### Asignación de columnas (`[vwap_columns]`)

| Parámetro | Columna por defecto | Efecto de cambiarlo |
|---|---|---|
| `reference_date` | `"reference_date"` | Lee las fechas de observación de esa columna; obligatoria y con fechas válidas |
| `product` | `"product"` | Lee el nombre, primer componente de identidad; obligatorio y no vacío |
| `region` | `"region"` | Lee la región exacta de identidad; columna obligatoria, vacío literal |
| `unit` | `"unit"` | Lee la unidad exacta de identidad; columna obligatoria, sin conversión ni comodines |
| `tenor` | `"tenor2"` | Lee las etiquetas relativas de entrega; obligatoria |
| `vwap` | `"vwap"` | Lee los precios; columna obligatoria, aunque los valores vacíos/inválidos se conservan para enriquecerlos |
| `volume` | `"total_volume"` | Lee los volúmenes para anclas; la columna puede faltar |

Cambiar estas asignaciones modifica la interpretación, no elimina las columnas originales del output.

## Generar y revisar el mapeo

Ejecuta una vez en la máquina de destino:

```powershell
python run.py mapping
```

Revisa `mappings/products.csv` antes de rellenar. **Cada fila nueva se propone con `use = off`,
aunque se haya encontrado un CSV EEX**. Activa expresamente las identidades deseadas: `fill`
calcula esa curva, `helper` aporta ayuda sin publicar su propia curva calculada y `off` la
excluye del cálculo. Comprueba cada `eex_file`, identidad/perfil, `hours` y `timezone`. Las
unidades y divisas deben coincidir con EEX; el programa no las convierte. Las identidades
sin mapear se indican y no se procesan; sus originales permanecen en el enriquecido.

`fill`/`helper` requieren además `eex_file` no vacío: si no hay archivo asignado, la identidad
se excluye y se señala con `mapping_unassigned` aunque `use` esté activado. Es distinto de
tener una ruta asignada cuyo archivo no exista o no contenga cotizaciones para esa fecha:
esa identidad sí está activa, se avisa de los datos ausentes y puede usar VWAPs propios/arbitraje.

**El mapeo se edita a mano**, con un editor de texto o Excel. La cabecera es
`product,region,unit,use,area,profile,eex_file,hours,timezone,comment`. Conserva las identidades
exactas de tres componentes del input y el formato CSV UTF-8 separado por comas; `eex_file`
es relativo a la carpeta POWER configurada. Un nombre puede repetirse si cambia región/unidad;
repetir toda la identidad es un error. Relanzar `mapping` conserva decisiones existentes y
añade identidades nuevas con `off`.

Un mapeo antiguo sin columnas región/unidad solo se migra mediante `mapping` si cada fila
antigua tiene exactamente una identidad compatible en el input. Se conservan su EEX y demás
ajustes. Con cero o varios candidatos, termina con error y no reescribe el archivo: añade
filas explícitas a mano. Una clave presente pero vacía es literal, no una coincidencia sin
especificar. El propio input debe tener las columnas región/unidad configuradas.

Un mapeo de pruebas AT/DE/FR/NL es una demo, no una lista completa de mercados. Genera y revisa
las identidades del input de destino. Los originales sin mapeo o con `off` permanecen en el
enriquecido, sin generarles curvas estimadas.

Los bloques GB del input, como `GB_Other_Block_1_2` o `GB_Other_Block_3_4`, no tienen calendario
ni fuente de bloque implementados y se proponen como `off`. `TB2` no significa «bloque 2»:
no los asignes a ciegas a TB2, Base o Peak. Para soportarlos hace falta definir exactamente
las horas de entrega y una fuente de precios correspondiente.

## Ejecutar

Después de ajustar las rutas del único `config.toml`, tanto aquí como en el ZIP extraído:

```powershell
python run.py mapping
python run.py daily
python run.py catchup
python run.py refill --from 2026-09-01 --to 2026-09-30
python run.py daily --date 2026-09-30
```

`daily` y `refill` comparten el mismo motor. Mantén `warmup_days = 0` y proporciona originales
acumulados para reconstruir la misma historia; solo las filas de hoy pierden esa memoria.
Las reejecuciones sustituyen resultados por fecha/producto/region/unit, conservando otras
identidades, incluidas otras regiones/unidades del mismo producto.

Los resultados antiguos sin `region`/`unit` en la curva o `curve_region`/`curve_unit` en el
enriquecido se rechazan antes de escribir resultados. Usa un `output_dir` nuevo y reconstruye
con `refill`; no se deducen identidades antiguas ni se fusionan silenciosamente. El log sí
puede escribirse.

### Elegir entre los tres usos

| Necesidad | Comando | Alcance |
|---|---|---|
| Calcular hoy o revisar una fecha | `daily` o `daily --date YYYY-MM-DD` | Recalcula la fecha, aunque tenga resultados |
| Recuperar días/curvas pendientes | `catchup` | Solo grupos fecha/identidad fill pendientes hasta hoy |
| Reconstruir un intervalo o enriquecer todo su input | `refill --from YYYY-MM-DD --to YYYY-MM-DD` | Recalcula el rango solicitado |

Catchup empieza en la primera fecha disponible de input/EEX salvo `--from`; sin fechas,
requiere un inicio explícito. `--to` es hoy por defecto y no admite futuro ni rango invertido.
Considera laborables y fechas observadas de input activo/EEX, incluidos fines de semana.
Un grupo está pendiente si un objetivo resoluble falta en **cualquiera** de los históricos
calculado/enriquecido. Un registro presente `missing` ya cuenta como procesado. Recalcula
la curva completa del grupo pendiente y conserva grupos completos. Para actualizar estos
con nuevas cotizaciones, usa daily/refill. Si no hay curvas fill activas o pendientes, no escribe.

Catchup solo incorpora originales de grupos fill pendientes; no exporta por primera vez
helper/off/sin mapeo. Daily/refill enriquecen todos los originales del rango. Los tres
reconstruyen memoria desde originales acumulados, nunca desde estimaciones guardadas.
El esquema de históricos y archivos afectados se valida antes de escribir resultados.

### Opciones de la línea de comandos

| Opción | Comandos / defecto | Efecto |
|---|---|---|
| `--config RUTA` | Global opcional; defecto `config.toml` | Permite otro config para uso avanzado; se escribe **antes** del comando |
| `--vwap RUTA_O_PATRÓN` | `mapping`, `daily`, `catchup`, `refill`, `backtest`, `tune`, `detect-conventions`; defecto input configurado | Cambia el input de esa ejecución; entrecomilla patrones con comodines |
| `--date YYYY-MM-DD` | `daily`; defecto fecha local de la máquina | Elige una fecha de referencia |
| `--from YYYY-MM-DD`, `--to YYYY-MM-DD` | `refill`, `backtest`; por defecto se deducen de los datos disponibles | Acota el rango solicitado; los datos anteriores pueden seguir calentando la memoria |
| `--from YYYY-MM-DD`, `--to YYYY-MM-DD` | `catchup`; inicio inferido, final hoy | Recupera solo pendientes; no admite final futuro ni rango invertido |
| `--last N` | `status`; defecto 10 | Número de fechas a mostrar |
| `--truth RUTA` | `backtest`; ausente por defecto | Compara con una verdad sintética correspondiente a esos datos |
| `--areas LISTA` | `make-synthetic`; defecto `DE,FR,NL,AT` | Áreas sintéticas separadas por comas |
| `--profiles LISTA` | `make-synthetic`; defecto `Base,Peak` | Perfiles sintéticos |
| `--from`, `--to` | `make-synthetic`; defecto 2000-01-01 a 2100-01-01 | Filtra las fechas EEX disponibles para generar sintéticos |
| `--seed N` | `make-synthetic`; defecto 7 | Semilla aleatoria de los sintéticos |
| `--mode ratio` o `--mode additive` | `make-synthetic`; defecto ratio | Elige cómo generar los sintéticos; **no sustituye el `basis_mode` del relleno** |
| `--out RUTA` | `make-synthetic`; defecto `data` | Carpeta de salida sintética |

Por ejemplo, `python run.py daily --date 2026-09-30 --vwap "C:/datos/vwaps_*.csv"` utiliza
el config habitual con otro input. Si se necesita un config opcional, se escribe
`python run.py --config C:/ajustes/personalizado.toml daily --date 2026-09-30`; no hace falta
crear un segundo config para el uso habitual. Sustituye las fechas por las cubiertas en destino.

## Leer el output

Los resultados principales son `output/enriched_history.csv` y `output/enriched/YYYY-MM-DD.csv`.

| Columna | Significado |
|---|---|
| `curve_price` | Precio final utilizable. Lee esta columna cuando el `vwap` original estuviera vacío o fuera inválido. |
| `data_origin` | `original`, `estimated` o `missing`. |
| `estimation_method` | Por ejemplo, `ratio_local`, `ratio_local_history`, `additive_local`, `eex`, `contract_strip`, `contract_residual` o `none`. |
| `curve_row_type` | `original`, `original_invalid` o `added`. |
| `curve_product`, `curve_region`, `curve_unit` | Identidad completa normalizada usada en los cruces; los valores originales quedan intactos. |
| `curve_basis_mode` | Fórmula aplicada: `ratio` o `additive`. |
| `curve_configured_basis_mode` | Opción solicitada: `auto`, `ratio` o `additive`. |
| `curve_flags` | Incluye el motivo de selección auto cuando se eligió additive para una estimación con EEX. |
| Otras columnas `curve_*` | Claves de referencia, fuentes, detalles del cálculo y avisos. |

Se conservan los valores originales, los duplicados y los tenors fuera de los objetivos configurados. Un `vwap` original inválido no se sobrescribe: su estimación aparece en `curve_price`. Las filas añadidas llevan la estimación en ambas columnas. Los puntos que no pueden resolverse quedan como `missing`, sin inventar precios, volúmenes ni número de operaciones.

`filled_history.csv`, `filled/` y `consistency_history.csv` contienen la curva calculada y sus diagnósticos. Un fallo interno de cálculo detectado devuelve un código de salida distinto de cero sin sustituir los CSV de resultados; revisa `output/_logs/`.

## Validar

```powershell
python -B -m pytest -p no:cacheprovider
python run.py backtest
```

Las pruebas y los datos sintéticos validan la mecánica, no demuestran la precisión sobre tus datos reales de mercado. Es una base de complejidad media que utiliza observaciones propias, EEX, ajustes locales/históricos y arbitraje. Mantén `cross = false` y `correlation = false` hasta que la validación con datos reales justifique añadir esas capas. Los documentos del algoritmo enlazados explican los cálculos y sus límites.

El backtest empareja por fecha/producto/region/unit/tenor. Los informes de error y la detección
de convenciones separan unidades, sin promediar errores EUR/MWh y GBP/MWh. Compara
`pipeline_configured` con EEX sobre las mismas observaciones mediante `n_paired` y `mae_improvement`.


## Ajustar parámetros con originales reales: `tune`

**La referencia correcta para medir el error es tu VWAP propio ocultado, no EEX.** EEX es
una entrada y una comparación de referencia. Ejemplo: propio real 120, EEX 100; candidato A
predice 102 (error 18), candidato B predice 118 (error 2). B es mejor aunque se aleje de EEX.
El programa no busca que tu curva se parezca más a la curva EEX.

En cada observación evaluada, oculta ese punto propio, lo predice con el pipeline configurado
y compara contra el valor propio que realmente existía. No se esconde toda la curva del día.
Necesitas originales y EEX que coincidan en fechas y periodos de entrega; un scraper similar
sin ese solapamiento no basta. El comando informa o falla si no hay evidencia emparejada
suficiente: no inventa métricas para las fechas sin datos comparables.

```powershell
python run.py tune
python run.py tune --from 2026-08-01 --to 2026-09-30 --validation-days 10 --basis-modes auto,ratio,additive --tau-log 0.3,0.5 --shrink-k 0.5,1,2 --max-trials 50
```

Las fechas son ejemplos: utiliza el periodo cubierto por los originales y EEX de la máquina
real. **Requiere `run.warmup_days=0`**; no cambia esa opción automáticamente. Con 10 días
reservados exige al menos 12 fechas de observaciones propias válidas, y al menos dos fechas
de calibración con comparaciones realmente emparejadas. El ejemplo prueba 18 combinaciones.

| Opción de tune | Defecto | Efecto |
|---|---|---|
| `--from`, `--to` | Primera/última fecha del input | Intervalo del que se separan calibración y validación; el histórico anterior sigue disponible |
| `--vwap RUTA_O_PATRÓN` | Input configurado | Elige originales acumulados para esta evaluación |
| `--basis-modes` | `auto,ratio,additive` | Fórmulas candidatas, separadas por comas |
| `--tau-log` | Solo el valor configurado | Lista de alcances locales positivos finitos, por ejemplo `0.3,0.5` |
| `--shrink-k` | Solo el valor configurado | Lista de reducciones locales positivas finitas, por ejemplo `0.5,1,2` |
| `--hist-modes` | Solo el valor configurado | Lista de `auto,on,off` para permitir historia |
| `--correlation` | Solo el valor configurado | Lista `off,on` para comparar la extensión de pesos |
| `--cross` | Solo el valor configurado | Lista `off,on` para comparar ayuda entre curvas |
| `--validation-days` | `20` | Número positivo de últimas fechas distintas con observaciones válidas que se reservan; no días naturales consecutivos |
| `--max-trials` | `50` | Límite positivo del producto cartesiano; si se supera, rechaza la rejilla en lugar de truncarla |

Se exploran **solo esas seis opciones de modelo**. Los demás controles siguen como estén en
config. Con los valores por defecto se prueban tres modos, conservando los otros cinco campos.
Cambiar parámetros como caducidad o volumen requiere una comparación explícita adicional;
tune no explora automáticamente todo el inventario de configuración.

**Cómo decide cuál es mejor:**

1. Ordena las fechas propias elegibles de curvas fill activas y aparta las últimas N para
   validación. En las anteriores calibra todas las combinaciones. No utiliza los errores
   de validación para escoger el ganador.
2. Todos los candidatos deben evaluarse sobre exactamente las mismas claves propias y
   referencia EEX. Para cada curva calcula `MAE_modelo / MAE_EEX`, ambos contra el **mismo
   VWAP propio ocultado**. Después promedia esos cocientes con igual peso por curva.
3. Gana el menor promedio de calibración. 1 iguala EEX; 0.7 significa un error normalizado
   medio por curva un 30 % inferior al de EEX, **no** un 30 % menos de MAE global en moneda.
   Si EEX acierta perfectamente una curva, el cociente se define como 1 si el modelo también
   acierta y como infinito si falla. En empate gana el primero en el orden de la rejilla.
4. Solo entonces evalúa al ganador sobre las fechas posteriores reservadas, con parámetros
   fijos. La memoria sigue avanzando cronológicamente con los originales ya observados,
   incluso dentro de la validación: cada fecha utiliza solo historia anterior. No se usa
   información de precios futura.

Escribe `output/tuning_calibration.csv`, `tuning_validation.csv` y `tuning_selected.json`.
Los CSV muestran score, `normalized_skill=1-score`, número de parejas y errores MAE/RMSE/sesgo
por unidad; no suma errores absolutos de EUR/MWh y GBP/MWh. El JSON contiene el cambio propuesto,
la configuración base completa, el patrón de input y metadatos con fechas previstas y realmente
emparejadas. Guarda también los archivos de entrada, EEX y mapping para reproducir la evaluación:
una ruta/configuración por sí sola no conserva sus contenidos.

**No edita `config.toml` ni los históricos de curvas.** Revisa la validación y, si la decisión
de negocio la acepta, copia manualmente los valores seleccionados a las secciones existentes.
Un fallo de cualquier candidato aborta la evaluación; no se publica una selección parcial.

Es el mejor candidato **entre los probados, en calibración**, no una garantía para el futuro.
La validación oculta puntos que sí tuvieron precio: puede favorecer periodos líquidos y no
demuestra el comportamiento cuando falta una curva diaria entera, ni conoce la verdad de los
huecos reales. No reajustes repetidamente contra el mismo tramo reservado y después lo
presentes como evidencia independiente. Reserva nuevas fechas para evaluar cambios posteriores.

Los settlements EEX ausentes/no numéricos/no finitos se excluyen con aviso conservando los válidos. Un precio calculado no finito hace fallar el cálculo y evita escribir resultados.
