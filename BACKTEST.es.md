# Evaluar el relleno: forma de curva, backtest y variantes locales

[English](BACKTEST.md) · [Algoritmo](ALGORITMO.md) · [Configuración y comandos](README.es.md)

Esta guía distingue el comportamiento implementado de las propuestas que todavía no existen.
La capa shape del apartado final está implementada y apagada por defecto; los experimentos y alternativas indicados como propuestas siguen pendientes.

El [notebook y la guía MLflow](MLFLOW.es.md) permiten editar listas de candidatos, registrar
experimentos locales, ejecutar una demo sintética y utilizar un grid ampliado del modelo.
Aquí `tune` se refiere al comando CLI con sus seis campos originales salvo indicación expresa.
Ambos usan el mismo criterio de cobertura primero y validación cronológica solo del ganador.
El ejemplo del notebook reserva cinco fechas; el valor predeterminado del CLI sigue siendo veinte.

## 1. Qué significa «mejor relleno»

El objetivo principal es recuperar precios propios que faltan. EEX aporta información, pero
**la respuesta contra la que se mide el error es el propio ocultado**, o la verdad sintética
guardada antes de crear huecos. Un resultado más parecido a EEX no es necesariamente mejor.

Hay varias dimensiones: precisión, cobertura, errores grandes, estabilidad y coherencia entre
contratos. Conviene medirlas por separado. Una curva visualmente suave puede equivocarse mucho;
una curva con pendientes o cambios estacionales no es incorrecta por tenerlos. Tampoco debe
imponerse automáticamente que todos los VWAPs de contratos distintos cuadren entre sí.

## 2. Qué forma produce LOCAL actualmente

Hay **un estimador local de base**: media de ajustes Own−EEX o Own/EEX−1, ponderada por
volumen, tipo y distancia logarítmica entre puntos medios de entrega. Después modera el ajuste
mediante `shrink_k`. Ratio/aditivo cambian la fórmula del ajuste, no la geometría de esa distancia.
`correlation=true` puede modificar el factor entre grupos; conserva el mismo estimador.

La prueba con referencia 30-09-2026, M+1 propio=110/EEX=100 y Q+2 propio=120/EEX=150 muestra:

| Mes | EEX | Relleno local aditivo |
|---|---:|---:|
| Enero 2027 | 150 | 132.239522 |
| Febrero 2027 | 150 | 128.569541 |
| Marzo 2027 | 150 | 130.903094 |

Aquí el centro del trimestre enero–marzo coincide con el centro de febrero. La señal trimestral
negativa recibe más fuerza allí y aparece un valle que no estaba en EEX. Es consecuencia de
representar un contrato de entrega por su punto medio, no evidencia observada de que febrero
deba ser más barato. Además, sus meses promedian por horas **130.637302**, mientras el trimestre
original permanece **120**. El comprobador informa esa diferencia sin reconciliarla.

Esta lógica es una hipótesis de estimación defendible, pero no garantiza una forma económica
correcta ni consistencia entre agregados. Un trimestre representa una entrega completa, no un
precio puntual en su centro. Al visualizar, ordena los meses por entrega y representa los
trimestres como intervalos/agregados: unir M+1…M+10,Q+1,Q+2 en una sola línea mezclaría periodos
solapados. El [ejemplo auditado](ALGORITMO.md#local-month-quarter-example) contiene los pesos.

## 3. Qué hacen hoy backtest y tune

`backtest` oculta un periodo propio de una fecha, incluidas sus etiquetas equivalentes, lo
estima y compara con el original. Conserva los otros contratos del día. Retira el periodo antes
de seleccionar ratio/aditivo y aprende la fecha después de predecirla. Para valorar el resultado
desplegado, lee **`pipeline_configured`**: `local_*`, `hist_*` y `blend_*` son diagnósticos y no
todos reproducen las capas, la reducción o el respaldo de producción.

`tune` compara una rejilla limitada de configuraciones y selecciona **una configuración global**:

1. Reserva las últimas 20 fechas distintas de observaciones para validar, salvo otro valor de
   `--validation-days`. Calibra sobre las anteriores; exige `warmup_days=0`.
2. Usa las mismas observaciones evaluables para todos los candidatos. Primero prefiere la
   **máxima cobertura** de calibración.
3. Entre esos candidatos, compara el error en la intersección de casos predichos por **todos**.
   Calcula `MAE_modelo/MAE_EEX` por identidad y promedia dando igual peso a cada curva.
4. El menor score gana; un empate favorece el primer candidato. Evalúa solo al ganador sobre
   las fechas posteriores, sin elegir parámetros utilizando sus errores.

Score 1 iguala el error de EEX; 0.8 mejora un 20 % ese error normalizado medio por curva. No es
el porcentaje de aciertos ni necesariamente la reducción del MAE monetario global. EEX sigue
siendo un benchmark diagnóstico aunque no se permita copiarlo como respaldo de producción.
Si el MAE de EEX es cero para una curva, el cociente se define como 1 cuando el modelo también
es perfecto, e infinito en otro caso. Si el ganador no predice ningún caso de validación,
su cobertura es cero y el error no es evaluable, no cero.

**La cobertura tiene prioridad, no es una puntuación combinada con el error.** Un candidato
que predice 100 casos puede ganar frente a otro que predice 99 aunque este tenga menor MAE.
Además, los casos fuera de la intersección cuentan para cobertura, pero no para el error común
de selección. Esta política debe encajar con el coste que tenga dejar un hueco sin rellenar.

La cobertura se refiere a propios evaluables con EEX, no a todos los huecos objetivo. Los
filtros generales de anclas también condicionan qué propios se evalúan. Para comparar distintos
filtros habría que fijar un universo independiente; excluir casos difíciles no debe confundirse
con estimarlos mejor. No se evalúan aquí objetivos sin referencia EEX.

La validación es cronológica con aprendizaje diario: originales de una fecha de validación
ya pasada pueden alimentar fechas posteriores. No simula un bloque que permanece sin propios.
Tampoco repite actualmente varios cortes temporales ni da incertidumbre sobre el ganador.

### Disponibilidad EEX: escenario fijo de evaluación

`eex.offset_days=0` permite publicaciones hasta la referencia T; `-1` solo hasta T-1 día
natural o anteriores. Elígelo en el TOML, utiliza `--eex-offset-days -1` en `backtest`/`tune`
o `EEX_OFFSET_DAYS=-1` en el notebook. No es un candidato de ninguno de los grids. El corte
afecta al benchmark EEX, referencias del pipeline y ventanas de precios/spreads del fallback.
Las entregas objetivo siguen resolviéndose desde T.

Con offset negativo, el histórico libera parejas originales Propio_h/EEX_h solo si `h<T`
y `h<=T+offset_days`, conservando h para decaimiento/caducidad. Nunca aprende una pareja de
fechas distintas. LOCAL e HIST siguen disponibles; la sorpresa actual de CROSS exige EEX
del mismo día, por lo que no aporta ajuste cross actual con offset negativo, incluso con
`layer_cross=True`. Las covarianzas cross sí aprenden parejas históricas exactas; los pesos
de correlación local también siguen siendo utilizables.

En lunes con offset -1, el corte es domingo. La publicación del viernes tiene tres días de
antigüedad respecto al lunes: `max_stale_days=2` la rechaza y cero sigue siendo sin límite.
Revisa `eex_offset_days`, `eex_cutoff_date`, `eex_asof` en LOO/predicciones emparejadas y la
política de disponibilidad en los metadatos de tuning.

Compara 0 y -1 en ejecuciones separadas, identificadas, con las mismas fechas previstas y
el mismo enmascarado. Un score menor no demuestra por sí solo mejor modelo: cambian la
referencia EEX y posiblemente los propios evaluables. Informa cobertura y claves comunes;
empareja expresamente los casos antes de atribuir diferencias a precisión. Las fechas del
CSV son una convención diaria, no un registro de disponibilidad intradía o revisiones históricas.

## 4. Qué parámetros se pueden comparar

La rejilla del comando CLI admite seis campos:
`basis_mode`, `tau_log`, `shrink_k`, `layer_hist`, `layer_correlation`, `layer_cross`.
Por defecto solo varía los tres modos de basis; las otras dimensiones requieren listas explícitas.

El [notebook de experimentos](MLFLOW.es.md) añade campos de memoria, fallback y shape a su
grid; esa guía enumera sus nombres Python exactos. Las indicaciones «fijo en tune» de la tabla
siguiente se refieren al CLI. Los filtros que cambian las observaciones evaluadas siguen
excluidos de ambos grids.

| Familia | Controles actuales | Qué permiten estudiar |
|---|---|---|
| Alcance local | `method.tau_log`, `other_kind_weight`, `shrink_k` | Alcance entre vencimientos, mezcla de tipos y fuerza de la señal local. Solo tau/shrink entran en la rejilla actual. |
| Volumen y observaciones | `method.min_volume`, `max_anchor_dev` | Qué anclas se admiten. La transformación `ln(1+volumen)` está fijada en código: no existe un selector de ponderación por volumen. |
| Fórmula y estabilidad | `method.basis_mode`, `ratio_eex_floor`, `max_ratio_deviation` | Diferencia absoluta/proporcional y guardas numéricas. Solo basis_mode entra en la rejilla. |
| Memoria propia | `layers.hist`; `method.ewma_halflife_days`, `hist_max_age_days`, `hist_auto_min_obs` | Permitir historia, rapidez de adaptación, caducidad y evidencia para hist-auto. Solo el modo de capa entra en la rejilla. |
| EEX suavizado | `eex_fallback.price_method`, `price_window`, `ewma_halflife`, `spread_window`, `anchor_months` | Media/EWMA, publicaciones de precios/spreads, intensidad exponencial y meses ancla. Todos quedan fijos dentro de tune. |
| Correlación local | `layers.correlation`; `correlation.halflife_days`, `prior_obs` | Activación y memoria/confianza de pesos aprendidos. Solo activación entra en la rejilla. |
| Ayuda entre curvas | `layers.cross`; `cross.min_corr`, `min_obs`, `halflife_days` | Activación, admisibilidad y memoria de relaciones. Solo activación entra en la rejilla. |
| Disponibilidad y rutas | `eex.offset_days`, `max_stale_days`; `layers.local`, `arbitrage` | Corte de publicaciones, antigüedad, ajuste local y reconstrucción. Disponibilidad fija dentro de cada grid; local/arbitrage solo varían si se solicita en el notebook ampliado. |

Los parámetros no incluidos en la rejilla requieren una comparación adicional controlada;
cambiar el TOML y ejecutar tune varias veces no garantiza por sí solo que los universos de
evaluación sigan siendo iguales. El límite predeterminado de la rejilla es 50 combinaciones.

**No todo lo configurable se debe optimizar por error.** Mapping, unidades, zona horaria,
convenciones, columnas y rutas deben representar correctamente los datos. La lista objetivo
define lo que se quiere producir y debe mantenerse comparable. `warmup_days=0` permite usar
todo el pasado suministrado; reducirlo cambia la evidencia. `eex.warn_stale_days` afecta al aviso,
no al precio. `eex.max_stale_days=0` significa sin límite, no solo publicaciones del mismo día.

## 5. Pruebas que añadiría para comparar estrategias

**Lo siguiente es un protocolo propuesto, no nuevas opciones ya implementadas.**

Generar curvas sintéticas completas y guardar su verdad antes de ocultar datos. Si el escenario
supone consistencia, construir sus Q/Cal a partir de la misma verdad de meses por horas; en otro
escenario se pueden introducir diferencias explícitas entre agregados. Probar varios mecanismos:
basis aditivo, proporcional, pendiente por vencimiento, estacionalidad, cambios bruscos, ceros y
negativos. Repetir semillas. Ningún generador demuestra por sí solo precisión real.

El generador sintético actual ya tiene memoria temporal, factores por grupo y días vacíos,
pero no una estructura específica de basis por estación/vencimiento, y su volumen aleatorio
no determina el ruido del precio. No basta para decidir si otra ponderación de volumen es mejor.

Usar exactamente las mismas máscaras para todos los candidatos:

- Un hueco aislado, como el backtest actual.
- Dos o tres meses consecutivos, o todos los meses de un trimestre.
- Solo M+1 y Q+2 visibles, para reproducir la duda concreta del experimento.
- Toda una familia o varios días completos sin precios propios.
- Memoria insuficiente, caducada o tras un cambio de nivel; cambio de mes/trimestre.

Las ausencias persistentes deben retirarse del input **antes de preparar y actualizar el
histórico de cada día**, incluidas las curvas ayudantes afectadas. Ocultar solo una predicción
y después dejar que su verdad entrene HIST/cross no reproduciría esa ausencia.

Calibrar sobre fechas anteriores, congelar parámetros y evaluar en otras posteriores. Repetir
con varios puntos de corte; conservar un tramo final sin usarlo para elegir. El principio de
separación temporal evita entrenar con el futuro de lo evaluado; véase la documentación oficial
de [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html).
El proyecto no utiliza esa clase ni implementa hoy esta repetición de cortes.

Medir por identidad, familia, plazo y patrón de ausencia, no solo una media global:

| Medida | Estado y lectura |
|---|---|
| MAE, RMSE, sesgo y cobertura | Ya disponibles en distintos informes; revisar casos comunes y denominador. Menor error, sesgo cercano a cero y cobertura suficiente. |
| Error extremo, por ejemplo percentil 95 | Propuesto: detectar métodos con una buena media y fallos ocasionales grandes. |
| Error de spreads entre meses | Propuesto: compara diferencias estimadas con diferencias de la verdad oculta. |
| Trimestre frente a sus meses | Ya hay diagnóstico de consistencia; no participa en el score de tune. |
| Curvatura y estabilidad del ajuste | Propuesto: medir saltos del basis y evolución temporal. No premiar una curva plana ni eliminar estacionalidad legítima. |
| Cambio de etiqueta M+1/M+2 | Propuesto: seguir también el mismo periodo absoluto para no interpretar un cambio de contrato como un salto artificial. |

## 6. Otras lógicas LOCAL que merece la pena comparar

Son alternativas de diseño pendientes, no mejoras demostradas:

| Alternativa | Idea | Límite que debe medirse |
|---|---|---|
| Cercanía por días naturales | Sustituir distancia logarítmica por distancia en días con un alcance interpretable. | También necesita decidir cómo representa los contratos largos; no garantiza consistencia. |
| Solapamiento de entrega | Dar peso al trimestre según cuánto cubra la entrega del mes; usar distancia para contratos no solapados. | Hay que normalizar por horas para no favorecer contratos largos por tamaño. No impone por sí sola que los meses sumen el trimestre. |
| Mismo tipo primero | Usar meses para meses y consultar otros tipos cuando falte evidencia suficiente. | Puede perder información útil; hace falta definir qué es evidencia suficiente. La separación estricta ya se consigue con other_kind_weight=0 y correlation=false, pero el respaldo jerárquico todavía no existe. |
| Interpolar el ajuste mensual | Interpolar basis entre anclas mensuales, con una política explícita fuera de ellas. | Un trimestre no es una ancla mensual puntual. Pocas anclas y extrapolación requieren respaldo. |
| Otra ponderación de volumen | Comparar pesos iguales, logaritmo actual o influencia limitada. | Confirmar primero qué mide total_volume: MW, MWh u otra unidad. Normalizar por horas solo tendría sentido si la definición lo justifica. |
| Ajuste conjunto de contratos | Ya implementado opcionalmente como shape, con penalizaciones suaves y límites; no como otro estimador LOCAL. | Originales incompatibles pueden dejar residuos. Solo se mueven originales con permiso explícito; véase la capa implementada al final. |

Para interpolación mensual, PCHIP es una posible alternativa a splines que pueden introducir
sobreoscilaciones: preserva la monotonía de los datos interpolados, según su
[documentación oficial](https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.PchipInterpolator.html).
Eso no garantiza monotonía del precio final al combinarlo con EEX ni coherencia de agregados.
No está incorporado al proyecto.

Empezaría comparando el local actual con **distancia natural** y **solapamiento de entrega**,
y probaría pesos iguales frente al logaritmo de volumen. Después estudiaría la memoria y el
respaldo EEX donde realmente se usan. Ajustar todas las opciones a la vez dificultaría atribuir
la mejora y aumentaría el riesgo de elegir una combinación que solo funciona en la muestra.

## 7. Qué se puede ejecutar hoy

Con input, mapping y EEX configurados para la máquina de destino:

```powershell
python run.py backtest
python run.py tune --basis-modes auto,ratio,additive --hist-modes off,auto --validation-days 20 --max-trials 50
```

El segundo comando prueba seis combinaciones si no se varían las otras dimensiones. Requiere
al menos 22 fechas de observaciones válidas y dos fechas de calibración con predicciones comunes,
además de evidencia evaluable en validación. El experimento de dos anclas de un único día no
cumple ese requisito y no ha producido un ganador de tune.

Lee `backtest_loo.csv`, `backtest_report.csv`, `tuning_calibration.csv`,
`tuning_validation.csv` y `tuning_selected.json` en el output configurado. Tune propone
parámetros y registra la configuración de partida; **no modifica config.toml**.

<a id="shape-investigation"></a>

## 8. Investigación de la forma: evidencia y conclusión

**Fuentes primarias consultadas.** Callegaro et al. (2022), sección 5.2 y apéndice A,
suavizan la corrección para conservar la estacionalidad y relacionan precios con promedios
sobre las entregas. Esto respalda investigar un ajuste por intervalos, en lugar de representar
todo un trimestre únicamente por su centro. [Artículo completo](https://onlinelibrary.wiley.com/doi/full/10.1002/asmb.2645).

Fleten y Lemming (2003) combinan información de mercado, forma estacional y un objetivo de
suavidad con restricciones de precios. Su propuesta no se limita a dibujar una línea agradable.
[Publicación original](https://www.sciencedirect.com/science/article/pii/S0140988303000392).

**Aplicación opcional implementada:** la capa shape regulariza ajustes mensuales sobre EEX,
con penalizaciones suaves de coherencia; véase [su alcance actual](#optional-shape-layer). La idea es penalizar cambios bruscos del ajuste
y representando cada Q/Cal mediante el promedio por horas de sus entregas. Usar EEX como
referencia de forma es nuestra adaptación, no una mejora demostrada por esos artículos para
este input. No exigir una curva plana, monótona ni universalmente positiva.

**Prueba de sensibilidad ejecutada.** Sobre las mismas dos anclas sintéticas, sin historia,
cross, correlation ni arbitrage, se probaron las 27 combinaciones aditivas de:

- `tau_log`: 0.25, 0.5, 1.
- `shrink_k`: 0.5, 1, 2.
- `other_kind_weight`: 0, 0.2, 0.6.

Los originales M+1=110 y Q+2=120 se mantuvieron. Se define valle interior estrictamente como
`febrero < min(enero, marzo)`; no basta con que febrero esté por debajo de la media de sus
vecinos, pues eso también puede suceder en una secuencia monótona curvada.

| Resultado del experimento | Qué demuestra |
|---|---|
| 18 de 18 combinaciones con peso cruzado 0.2/0.6 tienen mínimo interior en febrero | El efecto persiste en esta rejilla; no es exclusivo del valor por defecto. |
| Las 9 combinaciones con peso cruzado 0 no tienen ese mínimo | Se elimina aquí al dejar de utilizar Q+2 para los meses, sacrificando esa información. |
| El promedio mensual supera al trimestre original entre 6.979617 y 35.411089 | Estos parámetros no imponen la igualdad trimestral. No son errores frente a verdad mensual conocida. |

Por ejemplo, con tau=0.5 y shrink=1, cambiar el peso cruzado de 0.6 a 0 cambia enero–marzo
de **132.239522, 128.569541, 130.903094** a **151.054476, 150.681660, 150.474199**.
La segunda secuencia ya no tiene valle, pero su promedio **150.738738** se aleja más del
trimestre propio 120. Una forma aparentemente más regular no identifica por sí sola un ganador.

En este escenario hay además una razón algebraica. Sean `a` y `b` los pesos no negativos
del mes y trimestre, con `a+b>0`, y `k=shrink_k>0`. Sin historia/cross:

```text
ajuste = (10×a − 30×b)/(a+b+k)
ajuste + 30 = (40×a + 30×k)/(a+b+k) > 0
```

Con EEX=150 en esos meses, cada precio estimado supera 120. El caso a=0 tampoco alcanza
120 mientras k>0 y exista evidencia local. No basta con variar pesos para imponer una
ecuación que el estimador no contiene. Esta demostración se limita a estas anclas y supuestos.

**Controles que introduciría antes de seleccionar otro refill.** Evaluar los errores sobre
huecos ocultados junto con: spreads entre entregas, cambios bruscos del basis, agregación por
horas, sensibilidad a una sola ancla y estabilidad del mismo contrato absoluto entre fechas.
Informar qué parte procede de originales y cuál de estimaciones. Los umbrales necesitan
calibración por curva y horizonte; un salto no debe rechazarse automáticamente si hay evidencia
propia que lo explique. Actualmente solo parte de esto existe en el informe de consistencia.

Para un output que conserva VWAPs históricos, una discrepancia de agregación no prueba una
oportunidad de arbitraje: los contratos pueden haberse operado a distintos momentos o con
distintas muestras. EEX, por su parte, publica settlements entre sus datos de cierre diario.
[EEX End-of-Day](https://www.eex.com/en/market-data/eex-group-datasource/end-of-day-prices).
La necesidad de imponer igualdades exactas dependería de si se busca una curva de valoración
coherente o completar observaciones conservando sus diferencias; esa es una decisión de uso.

Los artefactos de esta revisión local están en `output/anchor_influence_test/`:
`run_shape_sensitivity.py`, `shape_sensitivity.csv` y `shape_sensitivity.json`.
La carpeta output está ignorada por Git y esos archivos no forman parte del repositorio
publicado. El estudio verifica sensibilidad y estructura, **no predicción real ni parámetros
óptimos**, y no cambia el comportamiento de producción.

<a id="rollover-audit"></a>

## 9. Cambio de mes y trimestre: qué se conserva y qué puede saltar

Hay que distinguir cambiar de etiqueta de cambiar de precio para una misma entrega.
El 30-09-2026, M+1 significa octubre y M+2 significa noviembre. El 01-10-2026, M+1 significa
noviembre. El motor resuelve estas fechas y busca el mismo periodo absoluto en las publicaciones
EEX utilizadas. Para estudiar estabilidad se siguen `delivery_start` y `delivery_end`, junto
con identidad y perfil; comparar únicamente M+1 entre fechas compararía contratos distintos.

**Prueba ejecutada con el motor actual.** Se suministraron nueve publicaciones EEX sintéticas,
terminando el 30 de septiembre, ninguna publicación el 1 de octubre y ningún precio propio.
Se desactivaron historia, cross, correlation y arbitrage en la configuración del experimento.
El respaldo conserva sus valores por defecto: EWMA de cinco publicaciones, vida media dos,
media simple de nueve spreads y `anchor_months=2`. La configuración de producción no se editó.

| Misma entrega absoluta | 30-09-2026 | 01-10-2026 | Diferencia |
|---|---:|---:|---:|
| Noviembre 2026 | M+2: 114.000000, cascada | M+1: 116.659473, EWMA directa | +2.659473 |
| Enero–marzo 2027 | Q+2: 156.659473, EWMA directa | Q+1: 156.659473, EWMA directa | 0 |

En las nueve publicaciones, octubre vale siempre 100 y los spreads noviembre menos octubre
son 10, 11, ..., 18. El 30 de septiembre, noviembre se calcula como
`100 + media(10,...,18) = 114`. El 1 de octubre ya entra entre los meses promediados directamente:
la EWMA de sus últimos cinco precios, 114, 115, 116, 117 y 118, vale **116.659473**. Los pesos
normalizados, del más antiguo al reciente, son 0.088947075, 0.125790159, 0.177894149,
0.251580318 y 0.355788298. El último settlement sigue siendo 118 y `eex_asof` sigue siendo
30-09-2026 en ambas estimaciones. No hay nueva información que explique esa diferencia.

**La causa es un cambio de fórmula al cambiar el calendario.** El límite entre promedio directo
y cascada, y el mes desde el que parte la cascada, se calculan desde la fecha de referencia.
También puede verse afectado un mes que continúa en cascada si cambia su mes de partida.
El control trimestral no cambia porque aplica la media directa al mismo periodo y las mismas
publicaciones en ambas fechas. Esto no prueba que todos los trimestres sean siempre estables:
con nuevos datos o distintas capas pueden cambiar. Sí demuestra que este salto concreto
no es un error de emparejamiento ni un movimiento del contrato observado.

Otros efectos que conviene distinguir:

- **LOCAL:** sus pesos dependen del tiempo restante hasta la entrega. Pueden variar aunque los
  precios de las anclas no cambien. Además, una ancla propia de ayer no es una ancla local de hoy.
- **HIST:** no se reinicia al cambiar de mes. Conserva ajustes por tipo, grupo y conjunto de la
  curva; no guarda una memoria independiente para cada entrega absoluta o estación del año.
  Transferir esa diferencia a otra entrega es una hipótesis del modelo que hay que evaluar.
- **Disponibilidad:** una ventana incompleta impide el respaldo. Con `eex.max_stale_days=0`
  en el TOML no hay límite de antigüedad admitida; el aviso de tres días no bloquea el relleno.

**Qué mejoraría primero, sin cambiarlo en esta revisión:** investigar una regla de respaldo
que controle estos cambios de fórmula y evaluar su continuidad manteniendo fijos contratos
y publicaciones. Medir por separado los cambios explicados por nueva información, por
envejecimiento de la evidencia y por cambio de ruta. No imponer que todos los precios queden
congelados ni que la curva sea plana. Hay que contrastar cualquier alternativa con precisión,
cobertura y forma, además de este caso de calendario.

La reproducción está en `output/rollover_audit/run_audit.py`; `comparisons.csv`, `filled.csv`
y `summary.json` registran valores, métodos y supuestos. Se ejecuta desde la raíz con
`.venv/Scripts/python.exe -B output/rollover_audit/run_audit.py`. Los cálculos manuales coinciden
con el motor, que no informó errores. Son artefactos locales ignorados por Git. La prueba
confirma una limitación de estabilidad; no mide el error frente a precios propios reales ni
modifica el algoritmo.

<a id="optional-shape-layer"></a>

## 10. Capa opcional de forma implementada y cómo validarla

La capa está implementada y **apagada por defecto**. Se ejecuta después del refill y combina
cambios pequeños, segundas diferencias del ajuste mensual aditivo `precio-eex_settle` y
residuos de agregación Quarter/Year ponderados por horas. Usa EEX bruto admitido actualmente,
no la EWMA del respaldo. La regularización necesita tres meses consecutivos con el mismo
`eex_asof`; la agregación necesita los tres/doce meses completos, pero no requiere EEX.
No rellena missing ni ajusta Day/Week/Season/BOM/BOW.

Los modos son `off`, `audit` (solo propuestas) y `adjust` (aplica una solución validada y
limitada). Por defecto los precios propios de la curva son fijos. La opción explícita
`adjust_originals=true` permite moverlos con mayor penalización de fidelidad; el input bruto
siempre queda intacto. Los originales cambiados pasan a `estimated`/`own+shape`/
`shape_adjusted_original`: no se presentan como observaciones. Los estimados modificados
conservan la procedencia previa y reciben `+shape`.

Los controles y valores iniciales implementados son `shape.mode="off"`,
`shape.adjust_originals=false`, `shape.smoothness_weight=1.0`,
`shape.coherence_weight=10.0`, `shape.coherence_tolerance=0.01`, `shape.max_abs_adjustment=10.0` y
`shape.original_weight=10.0`. Son valores de partida, no un óptimo calibrado.
[SHAPE.es.md](SHAPE.es.md) detalla objetivo, límites, consola y ejemplos. El solver convexo
con límites usa NumPy y valida condiciones KKT; si falla conserva precios previos.
La coherencia es suave: originales incompatibles o límites estrechos pueden dejar residuos
aunque la resolución sea correcta. Confidence no se usa como varianza.

**Agregación y forma no son lo mismo.** Restar 10.637302 a cada mes del ejemplo anterior
lleva el promedio por horas a 120, pero conserva todos los spreads y el valle de febrero.
Además supera el límite inicial de movimiento de 10. Es una demostración aritmética, no la
salida esperada del nuevo solver. Hay que evaluar ambos objetivos conjuntamente; los alias
y varias estimaciones que comparten anclas no son evidencia independiente.

Resolver una fecha no exige historia adicional; siguen vigentes la memoria y las ventanas
EEX del refill. Para elegir penalizaciones y límites sí hace falta evaluación histórica con
bloques ausentes, fechas posteriores, estaciones, horizontes y cambios de mes, sobre el mismo
universo. Un número de años no certifica solapamiento ni cobertura suficientes.

`pipeline_configured` evalúa shape después de ocultar el periodo y todos sus alias: la verdad
oculta no puede actuar como restricción original de shape. Historia y cross siguen aprendiendo
solo de originales reales. El CLI mantiene sus seis dimensiones y shape fijo; el
[notebook de experimentos](MLFLOW.es.md) sí puede incluir explícitamente los campos shape
en su grid. Compara sobre observaciones emparejadas: errores, extremos, cobertura, residuos,
tamaño de cambios y movimiento de propios.
Ocultar bloques y validar múltiples orígenes siguen siendo protocolos propuestos, no nuevas
funcionalidades de esta capa.

La motivación para suavizar la corrección conservando estacionalidad aparece en la sección
5.2, observación 10 de [Callegaro et al.](https://onlinelibrary.wiley.com/doi/full/10.1002/asmb.2645).
Nuestra adaptación con EEX no demuestra mejora predictiva. No impone una curva plana,
monótona ni positiva. No están implementadas una plantilla EEX suavizada conjuntamente ni
regularización temporal. La coherencia entre vencimientos no corrige por sí sola el
[salto del mismo contrato al cambiar de mes](#rollover-audit): requiere una prueba temporal
independiente y no debe esconderse mediante un gráfico más suave.

**La tolerancia de coherencia es diagnóstica, no una restricción obligatoria.**
`shape.coherence_tolerance=0.01` compara el valor absoluto del residuo
promedio-mensual-menos-padre con 0.01 en la unidad de precio de la curva. Subirla relaja la
comprobación y bajarla la endurece. No cambia el optimizador ni el precio aceptado.
Penalizaciones suaves, originales protegidos y límites de movimiento pueden dejar un resultado
fuera del margen. Audit señala la propuesta; adjust señala el resultado publicado. El trace
informa cada agregado y el resultado global, o null si no hay agregado aplicable. El mismo
valor numérico se interpreta en la unidad de cada curva; no es un porcentaje ni convierte monedas.

Véanse [el alcance de power y la muestra EEX local](SHAPE.es.md#por-qué-es-específico-de-power-y-qué-mostró-la-muestra-eex): concordancia agregada no exige meses iguales ni constituye una regla universal para todos los activos.

## 11. Influencia DayAhead: comportamiento actual y límites de validación

La auditoría sintética aislada usa el 30-09-2026, D+1 propio a 100 frente a EEX 80,
volumen 100, modo aditivo, sin historia y los parámetros actuales de distancia/tipo/shrink.
Con EEX objetivo 120, esa ancla de +20 produce **M+1=121.069779, M+4=120.028826 y
Q+2=120.017899**. La influencia se vuelve pequeña, pero no desaparece. Al existir ajuste
LOCAL, no entra el respaldo EEX suavizado: una influencia mínima puede cambiar la ruta
de cálculo. Es comportamiento existente, no una mejora predictiva demostrada.

La correlación actual aprende **sorpresas del basis propio−EEX entre grupos de contratos**;
no es un modelo solo EEX ni una relación individual M+1 frente a M+4. La revisión EEX usó
42 publicaciones, del 10-08 al 06-10-2026: los cambios diarios de abril 2027 correlacionaron
aproximadamente 0.81–0.85 con contratos fijos de noviembre–febrero, sobre 41 pares.
Sin verdad histórica propia no permite clasificar rellenos ni validar un ancla ganadora.
Elegibilidad por familia y un previo basado en EEX validado contra propios siguen siendo
propuestas. Los artefactos están en `output/local_anchor_review/`, ignorado por Git;
la auditoría no cambió la lógica de producción.
