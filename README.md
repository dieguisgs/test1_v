# VWAP curve completion


[Output dictionary](OUTPUT.md) · [Diccionario en español](OUTPUT.es.md)
[Español](README.es.md) · [Algorithm](ALGORITHM.md) · [Algoritmo en español](ALGORITMO.md)

[GitHub repository](https://github.com/dieguisgs/test1_v)

Complete missing power-curve prices for each **reference date, product, region, unit and target
tenor**, using observed VWAPs and EEX settlements. The enriched output retains original rows
and columns, adds absent curve rows, and identifies each price's origin and estimation method.

The curve identity is **`(product, region, unit)`**. The same product name in another region
or unit has separate mapping, anchors, history and results. Input values are preserved;
internal matching trims surrounding whitespace without changing case or spelling. Empty
region/unit values are literal identities, never wildcards. Product names cannot be empty.

## Install

Requires Python 3.11 or later. From the project directory, use either:

```powershell
uv sync
```

or a virtual environment with pip:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install "numpy>=1.26" "pandas>=2.2" "openpyxl>=3.1" "pytest>=8.0"
```

The examples below use `python` from that environment. In PowerShell, activate it with `.venv\Scripts\Activate.ps1`, use `.venv\Scripts\python.exe` directly, or prefix commands with `uv run` when using uv.

## Configure the real input

There is **one configuration file, `config.toml`**, both here and in the portable ZIP. Its
initial input path is `data/vwaps.xlsx`: edit that path to the real accumulated input on the
destination machine. All ordinary `python run.py ...` commands use this configuration.
For a separate demonstration run, explicitly pass `--vwap data/synthetic_vwaps.csv` if that
synthetic file has been generated; the default never silently selects demonstration data.

The portable ZIP excludes the local mapping, synthetic inputs, EEX data, virtual environment and generated outputs. Install dependencies on the destination machine, supply your input and EEX files, and generate the mapping there.

Edit `[paths]` in the selected configuration:

```toml
[paths]
vwap_input = "data/vwaps.xlsx"
mapping = "mappings/products.csv"
eex_curves_dir = "../eex_scraper/output/curves/POWER"
output_dir = "output"
```

Paths are relative to the configuration file; absolute paths also work. Input can be CSV or Excel, including a file pattern such as `data/vwaps_*.csv`. `--vwap` overrides its path for one command.

The input uses long format, with one observation per row:

| Columns | Meaning |
|---|---|
| `reference_date`, `product`, `region`, `unit`, `tenor2`, `vwap` | Required date, complete curve identity, relative tenor and observed price. Region/unit columns must exist, even if a literal blank value is appropriate. Dates must be valid; missing or invalid prices can be completed. |
| `total_volume` | Optional volume used when combining observations and weighting anchors. |
| `weekday`, `country`, `classification`, `periodicity_2`, `n_trades` | Other original metadata; retained along with every input column. Region/unit are identity fields, not merely descriptive metadata. |

Examples of tenor labels are `D+1`, `WE`, `M+1`, `Q+1` and `Cal+1`. Adjust `[vwap_columns]` if your column names differ, and `[targets]` for the tenors to complete. EEX files require `tradeDate`, `maturityType`, `deliveryStart` and `settlPx`.

`curves/POWER/<area>/Base.csv` and `Peak.csv` are long files containing the history accumulated
locally for each EEX product, not just one date. A repeated date is normal: each date has many
delivery contracts. The scraper rebuilds these views from its contract files in `table_data/`;
it does not append to the curve CSV. This one-file-per-area/product layout remains appropriate
for the current small files and the VWAP reader. Daily partitions are not required; a future
move to monthly partitions or Parquet would need changes to both writing and reading.

The target list is editable directly in the configuration; no Python changes are required:

```toml
[targets]
tenors = ["D+1", "D+2", "WE", "M+1", "M+2", "M+3", "Q+1", "Cal+1"]
```

Edit the existing section to extend or reduce this list. It applies to all `fill` products. Original rows outside the list remain preserved; missing rows outside it are not created. A listed tenor is estimated only when the available data support it.

## Choose a calculation mode

Edit the existing `[method]` section in `config.toml`:

```toml
[method]
basis_mode = "auto"
```

| Value | Calculation |
|---|---|
| `auto`, default | Select ratio or additive separately for each target, using the decision tree below |
| `ratio` | Estimate `basis = Own/EEX − 1`, then `price = EEX × (1 + basis)`; never switch automatically |
| `additive` | Estimate `basis = Own − EEX`, then `price = EEX + basis`; never switch automatically |

In auto, the first matching rule wins:

1. If `abs(target EEX) < ratio_eex_floor`, use additive (`auto_additive_low_eex`).
2. Otherwise, if no ratio anchors remain but additive anchors exist, use additive
   (`auto_additive_no_ratio_anchors`).
3. Otherwise, if neither mode has anchors and only additive has current history allowed by
   `[layers].hist`, use additive (`auto_additive_history_only`).
4. Otherwise use ratio.

Original finite VWAPs, including zero and negative values, are always preserved. Ratio anchors
require `abs(EEX) >= ratio_eex_floor`, `Own/EEX > 0` and
`abs(Own/EEX − 1) <= max_ratio_deviation`; additive accepts finite pairs after the common
volume/deviation filters. Negative pairs such as −10/−12 can be valid ratio anchors; 2/0 cannot.
An auto target near zero selects additive even when other anchors could support ratio.
Forced ratio still gives zero for a zero EEX target.

Ratio anchors can also be rejected by `max_ratio_deviation`, even with nonzero prices and
matching signs. Auto may then use their additive differences if the common filters allow
them. `max_ratio_deviation` protects ratio only; `max_anchor_dev` filters both modes and is
disabled by default. Auto is not an outlier detector or a selector of the lowest-error local model.

The two modes have separate histories, history scores and correlation/cross statistics.
No percentage basis is ever added directly to a price. `[layers].hist = "auto"` is a different
setting: it decides whether past history helps within each mode, rather than selecting the mode.

For example, Own = 2 against EEX = 0 supplies an additive difference of 2. With target EEX = 1,
no history, local weight sum W = 1 and `shrink_k = 1`, auto chooses additive and shrinks that
difference by `w = 0.5`: price = `1 + 0.5 × 2 = 2`. The unshrunk formula would give 3.
Actual W depends on volume and delivery distance. See the algorithm guide for the complete
weighting and learning calculations; auto selection is a rule to validate, not a guarantee
of lower prediction error.

## Complete configuration reference

The defaults below describe the supplied `config.toml`. Edit its existing sections; do not
add duplicate TOML sections. Changing these settings requires no Python edits. Relative file
paths are resolved against the configuration file, except each mapping `eex_file`, which is
relative to `eex_curves_dir`.

### Paths (`[paths]`)

| Parameter | Supplied value | Effect of changing it |
|---|---|---|
| `vwap_input` | `data/vwaps.xlsx` | Select accumulated original CSV/Excel input or a quoted glob; do not point to enriched output |
| `mapping` | `mappings/products.csv` | Select the (product, region, unit)-to-EEX mapping to generate/read |
| `eex_curves_dir` | `../eex_scraper/output/curves/POWER` | Select the root containing long EEX CSVs such as `DE/Base.csv` |
| `output_dir` | `output` | Choose where daily/cumulative curves, enriched rows, reports and logs are written |

### Layers (`[layers]`)

| Parameter | Default | Effect of changing it |
|---|---|---|
| `local` | `true` | `false` disables today's anchor adjustment, while originals remain preserved |
| `hist` | `"auto"` | `"on"` uses current historical adjustments; `"off"` disables them; `"auto"` compares earlier errors against EEX, separately by mode/group |
| `correlation` | `false` | `true` replaces fixed weights between groups with measured surprise relationships, subject to the prior |
| `cross` | `false` | `true` permits other products' correlated surprises; requires the target's internal history and own EEX, with statistics kept separate by mode |
| `arbitrage` | `true` | `false` disables strip/residual construction from already available contract prices when EEX cannot price the target |

Layer switches do not remove original rows. `hist = off` does not itself disable cross:
cross may use an internal historical baseline for surprises, without adding that mean to the
price. Selecting additive in auto does not enable a disabled local/history/cross layer.

### EEX freshness (`[eex]`)

| Parameter | Default | Effect of changing it |
|---|---|---|
| `max_stale_days` | `0` | 0 allows any earlier publication; positive N rejects curves more than N calendar days old; never selects future EEX |
| `warn_stale_days` | `3` | Stale-curve messages become ERROR at this age; this threshold logs a problem but does not itself reject the curve or fail the run |

Only same-day EEX can train history, regardless of whether a stale curve is accepted for pricing.

### Mapping time zones (`[timezones]`)

| Parameter | Default | Effect of changing it |
|---|---|---|
| `default` | `"Europe/Berlin"` | Default delivery time zone for newly drafted mapping rows |
| `GB` | `"Europe/London"` | Draft override for GB |
| `IE` | `"Europe/Dublin"` | Draft override for IE |
| `PT` | `"Europe/Lisbon"` | Draft override for PT |
| `GR` | `"Europe/Athens"` | Draft override for GR |
| `RO` | `"Europe/Bucharest"` | Draft override for RO |
| `BG` | `"Europe/Sofia"` | Draft override for BG |
| `FI` | `"Europe/Helsinki"` | Draft override for FI |

Other area keys can be added. Existing mappings use their own `timezone` column; changing
this section does not overwrite reviewed mapping rows. Base delivery hours include daylight
saving changes. Peak Day/Weekend uses 12 hours every day; other Peak kinds use Monday–Friday.

### Targets and conventions (`[targets]`, `[conventions]`)

| Parameter | Default | Effect of changing it |
|---|---|---|
| `targets.tenors` | `D+1..D+3`, `WE..WE+3`, `BOW`, `W+1..W+4`, `BOM`, `M+1..M+10`, `Q+1..Q+8`, `Sum+1..Sum+3`, `Win+1..Win+3`, `Cal+1..Cal+3` | Edit the actual string list to add/remove target rows for every `fill` product; original rows outside it remain preserved |
| `conventions.day` | `"calendar"` | `"business"` interprets D+n as Monday–Friday business-day offsets; no holiday calendar is supplied |
| `conventions.weekend_offset` | `0` | Shifts own WE+n by this many weekends when resolving delivery periods |

Ranges above abbreviate the supplied list; write individual strings in TOML, as shown earlier.
Adding a target does not guarantee coverage. Use `detect-conventions` to compare interpretations.

### Pricing and history (`[method]`)

| Parameter | Default | Effect of changing it |
|---|---|---|
| `basis_mode` | `"auto"` | Use the per-target tree above, or force `"ratio"` / `"additive"` |
| `min_volume` | `0` | Known volume below this threshold cannot anchor adjustments; missing volume is not below a known threshold; originals remain intact |
| `tau_log` | `0.5` | Larger positive values let more distant anchors influence a target |
| `other_kind_weight` | `0.6` | Greater weight for anchors of another contract kind, before any configured between-group correlation adjustment |
| `shrink_k` | `1.0` | Larger positive values lower local weight `w = W/(W+k)`, favouring allowed history or zero adjustment if no prior exists |
| `ewma_halflife_days` | `10` | Larger positive values slow ratio/additive history updates; measured in valid observation days, not elapsed days |
| `max_anchor_dev` | `0` | 0 disables this common filter; positive N excludes anchors with `abs(Own−EEX)/max(abs(EEX),ratio_eex_floor) > N`; within positive values, increasing N admits more deviations |
| `ratio_eex_floor` | `1.0` | Positive minimum abs(EEX) for ratio anchors; in auto, targets below it use additive. It is in price units and never edits EEX |
| `max_ratio_deviation` | `1.0` | Positive maximum abs(Own/EEX−1) for ratio anchors and absolute final ratio adjustment; not an additive price cap |
| `hist_max_age_days` | `60` | Positive calendar-day expiry: a kind/group/global mean is dropped after more than this many days since its last valid own observation |
| `hist_auto_min_obs` | `10` | Effective comparison mass before hist-auto decides; before it, current history is allowed. Higher values delay the decision |

Both historical models learn from original anchors with same-day EEX, after that day's
prediction. Filled estimates never train history. When a kind's mean is unavailable, the
same mode can fall back to its current group/global mean. Near-zero ratio exclusions do
not discard an otherwise valid additive observation. Review units and use real backtests
before changing bounds; automatic mode does not establish the predictive accuracy of a large additive adjustment.

### Correlation (`[correlation]`) and cross-product assistance (`[cross]`)

| Parameter | Default | Effect of changing it |
|---|---|---|
| `correlation.halflife_days` | `20` | Larger values retain paired surprise evidence longer; updates discount the calendar gap since the previous pair |
| `correlation.prior_obs` | `8` | Larger values keep weights closer to `other_kind_weight` for longer before measured correlation dominates |
| `cross.min_corr` | `0.5` | Higher correlation required to admit a helper product |
| `cross.min_obs` | `8` | Higher minimum effective joint observation mass before a helper can contribute |
| `cross.halflife_days` | `20` | Memory for helper correlation and β, discounted by calendar gaps between pairs |

These settings affect predictions when the corresponding layer is enabled. Eligible helpers
are mapped `fill` or `helper` products. Surprises, covariances and β remain separate by mode.

### Warmup (`[run]`)

| Parameter | Default | Effect of changing it |
|---|---|---|
| `warmup_days` | `0` | 0 rebuilds from all prior original history supplied; positive N restricts warmup to N calendar days and can make a daily run differ from a longer refill |

This setting does not retrieve missing files. Supply accumulated originals and the matching
EEX history on the destination machine.

### Input column assignments (`[vwap_columns]`)

| Parameter | Default input column | Effect of changing it |
|---|---|---|
| `reference_date` | `"reference_date"` | Read observation dates from the named column; mandatory and dates must parse |
| `product` | `"product"` | Read product names, the first identity component; mandatory and cannot be empty |
| `region` | `"region"` | Read the exact region identity component; column mandatory, blank value literal |
| `unit` | `"unit"` | Read the exact unit identity component; column mandatory, no automatic conversion or wildcard |
| `tenor` | `"tenor2"` | Read relative delivery labels; mandatory |
| `vwap` | `"vwap"` | Read observed prices; column mandatory, invalid/empty values retained for enrichment |
| `volume` | `"total_volume"` | Read anchor volumes; the column can be absent |

Assignments change how columns are interpreted; original columns are retained in enriched output.

## Generate and review the mapping

Run once on the destination machine:

```powershell
python run.py mapping
```

Review `mappings/products.csv` before filling. **Every newly drafted row starts with `use = off`,
even when an EEX file is found**. Activate the intended identities explicitly: `fill` calculates
that curve, `helper` supplies assistance without its own calculated output, and `off` excludes
it from calculations. Check each `eex_file`, identity/profile correspondence, `hours` and
`timezone`. Input and EEX currency/units must agree; the program does not convert them.
Unmapped identities are reported and not processed. Their originals remain in enriched output.

`fill`/`helper` also require a nonempty `eex_file`: without an assigned file the identity is
excluded and flagged `mapping_unassigned`, even if `use` is enabled. This differs from an
assigned path whose file is absent or has no quotes for the date: that identity is active,
the missing data is reported, and own VWAPs/contract construction can still be used.

**The mapping is editable by hand**, in a text editor or Excel. Its header is
`product,region,unit,use,area,profile,eex_file,hours,timezone,comment`. Use the input's exact
three-component identities and comma-separated UTF-8 CSV format; `eex_file` is relative to
the configured POWER directory. The same product name may have multiple rows when region/unit
differ. Duplicate complete identities are rejected. Running `mapping` again preserves existing
decisions and adds new identities as `off`.

An older mapping missing region/unit columns can be migrated by `mapping` only when every
old row has exactly one compatible identity in the input. Existing EEX choices and other
settings are retained. Zero or multiple candidates cause an error and leave the file unchanged;
add explicit rows manually. A present but blank identity value remains literal, not an
unspecified match. Input files themselves must contain the configured region/unit columns.

Any AT/DE/FR/NL demonstration mapping is a test example, not a complete market list. Generate
and review identities from the destination machine's input. Unmapped and `off` originals remain
in the enriched output, without generating estimated curves for them.

GB input blocks such as `GB_Other_Block_1_2` or `GB_Other_Block_3_4` have no implemented block
calendar/source mapping and stay `off` in the draft. `TB2` does not mean “block 2”; do not map
these rows blindly to TB2, Base or Peak. They require an exact definition of delivery hours and
a matching price source before support can be added.

## Run

After setting the paths in the single `config.toml`, here or in the extracted portable ZIP:

```powershell
python run.py mapping
python run.py daily
python run.py catchup
python run.py refill --from 2026-09-01 --to 2026-09-30
python run.py daily --date 2026-09-30
```

`daily` and `refill` share the same engine. Keep `warmup_days = 0` and supply accumulated
originals to rebuild the same historical state. Today's observations alone lose that memory.
Reruns replace results by date/product/region/unit, retaining other identities, including
other regions/units with the same product name.

Older result files without `region`/`unit` (calculated curves) or `curve_region`/`curve_unit`
(enriched output) are rejected before result writes. Set `output_dir` to a new directory and
rebuild with `refill`; old identities are not guessed or silently merged. Logs can still be written.

### Choose among the three uses

| Need | Command | Scope |
|---|---|---|
| Calculate today or revisit a date | `daily` or `daily --date YYYY-MM-DD` | Recalculates the date even if results exist |
| Recover pending days/curves | `catchup` | Only pending date/identity fill groups through today |
| Rebuild an interval or enrich all its input | `refill --from YYYY-MM-DD --to YYYY-MM-DD` | Recalculates the requested range |

Catchup starts at the earliest available input/EEX date unless `--from` is supplied; without
dates it requires an explicit start. `--to` defaults to today; future ends and reversed ranges
are rejected. Candidates include business days and observed active-input/EEX dates, including
weekends. A group is pending if a resolvable target is absent from **either** calculated or
enriched history. A present `missing` record already counts as processed. The full pending
curve is recalculated and complete groups are preserved. Use daily/refill to refresh those
with new quotes. Without active fill curves or pending groups, it does not write results.

Catchup initially exports only originals from pending fill groups, not helper/off/unmapped
rows. Daily/refill enrich all originals in the range. All three rebuild memory from accumulated
originals, never stored estimates. Historical and affected output schemas are validated before
writing results.

### Command-line options

| Option | Commands / default | Effect |
|---|---|---|
| `--config PATH` | Optional global option; default `config.toml` | Advanced override of the single normal config; goes **before** the command |
| `--vwap PATH_OR_PATTERN` | `mapping`, `daily`, `catchup`, `refill`, `backtest`, `tune`, `detect-conventions`; defaults to configured input | Override input for this run; quote patterns with wildcards |
| `--date YYYY-MM-DD` | `daily`; defaults to the machine's local date | Select one reference date |
| `--from YYYY-MM-DD`, `--to YYYY-MM-DD` | `refill`, `backtest`; defaults inferred from available data | Restrict the requested date range; earlier data can still warm up history |
| `--from YYYY-MM-DD`, `--to YYYY-MM-DD` | `catchup`; inferred start, end today | Recover pending groups only; future end and reversed ranges rejected |
| `--last N` | `status`; default 10 | Number of dates to display |
| `--truth PATH` | `backtest`; absent by default | Compare calculated prices with a matching synthetic ground-truth file |
| `--areas LIST` | `make-synthetic`; default `DE,FR,NL,AT` | Comma-separated synthetic product areas |
| `--profiles LIST` | `make-synthetic`; default `Base,Peak` | Synthetic profiles |
| `--from`, `--to` | `make-synthetic`; defaults 2000-01-01 to 2100-01-01 | Filter available EEX dates for synthetic generation |
| `--seed N` | `make-synthetic`; default 7 | Synthetic random seed |
| `--mode ratio` or `--mode additive` | `make-synthetic`; default ratio | Choose the synthetic data-generating model; **does not override filling `basis_mode`** |
| `--out PATH` | `make-synthetic`; default `data` | Synthetic output directory |

For example, `python run.py daily --date 2026-09-30 --vwap "C:/data/vwaps_*.csv"` uses the
normal config with another input. An optional custom config is written
`python run.py --config C:/settings/custom.toml daily --date 2026-09-30`; no second config is
required for ordinary use. Use dates actually covered by the destination machine's files.

## Read the output

The main deliverables are `output/enriched_history.csv` and `output/enriched/YYYY-MM-DD.csv`.

| Column | Meaning |
|---|---|
| `curve_price` | Final usable price. Read this column when an original `vwap` was blank or invalid. |
| `data_origin` | `original`, `estimated` or `missing`. |
| `estimation_method` | For example `ratio_local`, `ratio_local_history`, `additive_local`, `eex`, `contract_strip`, `contract_residual` or `none`. |
| `curve_row_type` | `original`, `original_invalid` or `added`. |
| `curve_product`, `curve_region`, `curve_unit` | Complete normalized curve identity used in matching; raw input values remain intact. |
| `curve_basis_mode` | Applied formula, `ratio` or `additive`. |
| `curve_configured_basis_mode` | Requested setting: `auto`, `ratio` or `additive`. |
| `curve_flags` | Includes the auto-selection reason when additive was selected for an EEX estimate. |
| Other `curve_*` columns | Reference keys, sources, calculation details and flags. |

Original values, duplicates and tenors outside the configured targets are preserved. An invalid original `vwap` is not overwritten; its estimate appears in `curve_price`. Added rows carry their estimate in both columns. Unresolvable cells stay `missing`, with no fabricated price, volume or trade count.

`filled_history.csv`, `filled/` and `consistency_history.csv` provide the calculated curve and diagnostics. A detected internal calculation failure returns a nonzero exit code without replacing result CSVs; inspect `output/_logs/`.

## Validate

```powershell
python -B -m pytest -p no:cacheprovider
python run.py backtest
```

Tests and synthetic data validate the mechanics; they do not establish accuracy on your real market data. This is a moderately complex baseline using own observations, EEX, local/history adjustments and arbitrage. Keep `cross = false` and `correlation = false` until real-data validation supports adding those layers. The linked algorithm documents describe the calculations and their limits.

Backtest pairing uses date/product/region/unit/tenor. Error reports and convention checks
separate units, so EUR/MWh and GBP/MWh errors are not pooled. Compare `pipeline_configured`
with EEX on the same observations using `n_paired` and `mae_improvement`.


## Select parameters against real originals: `tune`

**Prediction errors are measured against your hidden own VWAP, not against EEX.** EEX is an
input and comparison baseline. Example: actual own price 120, EEX 100; candidate A predicts
102 (error 18), candidate B predicts 118 (error 2). B is better even though it moves farther
from EEX. The program does not optimize resemblance to the EEX curve.

For each evaluated observation, it hides that own point, predicts it with the configured
pipeline and compares with the original value that actually existed. It does not hide the
entire daily curve. Originals and EEX must overlap in dates and delivery periods; a similar
scraper without that overlap is insufficient. The command reports or fails on insufficient
paired evidence rather than inventing metrics for dates without comparable data.

```powershell
python run.py tune
python run.py tune --from 2026-08-01 --to 2026-09-30 --validation-days 10 --basis-modes auto,ratio,additive --tau-log 0.3,0.5 --shrink-k 0.5,1,2 --max-trials 50
```

Dates are examples: use the coverage of originals and EEX on the real-data machine.
**Requires `run.warmup_days=0`**; the command does not change it automatically. Reserving
10 dates requires at least 12 dates with eligible own observations, and at least two
calibration dates with actual paired comparisons. The example tests 18 combinations.

| Tune option | Default | Effect |
|---|---|---|
| `--from`, `--to` | First/last input date | Interval split into calibration and validation; earlier history remains available |
| `--vwap PATH_OR_PATTERN` | Configured input | Select accumulated originals for this evaluation |
| `--basis-modes` | `auto,ratio,additive` | Comma-separated candidate formulas |
| `--tau-log` | Configured value only | List of finite positive local reaches, such as `0.3,0.5` |
| `--shrink-k` | Configured value only | List of finite positive shrinkage values, such as `0.5,1,2` |
| `--hist-modes` | Configured value only | List of `auto,on,off` history settings |
| `--correlation` | Configured value only | List `off,on` to compare the weighting extension |
| `--cross` | Configured value only | List `off,on` to compare cross-curve assistance |
| `--validation-days` | `20` | Positive number of latest distinct eligible observation dates reserved; not consecutive calendar days |
| `--max-trials` | `50` | Positive Cartesian-product limit; an oversized grid is rejected rather than truncated |

Only **those six model settings** are explored. Other controls retain their configured values.
Defaults test three modes while keeping the other five fields fixed. Changing settings such
as expiry or volume requires another explicit comparison; tune does not automatically search
the entire configuration inventory.

**How it chooses the better candidate:**

1. Sort eligible own-observation dates for active fill curves and reserve the latest N for
   validation. Calibrate all combinations on the earlier dates. Validation errors do not
   participate in selecting the winner.
2. Every candidate must use exactly the same own keys and EEX baseline. For each curve,
   calculate `MAE_model / MAE_EEX`, both measured against the **same hidden own VWAP**.
   Average those ratios with equal weight for each curve.
3. The smallest calibration average wins. 1 matches EEX; 0.7 means mean normalized error
   per curve is 30% below EEX, **not** 30% lower pooled currency MAE. If EEX is perfect on a
   curve, its ratio is defined as 1 when the model is also perfect, otherwise infinity.
   Ties favor the first candidate in grid order.
4. Only then evaluate the winner on the later reserved dates, keeping parameters fixed.
   Memory advances chronologically using originals already observed, including earlier
   validation dates: each date uses only prior history. Future prices are not used.

Writes `output/tuning_calibration.csv`, `tuning_validation.csv` and `tuning_selected.json`.
The CSVs report score, `normalized_skill=1-score`, paired counts and MAE/RMSE/bias by unit;
absolute EUR/MWh and GBP/MWh errors are not pooled. JSON records proposed changes, the full
base configuration, input pattern and metadata with planned and actually paired dates.
Retain input, EEX and mapping files too: paths/configuration alone do not preserve their contents.

**Does not edit `config.toml` or curve histories.** Review validation and, if accepted for
business use, manually copy selected values into existing configuration sections. Failure
of any candidate aborts evaluation rather than publishing a partial selection.

This is the best candidate **among those tested, on calibration**, not a future guarantee.
Validation hides points that actually had observations: it may favor liquid periods and
does not establish performance when an entire daily curve is missing, or reveal truth for
actual unobserved gaps. Do not repeatedly tune against the same reserved period and then
present it as independent evidence. Reserve fresh dates for later changes.

Missing, nonnumeric or nonfinite EEX settlements are excluded with a warning while valid quotes remain. A nonfinite calculated price fails the run and prevents result writes.
