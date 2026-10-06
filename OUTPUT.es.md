# Diccionario de salidas

Versión inglesa: [OUTPUT.md](OUTPUT.md). Reglas de cálculo: [ALGORITMO.md](ALGORITMO.md).

Todas las claves de curva utilizan **fecha de referencia + product + region + unit + etiqueta de tenor**. Una región o unidad vacía es un valor literal de identidad. Los precios y errores absolutos usan la `unit` de su fila; no se convierten divisas. Los CSV usan UTF-8 con BOM, separador de coma y cabecera. Una celda numérica o de fecha vacía significa no disponible o no aplicable, nunca cero. Los precios cero y negativos son valores finitos válidos.

## Archivos

Las rutas siguientes son relativas a `[paths].output_dir`. Los archivos aparecen cuando el comando correspondiente tiene resultados; una comprobación de consistencia vacía puede no crear archivo.

```text
output/
  enriched_history.csv          Originales y puntos añadidos de las fechas procesadas
  enriched/YYYY-MM-DD.csv        Mismo esquema enriquecido para una fecha
  filled_history.csv            Puntos objetivo del motor de las fechas procesadas
  filled/YYYY-MM-DD.csv          Mismo esquema del motor para una fecha
  consistency_history.csv       Comparaciones disponibles de agregado frente a partes
  backtest_loo.csv               Predicciones individuales ocultando observaciones
  backtest_report.csv            Métricas del backtest
  tuning_calibration.csv         Puntuaciones de calibración de cada candidato
  tuning_validation.csv          Puntuaciones posteriores del candidato seleccionado
  tuning_selected.json           Propuesta de parámetros y metadatos de evaluación
  _logs/vwaps_YYYY-MM-DD.log      Registro de ejecución de comandos
```

`daily` y `refill` conservan en el enriquecido los originales, incluidas curvas sin mapping, off o helper. `catchup` actualiza exclusivamente grupos fecha/curva `fill` activos pendientes y conserva intactos los grupos completos. No añade originales de curvas ajenas a esos grupos. Un objetivo procesado con `source=missing` ya cuenta como procesado. Recalcular sustituye en los históricos los grupos fecha/curva seleccionados, sin añadir otra versión. No existe un archivo `latest.csv`.

`make-synthetic` escribe `synthetic_vwaps.csv` y `synthetic_truth.csv` en su destino seleccionado; se describen al final. Los logs son registros de texto con fecha/hora, nivel y mensaje, no tablas de precios.

## Salida enriquecida: tabla original con procedencia

`enriched_history.csv` y los enriquecidos diarios comienzan con **todas las columnas originales**, con su nombre y orden originales. Se conservan sus valores y las filas duplicadas. Los nombres físicos de los campos lógicos `reference_date`, `product`, `region`, `unit`, `tenor`, `vwap`, `volume` siguen `[vwap_columns]`; por ejemplo, `tenor2` y `total_volume` pueden ser los nombres de entrada configurados. También se conserva una columna índice de origen o cualquier campo propio. Estos campos arbitrarios no tienen un diccionario universal fijo: mantienen el significado del proveedor.

| Campo de entrada o categoría | Fila original | Fila nueva añadida |
|---|---|---|
| Fecha de referencia | Se conserva su representación; ISO y día/mes/año se interpretan coherentemente | Formato según la primera representación utilizable de fecha en la entrada |
| Producto, región, unidad | Se conservan los valores originales | Identidad normalizada exacta de la curva |
| Tenor (`tenor2`, si se configura así) | Etiqueta original, incluso fuera de objetivos | Etiqueta objetivo configurada |
| VWAP (`vwap`, si se configura así) | Valor original, incluido texto inválido o vacío | Mismo precio que `curve_price`, o vacío si falta |
| Volumen (`total_volume`, si se configura así), `n_trades`, IDs de operación, índice/campos propios | Se conservan | Vacíos; nunca se inventan a partir del precio ni se copian de otra operación |
| `country`, `classification`, `currency`, `area`, `profile` | Se conservan | Solo se copian si ese campo tiene un único valor distinto no vacío en los originales de esta identidad completa |
| `weekday`, si existe | Se conserva | Día de la semana en inglés de la fecha de referencia |
| `periodicity_2`, si existe | Se conserva | `Daily`, `Weekend`, `BOW`, `Weekly`, `BOM`, `Monthly`, `Quarterly`, `Seasonal` o `Annual`, según el tipo de objetivo |

Los nombres de entrada `data_origin`, `estimation_method` y los que empiezan por `curve_` están reservados y se rechazan para evitar sobrescrituras silenciosas.

### Columnas específicas del enriquecido

| Columna | Tipo y valores | Significado |
|---|---|---|
| `data_origin` | Texto: `original`, `estimated`, `missing` | Procedencia del precio utilizable `curve_price`. Un VWAP original finito sigue siendo `original`, incluso cero o negativo. Una fila original inválida puede recibir una estimación en `curve_price`. |
| `estimation_method` | Texto; reglas más abajo | `none` en todo original válido y en todo precio enriquecido no disponible; en otro caso, método que proporciona el precio. |
| `curve_reference_date` | Fecha ISO | Fecha interpretada, independiente del formato original. |
| `curve_product`, `curve_region`, `curve_unit` | Texto | Identidad normalizada de la curva. |
| `curve_tenor` | Texto | Etiqueta original en filas originales; etiqueta objetivo en filas añadidas. |
| `curve_price` | Número o vacío | Precio original, estimado o ausente utilizable. Es el campo que debe usarse cuando la columna VWAP original contiene texto inválido. |
| `curve_source` | Valores de source del motor | `own` para un original válido, aunque el motor no haya calculado esa fila. En otro caso, source del motor o `missing`. |
| `curve_row_type` | Texto: `original`, `original_invalid`, `added` | Indica si la fila física existía, tenía VWAP inutilizable o se añadió. Independiente de la procedencia del precio. |
| `curve_flags` | Texto separado por `;` o vacío | Flags del motor más flags del enriquecido, descritos abajo. |

**Las demás columnas del motor de la sección siguiente se copian con el prefijo `curve_`**, salvo `data_origin` y `estimation_method`, que siguen las reglas del enriquecido. La traza normal completa incluye además `curve_area`, `curve_profile`, `curve_kind`, `curve_period`, `curve_delivery_start`, `curve_delivery_end`, `curve_hours`, `curve_confidence`, `curve_basis_mode`, `curve_configured_basis_mode`, `curve_own_vwap`, `curve_own_volume`, `curve_eex_settle`, `curve_eex_method`, `curve_eex_asof`, `curve_basis`, `curve_basis_local`, `curve_basis_hist`, `curve_cross_adj`, `curve_local_weight`, `curve_anchors`, `curve_cross_from` y **`curve_flag`**. Si el motor no produjo filas, solo están garantizadas las columnas fijas del enriquecido; las trazas opcionales dependen de la tabla del motor recibida.

`curve_flag` copia sin cambios el `flag` singular del motor. `curve_flags` es el campo combinado del enriquecido. Son distintos. En originales válidos, `curve_price`, `curve_source` y, si existen, `curve_own_vwap`/`curve_own_volume` describen esa fila original concreta. Las demás trazas describen el punto correspondiente del motor: pueden estar vacías o referirse a un agregado de originales con el mismo periodo de entrega. Que exista una fila original no significa que se hayan calculado todos sus diagnósticos.

Ejemplo ilustrativo, no observaciones reales de mercado; las tres filas pertenecen a una curva en EUR/MWh. `tenor2` es aquí el nombre configurado para tenor:

| `tenor2` | `vwap` original/de salida | `curve_price` | `data_origin` | `curve_row_type` | `curve_source` | `estimation_method` |
|---|---:|---:|---|---|---|---|
| M+1 | 100 | 100 | original | original | own | none |
| M+2 | 105 | 105 | estimated | added | eex+local | ratio_local |
| M+3 | invalid | vacío | missing | original_invalid | missing | none |

La tercera fila recibe también `original_vwap_missing_or_invalid`. Si pudiera estimarse, su `vwap` original seguiría siendo `invalid`; `curve_price` contendría la estimación y `data_origin` pasaría a `estimated`.

## Salida filled: las 32 columnas del motor

Estas columnas aparecen en `filled_history.csv` y los filled diarios. Hay una fila por etiqueta objetivo resoluble y curva/fecha `fill` activa. Un objetivo no resoluble no genera fila. Varias etiquetas pueden representar el mismo periodo de entrega.

| Columna | Tipo / valores | Significado y casos vacíos |
|---|---|---|
| `reference_date` | Fecha ISO | Fecha de valoración/observación de entrada. |
| `product` | Texto | Identificador normalizado exacto del producto mapeado. |
| `region` | Texto, puede estar vacío | Componente literal de región de la identidad. |
| `unit` | Texto, puede estar vacío | Componente literal de unidad de la identidad y unidad de precios/errores. |
| `area` | Texto | Etiqueta de mercado del mapping. |
| `profile` | Texto | Etiqueta de perfil del mapping, habitualmente `Base` o `Peak`. Las horas siguen la convención hours del mapping, que es independiente. |
| `tenor` | Texto | Etiqueta relativa configurada: `M+1`, `WE`, `BOM`, `Q+1`, `Cal+1`, etc. |
| `kind` | Texto | `Day`, `Weekend`, `BOW`, `Week`, `BOM`, `Month`, `Quarter`, `Season`, `Year`. |
| `period` | Texto | Periodo absoluto: fecha, `WE YYYY-Www`, `YYYY-Www`, `YYYY-MM`, `YYYY-Qn`, `Sum-YY`, `Win-YY/YY`, `Cal-YYYY` o `BOW/BOM inicio..último-día`. |
| `delivery_start` | Fecha ISO | Inicio inclusivo de entrega. |
| `delivery_end` | Fecha ISO | Fin exclusivo de entrega. |
| `hours` | Número, >=0 | Horas según perfil, zona horaria y tipo de objetivo; incorpora las reglas aplicables de calendario/cambio horario. |
| `price` | Número finito o vacío | Precio del motor en `unit`; vacío cuando `source=missing`. |
| `source` | Texto | `own`, `eex+local`, `eex+hist`, `eex+cross`, `eex`, `arbitrage`, `missing`; véase más abajo. |
| `confidence` | Número, 0..1 | Diagnóstico heurístico, **no probabilidad ni precisión calibrada**. Own=1, missing=0, arbitrage=0.4. Con EEX usa 0.4 si no hay ajuste o `0.5+0.4*local_weight`; multiplica por 0.85 si el contrato no es exacto y por 0.9 si el settlement es anterior; redondea a tres decimales. |
| `data_origin` | Texto | `original` para own, `estimated` para precio calculado, incluido EEX sin ajuste, y `missing` en otro caso. |
| `estimation_method` | Texto | `none` para own, `unavailable` para missing o método de cálculo descrito abajo. |
| `basis_mode` | Texto: `ratio`, `additive` | Modo efectivo seleccionado para este objetivo. En filas own/missing no implica que se haya aplicado un ajuste. |
| `configured_basis_mode` | Texto: `auto`, `ratio`, `additive` | Configuración solicitada antes de la selección por objetivo. |
| `own_vwap` | Número o vacío | Precio propio del periodo, posiblemente agregado de duplicados/alias; vacío si no hay contrato propio utilizable con horas positivas. |
| `own_volume` | Número o vacío | Volumen asociado al periodo propio; puede estar agregado o no disponible. |
| `eex_settle` | Número o vacío | Precio EEX del periodo, exacto o reconstruido. No necesariamente un settlement cotizado directamente. |
| `eex_method` | Texto o vacío | `exact`, `strip`, `residual`; vacío si no se obtiene precio del contrato. Con `source=arbitrage` registra cómo se reconstruyó con contratos disponibles de curva/propios, aunque no exista precio EEX. |
| `eex_asof` | Fecha ISO o vacío | Fecha del snapshot EEX usado. Puede preceder a `reference_date` o existir aunque ese snapshot no permita valorar este objetivo. |
| `basis` | Número o vacío | Ajuste final aplicado al EEX, después del límite ratio si procede. Cero significa ajuste real de cero; se distingue del vacío en own/arbitrage/missing. |
| `basis_local` | Número o vacío | Ajuste local de las anclas de hoy antes de combinar; vacío si no está disponible o está desactivado. |
| `basis_hist` | Número o vacío | Ajuste histórico admitido por la política histórica; vacío si no existe, ha caducado, está desactivado o lo rechaza la evaluación automática. |
| `cross_adj` | Número o vacío | Ajuste entre curvas basado en sorpresas actuales elegibles y relaciones aprendidas; vacío si no existe. |
| `local_weight` | Número, 0..1, o vacío | Peso local de la combinación: `W/(W+shrink_k)` si hay evidencia local y cero en otro caso. Vacío si no se calculó ajuste EEX. |
| `anchors` | Texto separado por comas o vacío | Etiquetas de las **tres entradas de ancla con mayor peso local**, no todas las que contribuyen. Una entrada puede contener varias etiquetas alias. No exporta pesos ni la trazabilidad completa. |
| `cross_from` | Texto separado por comas o vacío | Etiquetas de otras curvas utilizadas con correlación redondeada a dos decimales: `product [region='...', unit='...'](0.85)`. No es una tabla de betas ni pesos. |
| `flag` | Texto separado por `;` o vacío | Condiciones del motor descritas abajo. El precio propio se conserva aunque se excluya como ancla. |

En `basis`, `basis_local`, `basis_hist` y `cross_adj`, **ratio se expresa como fracción**: `0.05` significa +5%, y `price = eex_settle * (1 + basis)`. En additive se usa la unidad del precio: `0.05` significa +0.05 EUR/MWh en una curva EUR/MWh, y `price = eex_settle + basis`. No deben combinarse ajustes de distintos modos como si tuvieran la misma unidad. `local_weight` es adimensional en ambos modos. Los precios propios pueden tener vacíos los diagnósticos del ajuste.

### Fuentes y métodos

| `source` | Significado |
|---|---|
| `own` | VWAP propio del mismo periodo de entrega, incluidos alias de tenor admitidos. |
| `eex+local` | EEX con ajuste donde predomina la parte local; también puede contribuir histórico/cross. |
| `eex+hist` | EEX con ajuste donde predomina el histórico; también puede contribuir evidencia local. |
| `eex+cross` | EEX con ajuste donde predomina el previo e interviene información entre curvas. |
| `eex` | Precio EEX sin ajuste de basis. |
| `arbitrage` | Reconstrucción con contratos disponibles de curva/propios cuando EEX no valora el objetivo. No garantiza una curva completa libre de arbitraje. |
| `missing` | Sin estimación disponible, incluido el caso de cero horas de entrega. |

`source` resume la categoría. Para conocer componentes deben consultarse `estimation_method` y los diagnósticos. Los métodos del motor se construyen exactamente así:

- `none`: precio propio; `unavailable`: precio del motor ausente; `eex`: sin componentes de ajuste.
- `ratio_` o `additive_`, seguido de los componentes disponibles en este orden fijo: `local`, `history`, `cross`, separados por guiones bajos. Ejemplos: `additive_local_history` o `ratio_history_cross`. Describe componentes disponibles en el cálculo, no asegura que cada aportación numérica sea distinta de cero.
- `contract_exact`, `contract_strip`, `contract_residual`: reconstrucción sin EEX. `exact` usa el periodo coincidente; `strip` combina periodos contiguos ponderados por horas; `residual` obtiene la cola de un contrato mayor usando su tramo inicial cubierto.
- El enriquecido convierte todo método no disponible en `none`. Si una fila añadida/original inválida recibe precio con `source=own`, el método es `own_equivalent_period`; se marca `estimated` porque esa fila física no contenía precio original utilizable. Todo original válido lleva `none`.

### Flags

Se unen mediante `;`. Vacío significa que no se indicó ninguna de estas condiciones. Pueden coexistir varios.

| Flag | Ubicación | Significado |
|---|---|---|
| `anchor_excluded` | Motor y enriquecido | El periodo propio se rechazó como ancla por los filtros configurados. No sustituye el precio original. En auto, la inestabilidad exclusiva de ratio se trata por modo y no genera necesariamente este flag. |
| `zero_delivery_hours` | Motor y enriquecido | El objetivo no tiene horas según su convención; el motor devuelve missing. El enriquecido conserva los originales. |
| `auto_additive_low_eex` | Motor y enriquecido | Auto eligió additive porque el valor absoluto del EEX objetivo está por debajo de `ratio_eex_floor`. |
| `auto_additive_no_ratio_anchors` | Motor y enriquecido | Auto eligió additive porque hoy solo existen anclas aditivas utilizables. |
| `auto_additive_history_only` | Motor y enriquecido | No hay anclas utilizables hoy y solo el histórico aditivo es utilizable según la política histórica. |
| `ratio_adjustment_limited` | Motor y enriquecido | El basis ratio final se limitó a `max_ratio_deviation`. |
| `unmapped_product` | Flags combinados del enriquecido | No existe mapping para la identidad completa product/region/unit. |
| `mapping_off` | Flags combinados del enriquecido | El mapping está desactivado. |
| `mapping_unassigned` | Flags combinados del enriquecido | El mapping no está off pero no tiene archivo EEX asignado. |
| `mapping_helper` | Flags combinados del enriquecido | El mapping asignado solo actúa como helper. |
| `original_vwap_missing_or_invalid` | Flags combinados del enriquecido | El VWAP de la fila física original es vacío, inválido o no finito. |
| `unit_missing` | Flags combinados, filas añadidas | La unidad de identidad está vacía; no se ha inventado otra. |
| `metadata_ambiguous:<column>` | Flags combinados, filas añadidas | Hay más de un valor original no vacío de ese metadato para la identidad; se deja vacío. `<column>` es country, classification, currency, area o profile. |

Los flags de motivo auto se emiten al calcular una estimación basada en EEX, no simplemente porque una fila propia tenga modo efectivo additive. La falta/antigüedad del EEX también se registra en logs; no existe un flag específico de EEX antiguo en este esquema. Debe compararse `eex_asof` con `reference_date`.

## Consistencia

`consistency_history.csv` solo contiene comparaciones disponibles: Quarter frente a meses, Season frente a trimestres y Year frente a trimestres. La ausencia de fila significa que no se produjo esa comparación, no prueba consistencia. Se informa de diferencias sin forzar los precios.

| Columnas | Significado |
|---|---|
| `reference_date`, `product`, `region`, `unit` | Fecha e identidad completa. |
| `tenor`, `period` | Etiqueta del objetivo agregado y periodo absoluto. |
| `price`, `source` | Precio agregado y source del motor. |
| `from_parts` | Precio reconstruido con periodos menores ponderados por horas. |
| `deviation` | `price - from_parts`, en la unidad de la curva. |

## Backtest

`backtest_loo.csv` contiene predicciones individuales leave-one-out. Se oculta cada periodo propio elegible antes de predecirlo con la configuración; las alternativas diagnósticas pueden tener distinta disponibilidad. Las filas comparten observado pero cambian de método.

| Columna | Significado / valores |
|---|---|
| `reference_date`, `product`, `region`, `unit`, `tenor`, `kind` | Fecha, identidad completa y contrato oculto. `tenor` puede combinar etiquetas alias propias. |
| `group` | `short` (Day/Weekend/BOW/Week), `month` (BOM/Month), `quarter` (Quarter), `long` (Season/Year). |
| `own` | Precio propio oculto, posiblemente agregado por periodo de entrega. |
| `volume` | Volumen propio asociado; puede estar vacío. |
| `n_other_anchors` | Anclas restantes del conjunto resumen configurado; no cuenta todas las filas originales ni indica pesos por método. |
| `configured_basis_mode` | Configuración `auto`, `ratio` o `additive`. |
| `method` | `eex`, `pipeline_configured` o `local_<mode>`, `hist_<mode>`, `blend_<mode>`, `local_corr_<mode>`, `blend_corr_<mode>`, `hist_cross_<mode>`, con `<mode>` ratio/additive. Aparecen cuando hay datos y se ejecuta su rama. |
| `basis_mode` | Modo efectivo ratio/additive; vacío en la referencia `eex`. |
| `pred` | Predicción en `unit`. |
| `error` | `pred - own`; positivo significa sobreestimación. |

`pipeline_configured` aplica la configuración real después de ocultar la observación. Las alternativas con nombre propio son comparaciones diagnósticas: no todas siguen del mismo modo los interruptores/límites del cálculo desplegado.

`backtest_report.csv` agrupa por `unit`, `method`, `group`; `group=ALL` reúne los grupos de contratos dentro de la misma unidad. Las métricas absolutas mantienen esa unidad.

| Columna | Significado |
|---|---|
| `unit`, `method`, `group` | Claves de agrupación de las métricas. |
| `n` | Número de predicciones del método/grupo. |
| `mae`, `bias`, `rmse` | Error absoluto medio, error firmado medio y raíz del error cuadrático medio. |
| `n_paired` | Predicciones emparejadas con EEX por fecha/identidad completa/tenor. |
| `mae_paired`, `mae_eex_paired` | MAE del método y de EEX exactamente sobre esas observaciones comunes. Vacío si no existe métrica emparejada. |
| `mae_improvement` | `mae_eex_paired - mae_paired`; positivo indica mejora frente a EEX. |

Se redondean las métricas a cuatro decimales. `backtest --truth` muestra, sin guardar otro informe, `unit`, `source`, `n`, `mae`, `bias` frente a la verdad sintética, excluyendo celdas con precio propio.

## Calibración de parámetros

`tuning_calibration.csv` informa de todos los candidatos de una rejilla finita en fechas anteriores. `tuning_validation.csv` informa únicamente del ganador en fechas posteriores reservadas. Los parámetros quedan fijados antes de validar; las observaciones originales anteriores sí pueden actualizar el histórico cronológicamente. Ninguna salida modifica la configuración de producción.

Ambas tablas contienen:

| Columna | Significado / valores |
|---|---|
| `trial_id` | Posición del candidato en la rejilla, comenzando en 1. |
| `scope` | `overall` o `unit`. |
| `unit` | Unidad en filas unit; vacío en overall. |
| `n_paired`, `n_curves`, `n_paired_dates` | Observaciones comunes, identidades completas distintas y fechas con observaciones emparejadas. |
| `score` | Media con igual peso por curva del cociente MAE modelo / MAE EEX de cada curva. Menor es mejor; 1 iguala la referencia. Si MAE EEX=0, el cociente vale 1 si MAE modelo=0 y, en otro caso, infinito. |
| `normalized_skill` | `1 - score`; positivo indica mejora normalizada. |
| `reference_date_from`, `reference_date_to` | Primera y última fecha de observación asignada a calibración/validación; pueden abarcar más fechas que las que realmente tienen predicciones emparejadas. |
| `basis_mode` | Configuración del candidato: `auto`, `ratio`, `additive`; no es el modo efectivo por objetivo. |
| `tau_log`, `shrink_k` | Parámetros positivos del método candidato. |
| `layer_hist` | Política candidata: `auto`, `on`, `off`. |
| `layer_correlation`, `layer_cross` | Interruptores booleanos del candidato. |
| `mae_model`, `rmse_model`, `bias_model` | Errores absolutos del pipeline configurado en la unidad de filas unit; vacíos en overall para no mezclar divisas/unidades. |
| `mae_eex`, `rmse_eex`, `bias_eex` | Errores de referencia EEX con la misma regla y las mismas observaciones emparejadas. |
| `selected` | Booleano; true en el ganador de calibración y todas sus filas de validación. |

`tuning_selected.json` contiene estas claves principales:

| Clave | Contenido |
|---|---|
| `selected_parameters` | Cambio de config propuesto: `method.{basis_mode,tau_log,shrink_k}` y `layers.{hist,correlation,cross}`. |
| `metadata` | Registro de evaluación detallado abajo. |
| `base_configuration` | Copia completa de Config: rutas resueltas, alias de campos, objetivos, parámetros del método/capas y convenciones. |
| `input_pattern` | Ruta/patrón real de VWAP utilizado. |
| `selection` | Texto que indica que solo calibración selecciona parámetros y validación se evalúa después. |
| `config_changed` | `false`; el comando no aplica automáticamente la propuesta. |

Todas las claves de `metadata`:

- `objective` = `mean_per_curve_mae_model_over_mae_eex`; `evaluated_method` = `pipeline_configured`; `baseline` = `eex`.
- `parameter_grid`: rejilla solicitada de campos y listas; `selection_scope`: mejor score de calibración dentro de esa rejilla; `lower_score_is_better`: true; `tie_break`: `first_candidate_in_grid_order`.
- `calibration_start`, `calibration_end`, `validation_start`, `validation_end`: límites de fechas de observación asignadas. `calibration_days`, `validation_days`: número de fechas distintas asignadas, no duración en días naturales.
- `n_trials`, `selected_trial_id`, `calibration_score`, `validation_score`: número de candidatos, ID ganador y puntuaciones.
- `calibration_n_paired`, `validation_n_paired`: número de predicciones emparejadas.
- `calibration_paired_days`, `validation_paired_days`, `calibration_paired_start`, `calibration_paired_end`, `validation_paired_start`, `validation_paired_end`: fechas que realmente aportan observaciones comunes.
- `warmup_days` = 0; `validation_protocol` = `fixed_selected_parameters_with_chronological_original_history_updates`.

Las claves de `base_configuration` son `base_dir`, `vwap_input`, `mapping_file`, `eex_curves_dir`, `output_dir`; `layer_local`, `layer_correlation`, `layer_cross`, `layer_hist`, `layer_arbitrage`; `max_stale_days`, `warn_stale_days`, `timezones`, `tenors`, `day_convention`, `weekend_offset`; `basis_mode`, `min_volume`, `tau_log`, `other_kind_weight`, `shrink_k`, `ewma_halflife_days`, `max_anchor_dev`, `hist_auto_min_obs`; `corr_halflife_days`, `corr_prior_obs`, `cross_min_corr`, `cross_min_obs`, `cross_halflife_days`; `warmup_days`, `vwap_columns`, `ratio_eex_floor`, `max_ratio_deviation`, `hist_max_age_days`. Son configuración, no resultados medidos; véanse [ALGORITMO.md](ALGORITMO.md) y [config.toml](config.toml). Las rutas se convierten en texto. Los diagnósticos no finitos se guardan como JSON `null`; los score CSV pueden mostrar `inf`/`-inf` en el caso anterior de referencia con error cero. Esto no permite precios de producción no finitos.

## Archivos sintéticos

Son datos explícitamente simulados, nunca operaciones reales. `synthetic_vwaps.csv` contiene `reference_date`, `weekday`, `product`, `country`, `region`, `classification`, `unit`, `periodicity_2`, `tenor2`, `vwap`, `total_volume`, `n_trades`. Sus significados coinciden con el diccionario de entrada anterior, pero se generan precios, volúmenes, operaciones y disponibilidad de observaciones. `reference_date` usa día/mes/año, `country` usa el área mapeada y classification es `<profile> load`.

`synthetic_truth.csv` contiene `date` (fecha de referencia), `product`, `region`, `unit`, `tenor`, `period`, `delivery_start`, `delivery_end`, `truth` (precio completo simulado) y `eex` (precio EEX usado para generarlo). Los alias del mismo periodo comparten una sola verdad. Ambos precios usan la unidad de la curva.
