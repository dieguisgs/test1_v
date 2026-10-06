# Output dictionary

Spanish version: [OUTPUT.es.md](OUTPUT.es.md). Calculation rules: [ALGORITHM.md](ALGORITHM.md).

All curve keys use **reference date + product + region + unit + tenor label**. A blank region or unit is a literal identity value. Prices and absolute errors use the row's `unit`; currencies are not converted. CSV files use UTF-8 with BOM, comma separators and a header. Empty numeric/date cells mean unavailable or not applicable, not zero. Zero and negative prices are valid finite values.

## Files

Paths below are relative to `[paths].output_dir`. Files appear when the corresponding command has results; an empty consistency result need not create a file.

```text
output/
  enriched_history.csv          Original rows plus added points across processed dates
  enriched/YYYY-MM-DD.csv        Same enriched schema for one reference date
  filled_history.csv            Engine target points across processed dates
  filled/YYYY-MM-DD.csv          Same engine schema for one reference date
  consistency_history.csv       Available aggregate-versus-parts comparisons
  backtest_loo.csv               Individual held-out predictions
  backtest_report.csv            Backtest metrics
  tuning_calibration.csv         Every candidate's calibration scores
  tuning_validation.csv          Selected candidate's later-date scores
  tuning_selected.json           Proposed parameters and evaluation metadata
  _logs/vwaps_YYYY-MM-DD.log      Command execution log
```

`daily` and `refill` preserve original rows, including unmapped/off/helper curves, in enriched output. `catchup` updates only pending active `fill` date/curve groups; already complete groups remain intact. It does not add raw rows of unrelated curves. A processed target with `source=missing` is already processed. Recalculation replaces the selected date/curve groups in histories, rather than appending another version. There is no `latest.csv` file.

The `make-synthetic` command writes `synthetic_vwaps.csv` and `synthetic_truth.csv` to its selected destination (see below). Logs are text records with timestamp, severity and message, not a tabular price output.

## Enriched output: the original table with provenance

`enriched_history.csv` and daily enriched files begin with **every original input column**, in its original spelling and order. Original row values and duplicate rows are retained. The physical columns for the logical fields `reference_date`, `product`, `region`, `unit`, `tenor`, `vwap`, `volume` follow `[vwap_columns]`; for example `tenor2` and `total_volume` can be the configured input names. A source index column or any custom field is retained too. These arbitrary fields cannot have a fixed universal dictionary: their original meaning remains the supplier's meaning.

| Input field or category | Original row | Newly added row |
|---|---|---|
| Reference date | Original representation retained; ISO and day/month/year parse consistently | Formatted following the first usable input date representation |
| Product, region, unit | Original values retained | Exact normalized curve identity |
| Tenor (`tenor2`, if configured) | Original label retained, even outside targets | Configured target label |
| VWAP (`vwap`, if configured) | Original value retained, including invalid text or an empty value | Same price as `curve_price`, or empty if missing |
| Volume (`total_volume`, if configured), `n_trades`, transaction IDs, index/custom fields | Preserved | Empty; never invented from prices or copied from another trade |
| `country`, `classification`, `currency`, `area`, `profile` | Preserved | Copied only when that field has one distinct nonempty value in the original data for this complete curve identity |
| `weekday`, if supplied | Preserved | English weekday of the reference date |
| `periodicity_2`, if supplied | Preserved | `Daily`, `Weekend`, `BOW`, `Weekly`, `BOM`, `Monthly`, `Quarterly`, `Seasonal` or `Annual`, according to target kind |

Input names `data_origin`, `estimation_method` and names starting with `curve_` are reserved and rejected to prevent silent overwriting.

### Enrichment-specific columns

| Column | Type and values | Meaning |
|---|---|---|
| `data_origin` | Text: `original`, `estimated`, `missing` | Origin of the usable `curve_price`. A finite original VWAP always remains `original`, including zero or negative values. An invalid original row can have an estimated price in `curve_price`. |
| `estimation_method` | Text; method rules below | `none` on every valid original row and every unavailable enriched price; otherwise the method used to supply that price. |
| `curve_reference_date` | ISO date | Parsed reference date, independent of the original date's formatting. |
| `curve_product`, `curve_region`, `curve_unit` | Text | Normalized curve identity. |
| `curve_tenor` | Text | Original label for an original row; target label for an added row. |
| `curve_price` | Number or empty | Usable original, estimated or missing price. Use this field when the original VWAP column contains invalid text. |
| `curve_source` | Engine source enum below | `own` for a valid original row, even when the engine did not calculate that row. Otherwise the engine source, or `missing`. |
| `curve_row_type` | Text: `original`, `original_invalid`, `added` | Whether the physical row already existed, contained an unusable VWAP, or was appended. Independent of price origin. |
| `curve_flags` | Semicolon-separated text or empty | Engine flags plus enrichment flags, listed below. |

**Every other engine column in the next section is copied with `curve_` prefixed**, except `data_origin` and `estimation_method`, which use the enrichment semantics above. Thus the full normal trace also includes `curve_area`, `curve_profile`, `curve_kind`, `curve_period`, `curve_delivery_start`, `curve_delivery_end`, `curve_hours`, `curve_confidence`, `curve_basis_mode`, `curve_configured_basis_mode`, `curve_own_vwap`, `curve_own_volume`, `curve_eex_settle`, `curve_eex_method`, `curve_eex_asof`, `curve_basis`, `curve_basis_local`, `curve_basis_hist`, `curve_cross_adj`, `curve_local_weight`, `curve_anchors`, `curve_cross_from` and **`curve_flag`**. If no engine rows were produced, only the fixed enrichment columns are guaranteed; optional trace columns depend on the engine table supplied.

`curve_flag` is the engine's singular `flag` copied unchanged. `curve_flags` is the combined enrichment field. Do not confuse them. On valid original rows, `curve_price`, `curve_source`, and, when present, `curve_own_vwap`/`curve_own_volume` describe that exact original row. Other trace fields describe the matching engine point and can be empty, or refer to an aggregate of repeated original delivery periods. The presence of an original row does not imply that all diagnostics were computed.

Illustrative rows, not actual market observations; all three use the same EUR/MWh curve. Here `tenor2` is the configured tenor column:

| `tenor2` | Original/output `vwap` | `curve_price` | `data_origin` | `curve_row_type` | `curve_source` | `estimation_method` |
|---|---:|---:|---|---|---|---|
| M+1 | 100 | 100 | original | original | own | none |
| M+2 | 105 | 105 | estimated | added | eex+local | ratio_local |
| M+3 | invalid | empty | missing | original_invalid | missing | none |

The third row also receives `original_vwap_missing_or_invalid`. If a price were available for it, its original `vwap` would still read `invalid`; `curve_price` would hold the estimate and `data_origin` would become `estimated`.

## Filled output: all 32 engine columns

These fields are written to `filled_history.csv` and daily filled files. There is one row per resolvable configured target label and active `fill` curve/date. An unresolvable target produces no row. Different labels can resolve to the same delivery period.

| Column | Type / values | Meaning and empty cases |
|---|---|---|
| `reference_date` | ISO date | Valuation/input observation date. |
| `product` | Text | Exact normalized mapped product identifier. |
| `region` | Text, possibly blank | Literal region component of curve identity. |
| `unit` | Text, possibly blank | Literal unit component of curve identity; price/error unit. |
| `area` | Text | Mapping's market area label. |
| `profile` | Text | Mapping's profile label, commonly `Base` or `Peak`. Delivery hours follow the mapping's separate hours convention. |
| `tenor` | Text | Configured relative label, such as `M+1`, `WE`, `BOM`, `Q+1`, `Cal+1`. |
| `kind` | Text | `Day`, `Weekend`, `BOW`, `Week`, `BOM`, `Month`, `Quarter`, `Season`, `Year`. |
| `period` | Text | Absolute delivery label: date, `WE YYYY-Www`, `YYYY-Www`, `YYYY-MM`, `YYYY-Qn`, `Sum-YY`, `Win-YY/YY`, `Cal-YYYY`, or `BOW/BOM start..last-day`. |
| `delivery_start` | ISO date | Inclusive delivery start. |
| `delivery_end` | ISO date | Exclusive delivery end. |
| `hours` | Number, >=0 | Delivery hours under the mapped profile, timezone and target kind; includes applicable calendar/DST rules. |
| `price` | Finite number or empty | Engine price in `unit`; empty with `source=missing`. |
| `source` | Text | `own`, `eex+local`, `eex+hist`, `eex+cross`, `eex`, `arbitrage`, `missing`; see below. |
| `confidence` | Number, 0..1 | Heuristic diagnostic, **not a probability or calibrated accuracy measure**. Own=1, missing=0, arbitrage=0.4. EEX-based values use 0.4 for raw EEX or `0.5+0.4*local_weight`, reduced by 0.85 for a non-exact contract and 0.9 for an earlier settlement; rounded to three decimals. |
| `data_origin` | Text | `original` for own, `estimated` for a calculated price (including raw EEX), `missing` otherwise. |
| `estimation_method` | Text | `none` for own, `unavailable` for missing, or a calculation method below. |
| `basis_mode` | Text: `ratio`, `additive` | Effective mode selected for this target. On own/missing rows it does not mean that an adjustment was applied. |
| `configured_basis_mode` | Text: `auto`, `ratio`, `additive` | Requested configuration, before target-specific selection. |
| `own_vwap` | Number or empty | Own price for this delivery period, potentially an aggregate of duplicate rows/aliases; empty without a usable positive-hour own contract. |
| `own_volume` | Number or empty | Volume associated with that own period; may be aggregated or unavailable. |
| `eex_settle` | Number or empty | EEX price for this delivery period, exact or reconstructed. Not necessarily a directly quoted settlement. |
| `eex_method` | Text or empty | `exact`, `strip`, `residual`; empty without a priced contract. For `source=arbitrage` it records the reconstruction method using already available curve/own contracts, even though no EEX price exists. |
| `eex_asof` | ISO date or empty | Date of the EEX snapshot used. Can be earlier than `reference_date`, or present even if that snapshot cannot price this particular target. |
| `basis` | Number or empty | Final adjustment applied to EEX, after any ratio limit. Zero is a real adjustment of zero, distinct from empty on own/arbitrage/missing rows. |
| `basis_local` | Number or empty | Today's local anchor adjustment before blending; empty when unavailable or disabled. |
| `basis_hist` | Number or empty | Historical adjustment actually admitted by the history policy; empty when unavailable, expired, disabled or rejected by the automatic skill gate. |
| `cross_adj` | Number or empty | Cross-curve adjustment from eligible current surprises and learned relationships; empty when absent. |
| `local_weight` | Number, 0..1, or empty | Local weight in the blend; `W/(W+shrink_k)` when local evidence exists, otherwise zero. Empty when no EEX adjustment was calculated. |
| `anchors` | Comma-separated text or empty | Labels of the **top three anchor entries by local weight**, not every contributing anchor. An entry can itself combine alias labels. No weights or complete lineage are exported here. |
| `cross_from` | Comma-separated text or empty | Used helper/other curve labels with correlation rounded to two decimals: `product [region='...', unit='...'](0.85)`. Not a table of beta coefficients or weights. |
| `flag` | Semicolon-separated text or empty | Engine conditions listed below. Own values remain intact even when excluded as anchors. |

For `basis`, `basis_local`, `basis_hist` and `cross_adj`, **ratio values are fractions**: `0.05` means +5%, and `price = eex_settle * (1 + basis)`. Additive values use the price unit: `0.05` means +0.05 EUR/MWh on an EUR/MWh curve, and `price = eex_settle + basis`. Never combine adjustments from different modes as if they shared units. `local_weight` is dimensionless in both modes. Own values need not have populated basis diagnostics.

### Sources and methods

| `source` | Meaning |
|---|---|
| `own` | Own VWAP for the same delivery period, including supported tenor aliases. |
| `eex+local` | EEX with a local-led adjustment; a historical/cross component can also contribute. |
| `eex+hist` | EEX with a history-led adjustment; local evidence can also contribute. |
| `eex+cross` | EEX with a prior-led adjustment that includes cross-curve information. |
| `eex` | EEX price without a basis adjustment. |
| `arbitrage` | Reconstructed from available curve/own contracts when EEX cannot price the target. Does not guarantee an arbitrage-free entire curve. |
| `missing` | No available estimate, including zero delivery hours. |

`source` is a summary category. For component detail, use `estimation_method` and the diagnostic columns. Engine methods are constructed exactly as follows:

- `none`: own price; `unavailable`: engine price missing; `eex`: no adjustment components.
- `ratio_` or `additive_`, followed by the available component names in this fixed order: `local`, `history`, `cross`, joined with underscores. For example `additive_local_history` or `ratio_history_cross`. This describes available components in the calculation, not a claim that each numerical contribution is nonzero.
- `contract_exact`, `contract_strip`, `contract_residual`: non-EEX contract reconstruction. `exact` uses the matching period, `strip` combines contiguous periods by delivery hours, and `residual` extracts the tail of a larger contract using the covered head.
- Enriched output changes any unavailable method to `none`. A supplied price from `source=own` on an added/invalid original row becomes `own_equivalent_period`; it is marked `estimated` because that physical row did not contain a usable original price. Every valid original row instead has method `none`.

### Flags

Flags are joined with `;`. An empty field means no listed condition. Several can coexist.

| Flag | Location | Meaning |
|---|---|---|
| `anchor_excluded` | Engine and enriched | Own delivery period was rejected as anchor by configured eligibility checks. Does not replace its original price. In auto mode, ratio-only unsuitability is handled per mode and is not necessarily an exclusion flag. |
| `zero_delivery_hours` | Engine and enriched | Target has no delivery hours under its convention; engine returns missing. Raw original rows remain preserved in enriched output. |
| `auto_additive_low_eex` | Engine and enriched | Auto selected additive because target absolute EEX is below `ratio_eex_floor`. |
| `auto_additive_no_ratio_anchors` | Engine and enriched | Auto selected additive because only additive anchors are usable today. |
| `auto_additive_history_only` | Engine and enriched | No usable anchors today; only additive history is currently usable under the history policy. |
| `ratio_adjustment_limited` | Engine and enriched | Final ratio basis was clipped to configured `max_ratio_deviation`. |
| `unmapped_product` | Enriched combined flags | No mapping matches the full product/region/unit identity. |
| `mapping_off` | Enriched combined flags | Matching mapping is off. |
| `mapping_unassigned` | Enriched combined flags | Matching non-off mapping has no assigned EEX file. |
| `mapping_helper` | Enriched combined flags | Matching assigned mapping is helper-only. |
| `original_vwap_missing_or_invalid` | Enriched combined flags | Physical original row's VWAP is empty, invalid or nonfinite. |
| `unit_missing` | Enriched combined flags, added rows | Curve identity has an empty unit; nothing was invented. |
| `metadata_ambiguous:<column>` | Enriched combined flags, added rows | More than one nonempty original metadata value exists for this identity; the field was left empty. `<column>` is one of country, classification, currency, area, profile. |

Auto rationale flags are emitted when an EEX-based estimate takes that branch, not simply because an own row has effective additive mode. Missing/stale EEX also produces log messages; there is no separate stale-EEX flag in this schema. Compare `eex_asof` with `reference_date`.

## Consistency output

`consistency_history.csv` contains only available comparisons: Quarter against months, Season against quarters, Year against quarters. No row means no such comparison was produced, not proof of consistency. Prices are reported, not forced into agreement.

| Columns | Meaning |
|---|---|
| `reference_date`, `product`, `region`, `unit` | Date and full curve identity. |
| `tenor`, `period` | Aggregate target label and absolute period. |
| `price`, `source` | Aggregate price and its engine source. |
| `from_parts` | Delivery-hour-weighted price reconstructed from finer periods. |
| `deviation` | `price - from_parts`, in the curve's unit. |

## Backtest outputs

`backtest_loo.csv` holds individual leave-one-out predictions. Each eligible own delivery period is hidden before the configured pipeline predicts it; diagnostic alternatives can have different availability. Rows share truth but differ by method.

| Column | Meaning / values |
|---|---|
| `reference_date`, `product`, `region`, `unit`, `tenor`, `kind` | Observation date, full identity and held-out contract. `tenor` can combine own alias labels. |
| `group` | `short` (Day/Weekend/BOW/Week), `month` (BOM/Month), `quarter` (Quarter), `long` (Season/Year). |
| `own` | Held-out own price, possibly aggregated by delivery period. |
| `volume` | Associated own volume; can be empty. |
| `n_other_anchors` | Other anchors in the configured summary set, not a count of every original row or a per-method weight. |
| `configured_basis_mode` | Configured `auto`, `ratio` or `additive`. |
| `method` | `eex`, `pipeline_configured`, or `local_<mode>`, `hist_<mode>`, `blend_<mode>`, `local_corr_<mode>`, `blend_corr_<mode>`, `hist_cross_<mode>` where `<mode>` is ratio/additive. Methods only appear when their branch/data is available. |
| `basis_mode` | Effective ratio/additive mode; blank for baseline `eex`. |
| `pred` | Predicted price in `unit`. |
| `error` | `pred - own`; positive means overprediction. |

`pipeline_configured` applies the actual configuration after hiding the observation. The named alternatives are diagnostic comparisons and are not all constrained by the deployed layer switches/guards in the same way.

`backtest_report.csv` groups by `unit`, `method`, `group`; `group=ALL` combines contract groups within that same unit. Every absolute metric remains in its group's unit.

| Column | Meaning |
|---|---|
| `unit`, `method`, `group` | Metric grouping keys. |
| `n` | Number of predictions for that method/group. |
| `mae`, `bias`, `rmse` | Mean absolute error, mean signed error, root mean squared error. |
| `n_paired` | Predictions matched to the EEX baseline on date/full identity/tenor. |
| `mae_paired`, `mae_eex_paired` | Method and EEX MAE on exactly those matched observations. Empty when no paired metric exists. |
| `mae_improvement` | `mae_eex_paired - mae_paired`; positive means improvement over EEX. |

Metrics are rounded to four decimals. Optional `backtest --truth` prints, without a separate saved report, `unit`, `source`, `n`, `mae`, `bias` against synthetic truth, excluding own-priced cells.

## Tuning outputs

`tuning_calibration.csv` reports all finite-grid candidates on earlier dates. `tuning_validation.csv` reports only the selected candidate on reserved later dates. Parameters are fixed before validation; previous original observations can still update history chronologically. Neither output changes production configuration.

Both tables contain:

| Column | Meaning / values |
|---|---|
| `trial_id` | Candidate's 1-based position in the grid. |
| `scope` | `overall` or `unit`. |
| `unit` | Unit for scope=unit; blank for overall. |
| `n_paired`, `n_curves`, `n_paired_dates` | Matched observations, distinct complete curve identities, and dates with paired observations. |
| `score` | Mean, giving each curve equal weight, of that curve's model MAE / EEX MAE. Lower is better; 1 matches baseline. Baseline MAE=0 gives ratio 1 if model MAE=0, otherwise infinity. |
| `normalized_skill` | `1 - score`; positive means normalized improvement. |
| `reference_date_from`, `reference_date_to` | First and last observation dates allocated to this calibration/validation block, which can be wider than the dates with paired predictions. |
| `basis_mode` | Candidate setting: `auto`, `ratio`, `additive`; not the per-target effective mode. |
| `tau_log`, `shrink_k` | Positive candidate method parameters. |
| `layer_hist` | Candidate history setting: `auto`, `on`, `off`. |
| `layer_correlation`, `layer_cross` | Candidate Boolean switches. |
| `mae_model`, `rmse_model`, `bias_model` | Configured-pipeline absolute errors in the unit on unit rows; empty on overall rows to avoid mixing currency/price units. |
| `mae_eex`, `rmse_eex`, `bias_eex` | EEX baseline errors under the same rule and on the same paired observations. |
| `selected` | Boolean; true for the calibration winner and all its validation rows. |

`tuning_selected.json` has these top-level keys:

| Key | Contents |
|---|---|
| `selected_parameters` | Suggested config patch: `method.{basis_mode,tau_log,shrink_k}` and `layers.{hist,correlation,cross}`. |
| `metadata` | Evaluation record detailed below. |
| `base_configuration` | Complete Config snapshot, including resolved paths, field aliases, targets, method/layer parameters and conventions. |
| `input_pattern` | Actual VWAP input path/glob used. |
| `selection` | Text stating that only calibration dates choose parameters and validation follows selection. |
| `config_changed` | `false`; this command never applies the proposal automatically. |

All `metadata` keys:

- `objective` = `mean_per_curve_mae_model_over_mae_eex`; `evaluated_method` = `pipeline_configured`; `baseline` = `eex`.
- `parameter_grid`: requested field-to-list grid; `selection_scope`: best calibration score within that supplied grid; `lower_score_is_better`: true; `tie_break`: `first_candidate_in_grid_order`.
- `calibration_start`, `calibration_end`, `validation_start`, `validation_end`: allocated observation-date boundaries. `calibration_days`, `validation_days`: distinct allocated dates, not calendar-day duration.
- `n_trials`, `selected_trial_id`, `calibration_score`, `validation_score`: candidate count, winner ID and scores.
- `calibration_n_paired`, `validation_n_paired`: matched prediction counts.
- `calibration_paired_days`, `validation_paired_days`, `calibration_paired_start`, `calibration_paired_end`, `validation_paired_start`, `validation_paired_end`: dates actually contributing matched observations.
- `warmup_days` = 0; `validation_protocol` = `fixed_selected_parameters_with_chronological_original_history_updates`.

`base_configuration` keys are `base_dir`, `vwap_input`, `mapping_file`, `eex_curves_dir`, `output_dir`; `layer_local`, `layer_correlation`, `layer_cross`, `layer_hist`, `layer_arbitrage`; `max_stale_days`, `warn_stale_days`, `timezones`, `tenors`, `day_convention`, `weekend_offset`; `basis_mode`, `min_volume`, `tau_log`, `other_kind_weight`, `shrink_k`, `ewma_halflife_days`, `max_anchor_dev`, `hist_auto_min_obs`; `corr_halflife_days`, `corr_prior_obs`, `cross_min_corr`, `cross_min_obs`, `cross_halflife_days`; `warmup_days`, `vwap_columns`, `ratio_eex_floor`, `max_ratio_deviation`, `hist_max_age_days`. These are configuration values, not measured outcomes; see [ALGORITHM.md](ALGORITHM.md) and [config.toml](config.toml) for their meaning. Paths become strings. Nonfinite diagnostic numbers are serialized as JSON `null`; CSV diagnostic scores may display `inf`/`-inf` for the zero-baseline case above. This does not permit nonfinite production prices.

## Synthetic files

These files are explicitly simulated data, never real transactions. `synthetic_vwaps.csv` contains `reference_date`, `weekday`, `product`, `country`, `region`, `classification`, `unit`, `periodicity_2`, `tenor2`, `vwap`, `total_volume`, `n_trades`. Their meanings match the input dictionary above, but prices, volumes, trades and observation availability are generated. `reference_date` uses day/month/year, `country` uses mapped area, and classification is `<profile> load`.

`synthetic_truth.csv` contains `date` (reference date), `product`, `region`, `unit`, `tenor`, `period`, `delivery_start`, `delivery_end`, `truth` (simulated complete price) and `eex` (EEX price used to generate it). Aliases for the same delivery period share one truth. Both prices use the stated curve unit.
