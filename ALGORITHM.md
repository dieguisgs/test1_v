# Power curve filling algorithm


[Output dictionary](OUTPUT.md) · [Diccionario en español](OUTPUT.es.md)
[Versión en español](ALGORITMO.md)

How a complete product curve (for example DE Base) is generated each day from **your VWAPs**,
which cover only some contracts, and **EEX settlements**, which provide much of the curve.

> Section 0 contains teaching examples with explicit assumptions. Older numerical tables later
> in this document came from a run using DE Base on 29 September 2026 and synthetic VWAPs;
> they have not been recalculated. None demonstrates predictive accuracy on real data:
> explanations of the mechanics must be distinguished from validated backtest results.

---

## 0. Understand the product before reading the formulas

### 0.1. The problem it solves

Imagine your price table contains M+1, M+2 and M+4 on a date, but M+3 is absent. The gap is
**a missing row**, not necessarily an empty cell. The program reconstructs target points
using own prices and a comparable EEX reference. Estimates always remain identified as
estimates; they never become trades.

A curve belongs to a date and an exact **product + region + unit** identity.
`Base load / DE / EUR/MWh` and `Base load / GB / GBP/MWh` are independent curves: prices are
not pooled and currencies are not converted. The mapping controls scope and EEX sources.
New mapping rows start disabled: review and explicitly activate `fill` or `helper`, with an
assigned EEX file.

There are two views: a **calculated curve**, with one point per target, and the **enriched
input**, containing originals, added rows and trace information. Consume prices from
`curve_price`; `data_origin` distinguishes `original`, `estimated` and `missing`, and
`estimation_method` explains the estimate. An invalid original VWAP is not overwritten:
any estimate belongs in `curve_price`.

| Term | Business meaning |
|---|---|
| Target or tenor | Delivery period to value, such as next month, M+1 |
| Gap | Unobserved price: an absent row or unusable original value |
| Anchor | Own observation comparable with EEX that passes the filters for measuring a difference |
| Adjustment or basis | Own difference from EEX: a percentage in ratio, price units in additive |
| Local | What anchors on this date say, giving nearby anchors more influence |
| History | Memory of earlier differences; not copying yesterday's price |
| Local weight `w` | Share of the local adjustment versus its fallback; not a probability of being correct |
| Strip | Compose a period from pieces that cover its hours exactly |
| Residual | Infer one part by subtracting another known part from the full period |

Section 14 covers **all of `config.toml`**, defaults and effects of changing them. Sections
1–13 develop the formulas, files and audit procedure.

### 0.2. One date, one curve and three different outcomes

Teaching example for `Base load / DE / EUR/MWh`, using default layers:

| Tenor | Own input | Reference | Result |
|---|---:|---:|---|
| M+1 | 105 | EEX 100 | 105, `original`: own price is preserved |
| M+2 | Absent row | EEX 120 | 125.28, `estimated`, under the weight/history assumptions in the next section |
| M+3 | Absent row | No EEX or sufficient contract combination | `missing`: no invented price |

The 105 may help other points if it passes the filters. Preserving an original and allowing
it to influence estimates as an anchor are separate decisions: zero, negative values or
low volume do not remove the original, although they may exclude it from estimating others.

### 0.3. The same explanation with numbers: how much today and how much history

Assume an own anchor **105** against **EEX 100**, target **EEX 120**, aggregate local evidence
**W=4** and `shrink_k=1`: `w=W/(W+k)=4/5=0.8`. W depends on anchor weights;
**4 is a teaching assumption, not a fixed program value**. Cross is disabled.

In **ratio**, the anchor says `105/100−1=0.05`: +5%. If current, permitted history says +2%,
the blend is `0.8×5% + 0.2×2%=4.4%`. Price: **`120×1.044=125.28`**.

In **additive**, the anchor says `105−100=5` units. If current, permitted additive history
is +2, the blend is `0.8×5 + 0.2×2=4.4`. Price: **`120+4.4=124.4`**. Percentages are not added
to prices: the modes maintain separate memories and statistics.

| Permitted evidence | Ratio | Additive |
|---|---:|---:|
| Apply the entire anchor without shrinkage: teaching comparison | `120×1.05=126` | `120+5=125` |
| Local W=4 + history, k=1: implemented calculation for this example | **125.28** | **124.4** |
| Local W=4 without history: zero adjustment fallback | `120×(1+0.8×0.05)=124.8` | `120+0.8×5=124` |
| No anchors, only permitted history | `120×1.02=122.4` | `120+2=122` |
| No usable local, historical or cross adjustment | **120** | **120** |

Copying one known month's entire factor therefore does not always describe the calculation.
`shrink_k` reduces the local adjustment. As W increases relative to k, the result approaches
the full local adjustment. Without history, w is not forced to 1: the remaining share goes
to a zero adjustment. Enabled cross contributes to the fallback before blending.

### 0.4. Nine situations for interpreting prices

These are case families, not nine mandatory steps. Auto selection in row 8 operates within
cases that use EEX.

| Case | Available information | Program behavior | What to review |
|---|---|---|---|
| 1. Valid original | Numeric, finite own VWAP | Preserves its price, including zero/negative | It may be excluded as an anchor. Zero-hour delivery receives no calculated curve price, but its original is preserved |
| 2. Gap with today's anchors | EEX and admissible observations | Blends local adjustment with permitted history/cross, or zero | Mode, weight, anchors, filters and EEX age |
| 3. Gap with history | EEX, no local adjustment, current/permitted memory | Applies memory; optional cross may contribute | Memory precedes the date and has not expired |
| 4. EEX reference only | EEX, no usable adjustment | Uses EEX unchanged | A reference estimate is not a trade |
| 5. Exact EEX quote absent | Sufficient EEX pieces | Constructs EEX by strip/residual, then applies adjustment logic | Hour coverage and residual amplification |
| 6. EEX cannot be obtained | Sufficient own or already calculated contracts | With `arbitrage=true`, constructs by strip/residual | Not every combination is possible; global consistency is not forced |
| 7. Insufficient information | Neither reference nor valid construction, or no delivery hours | Leaves `missing` with a reason | A result without a price can be correctly processed |
| 8. Ratio fails selection rules | Small target EEX, additive anchors only, or permitted additive history only | Auto selects additive with a reason; forced modes retain their formula | Auto neither detects every outlier nor searches for the lowest-error mode |
| 9. Outside activated scope | Unmapped, `off`, or empty `eex_file` | No estimated curve; originals remain in the requested enriched scope | Review mapping. An absent tenor outside targets is not created either |

An EEX path **assigned but lacking data** keeps a curve active: originals and arbitrage may
be used. **No assigned source** excludes it. When today's EEX publication is unavailable,
the latest earlier publication may be used under `[eex]`, never a future one. Its age is
recorded and that date does not train memory using the stale reference.

A strip requires complete contiguous coverage and weights prices by hours. A residual values
the tail as `(parent_price×parent_hours−head_value)/tail_hours`. A small tail amplifies errors
by `parent_hours/tail_hours`; there is currently no dedicated limit on that amplification.
Diagnostics report inconsistencies without modifying originals to force aggregates to agree.

### 0.5. The decision tree as a human review

1. **Scope and calendar.** Check activated identity and assigned source. Resolve tenor, time
   zone and delivery hours before price. Without hours, the curve price remains missing.
2. **Original.** A valid own price for the period takes precedence. An invalid original
   remains unchanged while the program seeks an estimate for `curve_price`.
3. **Reference.** Try exact EEX, strip or residual, allowing past publication under the
   configuration. Without usable EEX, try permitted arbitrage; without information, `missing`.
4. **Formula.** `ratio` and `additive` force a mode. In `auto`, the first matching rule wins:
   `abs(target EEX)<ratio_eex_floor` → additive; no ratio anchors and some additive anchors →
   additive; no anchors in either mode and only current/permitted additive history → additive;
   otherwise → ratio.
5. **Adjustment.** Combine local, permitted history and enabled cross using w. Record price,
   origin, method and evidence; a valid original is not adjusted.
6. **Subsequent learning.** After predicting the date, update memories with admissible
   originals and EEX from that same date. Never learn from estimates.

By default, a ratio anchor requires `abs(EEX)>=1`, `Own/EEX>0` and `abs(Own/EEX−1)<=1`.
Thus −10 against −12 may work; 2 against 0, own zero or opposite signs do not. Excessive
ratio deviation also excludes it. Additive admits finite differences passing common filters.
`max_ratio_deviation` protects ratio; enabled `max_anchor_dev` protects both.

Near-zero example: own 2 and EEX 0 give an additive difference of +2. Target EEX 1 would give 3
**if the entire adjustment were applied**; the engine retains blending with w and history.
Target EEX 0 triggers additive in auto. Forced ratio still gives `0×(1+adjustment)=0`:
the anchor denominator filter does not modify the target EEX price.

### 0.6. History and the two meanings of “auto”

History remembers **differences** by kind, group and curve, separately by mode. It does not
carry yesterday's own price forward. With a previous ratio mean of +2%, new daily observation
of +4%, and half-life 10, the new weight is about 0.066967: the mean becomes **2.133934%**.
Applied later to current EEX 150, this gives **153.200901**. Current EEX supplies the price
level; memory supplies the usual difference.

This half-life counts days **with valid observations**: ten days without data are not ten
updates. In contrast, `hist_max_age_days=60` expires each mean after more than 60 calendar
days since its last valid observation. Estimates, future EEX and a stale publication reused
for today do not train these memories.

`basis_mode=auto` selects **the formula**. `hist=auto` decides **whether to permit memory
for a mode/group**, comparing prior errors with EEX alone; during warmup it permits current
history. It may reject ratio memory but allow additive memory, influencing the third
basis-auto branch. Prediction uses earlier memory; today's own observation is learned
afterwards. Section 7 explains comparisons and section 14 their controls.

### 0.7. Cross-curve help without confusing it with a price proxy

`cross=false` by default. Enabling it requires the target's own memory, target EEX and
sufficient relationships between **adjustment surprises**. It is not “ES price = alpha + beta
× FR price”, and it does not solve a curve that has never had comparable own history.

Ratio example: target mean −0.8%; a helper surprises today by −1 percentage point relative
to its mean, with beta 0.8. Its contribution is −0.8 points. Without local adjustment and
with permitted history, total adjustment is −1.6%; target EEX 100 gives **98.4**. This
illustrates the formula, not a demonstrated market relationship. If hist is off/rejected,
its mean is not added, although cross may use current internal memory to measure surprises.
Ratio and additive remain separate.

Correlation, beta regression and exponential means are standard statistical techniques;
their combination, filters and processing here are a custom implementation. Relationships
pair curves on the **same date**; this is not lagged cross-correlation searching for one
market to anticipate another. The other extension, `correlation=false`, would change weights
between tenor groups; it is distinct from cross. Validate both before enabling them.

### 0.8. Read a price's evidence and choose how to run

To audit **125.28** above, these fields must agree:

| Enriched field | Teaching value | What it checks |
|---|---|---|
| `data_origin` / `estimation_method` | `estimated` / `ratio_local_history` | Local estimate with history |
| `curve_configured_basis_mode` / `curve_basis_mode` | `auto` / `ratio` | Configured and actually applied choices |
| `curve_eex_settle` | 120 | Reference before adjustment |
| `curve_basis_local` / `curve_basis_hist` | 0.05 / 0.02 | Fractions, not prices |
| `curve_local_weight` / `curve_basis` | 0.8 / 0.044 | Blend weight and final adjustment |
| `curve_price` | 125.28 | `120×(1+0.044)` |

Also review identity, delivery, EEX date/method and flags. `curve_anchors` shows only three
anchors: reconstructing W requires input, EEX, mapping and configuration for the run.
`confidence` is heuristic: 0.8 does not mean an 80% probability of being correct.

| Operational need | Command | What is recalculated |
|---|---|---|
| Today or a specified date | `python run.py daily` or `daily --date 2026-09-30` | The date, even if results already exist |
| Recover pending runs | `python run.py catchup` | Only pending date/identity groups through today; accepts `--from` and `--to` |
| Rebuild an interval | `python run.py refill --from 2026-09-01 --to 2026-09-30` | The entire range, even if already processed |

Catchup considers a group pending when a resolvable target is absent from either calculated
or enriched history. An existing `missing` record already counts as processed; use daily/refill
to revisit it with new information. Catchup exports only pending `fill` curves and preserves
other existing results; daily/refill can enrich all originals in the range. All need accumulated
original input: output CSVs do not train the model. Section 5 details these three uses.

---

## 1. Inputs and outputs

**Inputs**

| Source | What it is | What it contributes |
|---|---|---|
| Your VWAPs | The day's traded average for each contract | **Your observed level**, where you traded |
| EEX | Each contract's daily settlement | **The curve shape**: November relative to October, Q1 relative to Cal, etc. |

**Calculated curve**: one price per target tenor for each date and **`(product, region, unit)`**
combination with `use = fill` and an assigned `eex_file`:

```text
D+1..D+3 | WE..WE+3 | BOW, W+1..W+4 | BOM, M+1..M+10 | Q+1..Q+8 | Sum+1..3, Win+1..3 | Cal+1..3
```

Each cell also records its `source`, confidence score and contributing anchors.

**Enriched file for daily/refill**: preserves all original columns and rows within the requested date range,
including order, duplicates, tenors outside the targets, and unmapped or disabled products.
Calculated tenors whose date/product/region/unit/label key was absent from the input are appended at the
end. The calculated curve may aggregate observations of the same delivery period; the enriched
file keeps each original observation separately. Throughout this guide, a processed product
or curve means the complete identity, not just its `product` name.

For example, `("Base load", "DE", "EUR/MWh")` and `("Base load", "FR", "EUR/MWh")` are
different curves; changing only `unit` also creates another identity. Their observations,
anchors, volumes and memories are not pooled because their names match. Each combination
has its own mapping and results. Assistance between curves requires the explicit cross layer.

Internally, surrounding whitespace is trimmed from the three identity components, preserving
case and spelling. Original input values remain unchanged. An empty `region` or `unit` is
the literal value `""`, never a wildcard matching every value. An empty `product` is an input error.

- `data_origin`: `original` when the row's VWAP was numeric and finite, `estimated` when the
  engine supplies a missing price, or `missing` when no usable price is available.
- `estimation_method`: the actual method, such as `ratio_local_history`, `eex` or
  `contract_strip`; `none` for valid originals and gaps without an estimate.
- `curve_price`: the usable price. If an original VWAP is empty or invalid, the original cell
  remains unchanged and any available estimate is recorded here.
- `curve_row_type`: `original`, `original_invalid` or `added`. Other trace fields use the
  `curve_*` prefix: source, EEX data, delivery dates, anchors, adjustments and flags.

New rows do not invent volumes or trade identifiers. They use their exact identity's `region`
and `unit`, inheriting only unambiguous other attributes from that same curve. An empty unit
is not invented and is flagged.

### 1.1. Your file: one row per observation, rather than one column per maturity

The input uses a **long format**. The example input contains these columns:

| Column | Role in the program |
|---|---|
| `reference_date` | VWAP observation date. Dates are parsed day first: `02/01/2025` means 2 January 2025 |
| `weekday` | Descriptive weekday text; does not determine the date or delivery calendar |
| `product` | Product name; together with `region` and `unit`, forms the exact mapping key |
| `country` | Preserved product attribute |
| `region` | Curve identity component; required column, although a literal empty value is allowed |
| `classification` | Preserved product attribute |
| `unit` | Declared price unit and identity component; required column, no automatic conversion; empty is literal |
| `periodicity_2` | Periodicity label; does not replace tenor resolution |
| `tenor2` | Relative tenor of the observation, for example `M+1` |
| `vwap` | Observed price, preserved on original rows |
| `total_volume` | Volume for weighting and optional anchor filtering; may be absent |
| `n_trades` | Original information; not used in estimation or invented for new rows |
| Optional index or other columns | Preserved as input data; not used as the engine's contract identity |

Column names are assigned in `[vwap_columns]`. The current configuration maps `tenor` to
`tenor2`, `volume` to `total_volume`, `region` to `region`, and `unit` to `unit`.
Date, product, region, unit, tenor and VWAP columns are required. If an older input lacks
region/unit columns, add the correct values or assign their actual column names in configuration;
they are not silently inferred. An invalid date stops loading. An empty or nonfinite VWAP remains in the enriched output and
is not used as an engine observation.

A typical gap is **an absent row**. If DE Base on 2 January 2025 has `M+1`, `M+2`, `M+3` and
`M+5`, the missing row is `M+4`; the input does not need a pre-existing empty `M+4` VWAP cell.
Gaps are detected against `[targets].tenors` by date/product/region/unit/label. If an empty VWAP row
already exists, that row is preserved and its usable price goes into `curve_price`, without
adding a duplicate. Existing duplicate rows are all preserved.

The current configuration creates `D+1..D+3` and `WE..WE+3`, along with the other targets above.
Input rows for `D+4` and `WE+4..WE+6` **are preserved when present**, and valid observations can
help the engine, but absent rows for those tenors are not created automatically. Add their
labels to `[targets].tenors` to include them in the target curve.
This `config.toml` list is editable by hand: keep the targets you want and add or remove labels
to change the scope. No code change is required.

### 1.2. EEX files and available coverage

The program reads the **long CSV**, for example `DE/Base.csv`, under `eex_curves_dir`.
The inspected file contains:

```text
tradeDate,relativeTenor,tenor,maturityType,deliveryStart,shortCode,maturity,
settlPx,totVolTrdd,grossOpenInt,netOpenInt,currency,uOM
```

The reader uses only `tradeDate`, `maturityType`, `deliveryStart` and `settlPx`. It reconstructs
delivery periods from their type and start date; it does not join VWAPs to `relativeTenor` or
the EEX label. Files named `*_wide` are not the input format for this reader.

In the local files inspected during implementation, DE Base covers **10 August to
30 September 2026**; the inspected ES, FR and GB files start on **17 August 2026**. These dates
describe that local copy, not guaranteed provider coverage. The example input from **January
2025 has no contemporaneous EEX history in that copy**. Filling it with an EEX curve shape
requires the corresponding historical files; the program does not use 2026 EEX prices to
reconstruct 2025.

Currency and units also require review: the inspected GB curve declares **GBP/MWh**. The
reader does not convert currencies or check `currency`/`uOM` against the VWAP unit. The mapping
must connect comparable prices; preserving `unit` in the output does not perform that check.

---

## 2. The core idea

Start with EEX and adjust it using your observations. There are **three configurable modes**:

| `[method].basis_mode` | Behaviour |
|---|---|
| `auto`, the default | Selects ratio or additive for each gap using its EEX price, eligible anchors and available history; the exact decision tree is in step 3b |
| `ratio` | Always uses a relative adjustment: `basis = Own/EEX − 1`, `price = EEX × (1 + basis)` |
| `additive` | Always uses a price-unit difference: `basis = Own − EEX`, `price = EEX + basis` |

`auto` is not a third pricing formula: it selects one of the other two and records which.
Original VWAPs remain unchanged. The following introductory examples explain the ratio branch:

```text
gap_price = EEX_gap × factor        with factor ≈ own_VWAP / EEX where an own VWAP exists
```

- **EEX supplies the shape and level.** The engine uses that day's curve or, if unavailable,
  the latest earlier publication allowed by configuration, recording its date.
- **Your VWAPs supply the adjustment**: how far your prices differ from EEX settlements.

This generalizes the formula from the paper:

```text
Own_M2 = Own_M1 × (EX_M2 / EX_M1) = EX_M2 × (Own_M1 / EX_M1) = EX_M2 × ratio_M1
```

Here `ratio_M1` is the **factor** `Own_M1/EX_M1`. In the code and `basis` columns, the ratio is
the **deviation from 1**: `Own_M1/EX_M1 − 1`.

The implementation does not necessarily reproduce the pure formula: it combines anchors,
shrinks their influence according to `shrink_k`, and may use history. For example, with
`Own_M1 = 100`, `EEX_M1 = 102` and `EEX_M2 = 110`:

```text
Pure formula:       100 / 102 × 110 = 107.843137...
Local ratio:        100 / 102 − 1   = −0.019607843...

With no history, W = 1 and shrink_k = 1:
    w = 1 / (1 + 1) = 0.5
    final ratio = 0.5 × (−0.019607843...) + 0.5 × 0
    M2 price = 110 × (1 − 0.009803921...) = 108.921568...
```

`W = 1` is a teaching assumption about the sum of weights, not a fixed M+1 weight. In an
actual run it depends on volume, delivery distance and contract type. With no history, the
estimate approaches `107.843137` as `w` approaches 1; at `w = 0.9` it is `108.058824`.
It also matches the pure formula if the historical prior has exactly the same ratio as the
local estimate. This difference from the paper is an algorithm choice to evaluate in the
backtest, rather than a rounding effect.

VWAP and EEX can differ because VWAP is a daily average while EEX is a closing settlement.
An afternoon rise may leave VWAP below the close across much of the curve. This is why the
ratio of one contract can inform its neighbours on the same day. This is a hypothesis, not a
universal rule: it depends on what traded, when, and where along the curve, and requires validation.

**There are no fixed tables of EEX product relationships.** In the illustrative data, the
November/October EEX ratio moved from 1.094 on 10 August to 1.037 on 29 September; a fixed
table would have missed by around €9/MWh. Relationships come from the curve available on
each date. History estimates **your difference from EEX**, relative in ratio mode and in price
units in additive mode.

> `[method].basis_mode = "auto"` chooses the formula. `[layers].hist = "auto"` decides whether
> to use that formula's historical adjustment. These are independent decisions, explained below.

---

## 3. The algorithm, step by step

For each date T, area and profile:

### Step 0 — Convert tenors to delivery dates

Your relative labels (`M+3`, `Q+1`) and EEX labels **do not always mean the same thing**.
Everything is converted to delivery intervals `[start, end)`, and matched by those dates.

Rules for trading date T = Tuesday 29 September 2026:

| Tenor | Rule | Example |
|---|---|---|
| D+n | T + n calendar days, or business days according to configuration | D+1 = 30 September |
| WE+n | Next Saturday–Sunday weekend + n weeks | WE = 3–4 October; WE+3 = 24–25 October |
| BOW | T+1 through this week's Sunday | 30 September → 4 October |
| W+n | ISO week of T + n | W+1 = 5–11 October |
| BOM | T+1 through month end; absent on the last day of the month | 30 September |
| M+n | Month of T + n | M+3 = December 2026 |
| Q+n | Quarter of T + n | Q+1 = October–December 2026 |
| Sum+n / Win+n | nth summer (April–September) / winter (October–March) that has not started yet | Win+1 = Win-26/27 |
| Cal+n | Year of T + n | Cal+1 = 2027 |

**Why this matters: EEX cascading.** In the example data, EEX Q4-26 is quoted until
28 September and disappears on 29 September as the quarter gives way to its three months
before delivery. Your `Q+1` (October–December 2026) then has no direct EEX quote. The EEX
`Q+2` label that day (Q1-27) becomes your `Q+1` two days later. Joining labels would mix
different contracts; matching delivery dates avoids that ambiguity.

### Step 1 — Select the EEX curve

- Use EEX settlements for date T.
- **If EEX has not published T**, use the latest earlier publication and log the selected
  date and its age, for example 1 October unavailable, using 29 September, two days earlier.
  At `warn_stale_days`, the log level becomes ERROR. That level alone does not fail the run;
  `max_stale_days` decides whether the curve is accepted.
- Add fixings for already delivered Day contracts within 45 days before the selected curve's
  date (`asof`). For each delivery, select the latest publication **on or before `asof`**, even
  if it was published after delivery. Future revisions are never used. These fixings support
  residual calculations such as BOM and BOW.

### Step 2 — Obtain an EEX price for any period

For each anchor or gap, try these methods in order:

| Method | When it applies | Example |
|---|---|---|
| `exact` | EEX quotes that delivery period | M+3 = December 2026 → 159.66 |
| `strip` | Contiguous EEX pieces cover the period; hours-weighted average with the fewest pieces | Q4-26: October 157.70 × 745 h + November 163.61 × 720 h + December 159.66 × 744 h, divided by total hours → **160.29** |
| `residual` | The target is the tail of a larger contract | BOM on 1 September = (September M+0 × month hours − delivered days × their hours) / remaining hours |

This can build Q+1 after cascading, Seasons missing from the example DE files
(Win = Q4 + Q1; Sum = Q2 + Q3), BOW and BOM.

Base uses actual hours in the delivery time zone, including clock changes: October in the
example has 745 hours. Under `Peak`, **Day and Weekend contracts count 12 hours per delivery
day**, including Saturdays and Sundays; Week, Month and other contracts count 12 hours per
Monday–Friday day. `Peak7` counts 12 hours every day. A strip or residual follows the **target
contract's** calendar: a Saturday Peak Day does not contribute hours to a Monday–Friday Peak Month.

A target with zero delivery hours is not estimated: the engine returns `missing` with
`zero_delivery_hours`. For example, a Peak BOW covering only Saturday and Sunday does not
inherit a Peak Weekend price merely because its dates match. Any original BOW observation
is still preserved in the enriched output for review.

Residuals can amplify errors. If `H_parent / H_tail = 30`, a one-unit error in the parent price
moves the residual by 30, holding the head fixed. The method does not impose a specific limit
on this amplification. A BOM with few remaining hours requires checking its component prices
and fixings even if the arithmetic is internally consistent.

### Step 3 — Anchors: your difference from EEX where a VWAP exists

A daily VWAP with an EEX price can become an **anchor** if it passes the filters:

```text
anchor_ratio    = own_VWAP / EEX − 1    # Unitless, for example 0.02 = +2%
anchor_additive = own_VWAP − EEX        # Price units, for example +2 EUR/MWh
```

`min_volume` excludes anchors whose known volume is below the threshold. `max_anchor_dev`,
when enabled, excludes extreme deviations. Ratio mode also requires
`abs(EEX) >= ratio_eex_floor`, a positive factor `VWAP/EEX > 0`, and an absolute deviation
from 1 no greater than `max_ratio_deviation`. Additive mode does not divide by EEX.
**These filters never replace or remove an original VWAP.**

**Zero and negative prices.** Any finite original VWAP, including zero or a negative value,
is always preserved in the enriched file. Whether it can supply a ratio is a separate decision:

| Ratio-mode check | Rule | Example |
|---|---|---|
| Anchor EEX denominator | `abs(EEX) >= ratio_eex_floor`, default 1 | Own = 10, EEX = 0.1: excluded because division would create an unstable factor |
| Anchor factor | `Own/EEX > 0` | Own = 0 with nonzero EEX, or opposite price signs: excluded |
| Factor deviation | `abs(Own/EEX − 1) <= max_ratio_deviation`, default 1 | Factors too far from 1 are excluded |
| Both prices negative | The same checks apply | Own = −10, EEX = −12 gives factor 0.833333, accepted if the other filters pass |
| Target EEX price with forced `ratio` | The floor does not alter or clip the target price | Target EEX = 0 gives `0 × (1 + basis) = 0`; `auto` selects additive for this target |

Two anchor lists are prepared. Both pass the common volume and configured deviation filters;
additive then accepts finite Own/EEX pairs, while ratio also requires the checks in the table.
An anchor rejected for ratio can remain eligible for additive. A percentage is never added
directly to a price: each formula uses its own anchors and history with consistent units.

| Anchor | Own VWAP | EEX | Ratio | Volume |
|---|---|---|---|---|
| M+1 | 155.995 | 157.70 | −1.081% | 71 |
| M+2 | 162.183 | 163.61 | −0.872% | 20 |
| M+4 | 170.734 | 172.23 | −0.869% | 41 |
| M+5 | 165.441 | 166.06 | −0.373% | 60 |
| W+3 | 152.004 | 152.40 | −0.260% | 93 |
| WE+4 | 130.525 | 131.39 | −0.658% | 175 |

Inside the engine, observations of the same period **and complete curve identity**, including
differently labelled aliases, are combined into one volume-weighted quote. Different regions
or units are never aggregated. The enriched file preserves all original rows
and their individual values.

### Step 3b — Select the formula: `auto`, `ratio` or `additive`

Forced `ratio` or `additive` always uses that mode, without automatic switching. With
`basis_mode = "auto"`, a gap with an EEX price follows this exact order:

```text
1. Is abs(target EEX) < ratio_eex_floor?
   Yes → additive; flag auto_additive_low_eex.
2. Otherwise, are there no ratio anchors today but some additive anchors?
   Yes → additive; flag auto_additive_no_ratio_anchors.
3. Otherwise, are both anchor lists empty, with no allowed/current ratio history
   and some allowed/current additive history for the target?
   Yes → additive; flag auto_additive_history_only.
4. Otherwise → ratio.
```

Thresholds use absolute prices: EEX = −12 is not small merely because it is negative.
With floor = 1, EEX = 1 or −1 does not trigger the first branch because the comparison is
strictly `<`. The floor protects anchor divisions and, in auto, selects the formula for
near-zero targets; it does not change the original settlement.

The anchors in this tree are that product's eligible anchors for the day, after filtering.
Rejecting **some** ratio anchors does not itself select additive: if other ratio anchors
remain and the target EEX is above the floor, ratio can remain selected. Formula selection
does not compare past mode errors: it is a deterministic rule, not a learned mode selector.
The backtest evaluates that rule's results.

Ratio rejection can also come from `max_ratio_deviation`, not only zero or opposite signs.
That bound does not apply to additive; `max_anchor_dev` is the common filter, disabled by
default. Auto can use a large additive difference if it passes those filters: it is not an
outlier detector or an automatic selector of the lowest-error local model.

The `history_only` branch checks history that is current **and allowed by `[layers].hist`**.
With `hist = off`, neither history is allowed; with `hist = auto`, each mode's own score is
checked. With no anchors, a non-small EEX and history disabled, the outcome is ratio and
unadjusted EEX even if additive memory remains internally. Local/cross switches still apply:
choosing a mode does not enable a disabled layer. Cross can use its internal history for a
surprise even when hist does not add its mean, as described in section 10.

Original observations are preserved without estimation or automatic-selection flags.
Without a target EEX price, contract construction (`arbitrage`) or `missing` still applies;
auto does not create an absent EEX curve. Zero-hour targets remain `missing` in the engine.

**Auditable examples.** The three local-anchor rows assume total weight `W = 1` in the chosen
mode, `shrink_k = 1`, no history/cross, and the local layer enabled, giving `w = 0.5`.
In real runs W is calculated, not fixed at 1.

| Case | Auto decision | Gap calculation |
|---|---|---|
| Anchor Own = 100, EEX = 102; target EEX = 110 | ratio: an eligible anchor and a non-small target | `b_local = 100/102 − 1`; `b = 0.5 × b_local`; price `108.921568...` |
| Anchor Own = 102, EEX = 100; target EEX = 0 | additive, `auto_additive_low_eex` | `b_local = 2`; `b = 1`; price `0 + 1 = 1` |
| Anchor Own = 2, EEX = 0; target EEX = 1 | additive, `auto_additive_no_ratio_anchors` | `b_local = 2`; `b = 1`; price `1 + 1 = 2`; the pure difference without shrinkage would give 3 |
| No anchors, no allowed ratio history, allowed/current additive history = 2; target EEX = 150 | additive, `auto_additive_history_only` | `w = 0`; `b = 2`; price `150 + 2 = 152` |
| No anchors or history; target EEX = 150 | ratio, final branch | No adjustment; price `150`, source `eex` |

Forced `ratio` would leave the zero-EEX target in the second example at 0. Forced `additive`
uses differences for every EEX-backed gap, even when ratio is stable. Automatic selection
avoids unsuitable divisions in its branches, but does not guarantee that additive differences
predict well: with `max_anchor_dev = 0`, large differences may be accepted. Predictive value
requires a backtest, rather than merely observing that a price can be produced.

### Step 4 — Estimate the adjustment in the selected mode

There are four components:

Formulas and example tables using `ratio` describe that branch. Additive uses the same
weighting and blending with `Own − EEX`, then adds the result to EEX rather than multiplying.
Anchors, historical means and surprises are never mixed across these different units.

**a) Local ratio: today's anchors.** A weighted average of their ratios:

```text
weight_i = ln(1 + volume_i) × kind_i × exp(−abs(ln(1+t_gap) − ln(1+t_i)) / tau_log)
```

- `ln(1+volume)`: more volume gives more weight, without one large anchor dominating everything.
- `kind_i`: 1 for the same contract kind, such as Month with Month; otherwise
  `other_kind_weight`, which defaults to 0.6.
- `t`: days to the midpoint of delivery. Logarithmic distance compares relative distance
  along the curve, rather than treating every additional calendar day equally.

Illustrative M+3 gap (December 2026, t = 78.5 days):

| Anchor | ln(1+vol) | Kind | Distance | Weight | Share of total |
|---|---|---|---|---|---|
| M+4 | 3.74 | 1 | 0.518 | 1.935 | 31% |
| M+5 | 4.11 | 1 | 0.322 | 1.326 | 21% |
| M+2 | 3.04 | 1 | 0.380 | 1.157 | 19% |
| WE+4 | 5.17 | 0.6 | 0.183 | 0.567 | 9% |
| W+3 | 4.54 | 0.6 | 0.095 | 0.259 | 4% |
| M+1 | 4.28 | 1 | 0.054 | 0.232 | 4% |
| … | | | | | |

```text
local_ratio = −0.723%        total evidence W = sum of weights = 6.19
```

**b) Historical adjustment: earlier observations.** For each contract kind (Day, Weekend,
Week, Month, Quarter, Season, Year), maintain **two separate exponential means** from earlier
days: one for `Own/EEX − 1` and another for `Own − EEX`. The selected mode reads only its own
history. For the ratio branch:

```text
daily_ratio(kind) = ln(1 + volume)-weighted mean of that day's anchor ratios for the kind
historical_ratio = α × daily_ratio + (1 − α) × previous_historical_ratio
α = 1 − 0.5^(1 / ewma_halflife_days)
```

- **It is a ratio to EEX, not a remembered price.** History means “your Months are typically
  0.76% below EEX”, rather than “today's M+3 equals yesterday's price”. The price uses the EEX
  curve available for today, with its age recorded.
- Only **observed own VWAPs** update history; filled prices never feed back into the model.
- Only observations with **same-day EEX** update history. Stale EEX would mix market movements
  into the estimated ratio.
- If kind history is unavailable, try the group (short = Day/WE/Week/BOW, month, quarter,
  long = Season/Year), then the global history.
- Each mean expires after more than `hist_max_age_days` calendar days since its latest real
  observation, default 60. A still-valid group/global fallback can then be used; if none exists,
  no historical factor is applied.
- The ratio EWMA advances on valid observations; expiry uses calendar time. An accepted anchor
  with missing or nonpositive volume gets weight 1.

Example: `historical_ratio(Month) = −0.759%`.

**Learning history with simple numbers.** Suppose the previous historical ratio was +2% and
valid anchors from a later, still prior, day produced a daily ratio of +4%. With
`ewma_halflife_days = 10`, `α = 1 − 0.5^(1/10) ≈ 0.066967`:

```text
new historical ratio = (1 − α) × 0.02 + α × 0.04 = 0.02133934...
                     = +2.133934%
If today's EEX is 150 and only that history is used:
estimated price = 150 × (1 + 0.02133934...) = 153.200901...
```

The model retains a smoothed relative difference, not the last observed price. Additive mode
uses the same mechanics for `Own − EEX` differences, adding the result to current EEX. Only
earlier original observations with same-day EEX enter history; estimates and future information
do not. `hist = auto` decides whether to use this memory by comparing earlier prediction errors
with unadjusted EEX. History expires after 60 calendar days by default, as described above.

In additive mode, if the earlier mean was +2 and the new daily adjustment is +4, the same α
produces +2.133934 in price units. Applied alone to EEX = 150, it gives
`150 + 2.133934 = 152.133934`, not `153.200901`, which belonged to the percentage example.
Auto preserves this separation of units.

**Exact learning order.** Before predicting a day, expire old means and prepare both anchor
lists. Select the formula for each gap and predict using earlier memory only. Then, separately
for each mode/group, compare the historical prediction and unadjusted EEX on that mode's
eligible anchors; update its `hist = auto` scores and surprise relationships. Finally update
both EWMAs using that day's original anchors, only when EEX is from the same date. The first
observation initializes a mean; later observations apply α. Both modes learn even if that
day's gaps used only one mode, and also when ratio or additive is forced.

Ratio history, additive history, hist-auto scores, between-group covariances and cross-product
relationships are stored separately by mode, identifying each curve by `(product, region, unit)`.
Filled prices do not become tomorrow's anchors.
Originals without contemporaneous EEX do not update this memory.

**Example with no own VWAP today.** Think of `own price = EEX × factor`; the factor is your
relative multiplier against EEX. Using illustrative own prices and December 2026 EEX prices:

- 22 September: EEX 165.26, own VWAP 163.77 → factor **0.991**.
- 23 September: EEX 162.40, own VWAP 161.26 → factor **0.993**.
- 24 September: EEX 167.40, own VWAP 166.06 → factor **0.992**.
- 25 September: EEX 163.11, own VWAP 161.81 → factor **0.992**.

Prices move between 162 and 167, but **the factor barely changes, around 0.992**. The model
remembers the factor rather than the price.

On 28 September, you do not trade December:

- EEX publishes December at **165.94**.
- The remembered factor is **0.992**.
- The estimated price is 165.94 × 0.992 = **164.61**.

EEX supplies today's price level; history supplies only the factor. Repeating the previous own
price, 161.81, would leave the result about €4 below the now higher market.

**c) Cross adjustment (optional improvement 2).** If a product has few or no anchors, its prior
can be adjusted using today's deviations in **other correlated products**. See section 10.

```text
adjusted_historical_ratio = historical_ratio + β × other_product_surprise_today
```

**d) Blend.** The weight assigned to today's anchors depends on their total evidence:

```text
w = W / (W + shrink_k)
ratio = w × local_ratio + (1 − w) × historical_ratio_or_adjusted_prior
With no history, the historical prior is 0, meaning unadjusted EEX.
```

Example: `w = 6.19 / (6.19 + 1) = 0.861`, then
`ratio = 0.861 × (−0.723%) + 0.139 × (−0.759%) = −0.728%`.

```text
M+3 = 159.66 × (1 − 0.00728) = 158.50
```

### Step 5 — Final price and source

In this table, `adjusted_price` means `EEX × (1 + basis)` for the applied ratio mode or
`EEX + basis` for additive. `basis_mode` records the applied mode; `configured_basis_mode`
records the requested setting. They can differ when auto is configured.

| Situation | Price | `source` |
|---|---|---|
| Valid own VWAP and positive delivery hours, regardless of volume | Own VWAP, aggregated by period in the calculated curve | `own` |
| EEX and local anchors; `w ≥ 0.5` or no historical/cross prior | adjusted_price | `eex+local` |
| EEX, few/no local anchors, and a correlated product with observations today | adjusted_price | `eex+cross` |
| EEX, few/no local anchors, and usable history | adjusted_price | `eex+hist` |
| EEX with no local, historical or cross adjustment available | EEX | `eex` |
| No EEX price can be obtained | Strip/residual from prices already available that day | `arbitrage` |
| None of the above | Empty | `missing` |

Zero-hour targets remain `missing` in the calculated curve before this cascade is applied;
original input rows remain preserved in the enriched output.

Ratio mode limits the final adjustment to `±max_ratio_deviation`, setting
`ratio_adjustment_limited` when clipped. `source` summarizes the dominant contribution;
`estimation_method` and adjustment columns expose the actual combination. The enriched file
always preserves each valid original row's own VWAP, even if the aggregated curve differs.

### Step 6 — Consistency checks

Compare each Q with its months, each Season with its quarters and each Cal with its quarters,
using the filled curve. Deviations go to `consistency_history.csv`. **They are reported, not
corrected**: observed VWAPs do not have to agree exactly across aggregations.

---

## 4. Cases and outcomes

| # | Case | Outcome |
|---|---|---|
| 1 | Own contract VWAP exists | Preserve it in enriched output; the calculated curve uses `own` when delivery hours are positive |
| 2 | Valid VWAP with volume below `min_volume` | Preserve the original; positive-hour contracts remain `own` in the curve but cannot act as adjustment anchors |
| 3 | Missing contract, other own VWAPs today | EEX adjusted by eligible anchors in the chosen mode (`eex+local`) |
| 4 | **No own VWAPs for the product today** | Select a mode, then `[layers] hist` allows its historical adjustment (`eex+hist`) or leaves unadjusted `eex`; hist-auto compares prior errors by mode/group |
| 4b | No own VWAPs, but a correlated product has observations | If enabled and eligible, use EEX × (1 + history + β × other surprise) in ratio mode (`eex+cross`) |
| 5 | No own history yet | Unadjusted EEX (`eex`) |
| 6 | EEX lacks the contract: cascading, Seasons, BOW/BOM | Build from EEX pieces, then apply cases 3/4/5; `eex_method` is strip/residual |
| 7 | EEX has not published today | Latest allowed earlier curve, logged age, confidence ×0.9; no history update |
| 8 | An EEX file is assigned but absent or has no quotes for the date | Own VWAPs plus contract construction; logged warning |
| 8b | Empty `eex_file`, even with `use = fill` or `helper` | Unassigned identity is reported and excluded from the engine; originals retained, no calculated curve |
| 9 | Dates before local EEX coverage, before 10 August 2026 in the DE example | Own VWAPs plus construction; other cells `missing` |
| 10 | EEX horizon is too short, such as Sum+3 without Q3-29 | Try available contract pieces if `arbitrage` is enabled; otherwise `missing` |
| 11 | BOM on month end, BOW on Sunday | Engine does not create the tenor; existing input rows are preserved |
| 12 | Same contract with two labels | One internal quote/anchor; both original rows remain in the enriched output |
| 13 | Unexpected error for a product/date | Engine records `RunResult.errors` and continues diagnosis; CLI returns 1 without writing run results |
| 14 | Identity unmapped, `use = off`, or EEX file unassigned | No engine processing or estimates; originals retained and the situation reported |

**Confidence**, from 0 to 1: `own` = 1. EEX estimates use 0.5 + 0.4×w, or 0.4 without any adjustment
information, multiplied by 0.85 for a constructed EEX price and 0.9 for an earlier curve.
`arbitrage` = 0.4; `missing` = 0.

This is a **heuristic score for provenance and evidence**, not a probability of accuracy,
statistical interval or data-quality guarantee. `own = 1` means an observation is preserved;
it does not certify that the observation is error-free.

---

## 5. Three uses: daily, catchup and refill

All three share **the same pricing engine** and rebuild memory from originals. Daily
recalculates one date; refill recalculates a range; catchup recovers only pending groups.

```powershell
python run.py mapping
python run.py daily
python run.py daily --date 2026-09-30
python run.py catchup
python run.py catchup --from 2026-09-01 --to 2026-09-30
python run.py refill --from 2026-09-01 --to 2026-09-30
python run.py status
```

### How catchup identifies pending work

Without `--from`, it starts at the earliest input/EEX date; without available dates, it asks
for an explicit start. `--to` defaults to today: future end dates and reversed ranges are
rejected. Candidates include business days and observed active-input/EEX dates, including
weekends. An active `fill` identity is pending if a resolvable target is absent from
`filled_history.csv` **or** `enriched_history.csv`, matched by date/full identity/tenor.
A present record with price `missing` counts as processed.

One absent point triggers recalculation of the full date/identity curve, preserving complete
groups. They are not refreshed for new quotes: use daily/refill for that. Adding targets can
make a group pending again. With no active fill curves or no pending groups, it reports no work.

Catchup enrichment includes **only pending fill groups**. It does not initially export
helper/off/unmapped originals; other existing results are preserved. Use refill to enrich the
complete historical input. It replays active curves' originals under the warmup setting,
never learning from output histories. Historical and affected output schemas are validated
before writing results.


- **Memory is rebuilt from originals.** The default `warmup_days = 0` processes all available
  earlier history without writing those earlier dates. For `daily` and `refill` to reconstruct
  the same memory, supply accumulated originals or a file pattern containing earlier VWAPs,
  with the same curves and configuration. A current-day-only input does not contain that
  history. N > 0 limits warmup to N days and logs that results may differ from a long refill.
- **Reruns replace date/identity results.** Outputs for each processed date and
  `(product, region, unit)` replace their earlier versions while preserving other identities,
  including other regions/units of the same product. The enriched output retains original
  duplicates without aggregation or reordering. If EEX publishes late, rerun
  `daily --date <date>`.
- **Outputs**, under `output/`:
  - `filled/<date>.csv`: calculated daily curve.
  - `filled_history.csv`: accumulated calculated curves.
  - `enriched/<date>.csv`: original daily rows with trace columns and added rows at the end.
  - `enriched_history.csv`: accumulated enriched output.
  - `consistency_history.csv`: Q/Season/Cal deviations.
  - `_logs/vwaps_<date>.log`: execution details, warnings and EEX dates used.

When the engine reports errors, `daily`, `catchup`, `refill` and `backtest` return exit code 1 before
writing their results. Existing files are not replaced by partial run results; the diagnostic
log is still written. An expected `missing` cell caused by absent coverage is not itself one
of these execution errors.

Older calculated outputs without `region`/`unit`, or enriched outputs without
`curve_region`/`curve_unit`, cannot safely identify their rows. The run rejects them before
writing results: select a new output directory and rebuild from originals with `refill`.
Dimensions are not guessed or silently merged; the diagnostic log can still be written.

Daily sequence: update EEX with `eex_scraper` after publication → run `daily` → inspect the
summary or `status`.

---

## 6. Parameters (`config.toml`)

Summary of the main controls. **Section 14 details all 46 config.toml keys**, including
aliases, time zones, sensitivity, conditions of use and constraints.

**Layers** (`[layers]`) control execution without code changes:

| Parameter | Default | Effect |
|---|---|---|
| `local` | true | EEX adjusted using today's own anchors |
| `correlation` | false | Improvement 1: measured weights between groups; section 10 |
| `cross` | false | Improvement 2: surprises from related products; section 10 |
| `hist` | auto | `on` uses valid history; `off` disables it; `auto` decides by group using prior errors. Also controls the prior in the local blend |
| `arbitrage` | true | Without EEX, construct prices from available contract pieces |

**Other parameters:**

| Section | Parameter | Default | Effect | Increasing it means |
|---|---|---|---|---|
| `paths` | `vwap_input` | `data/vwaps.xlsx` | Original VWAP file(s); patterns such as `vwaps_*.xlsx` supported | |
| | `mapping` | `mappings/products.csv` | (product, region, unit)-to-EEX mapping; section 9 | |
| | `eex_curves_dir` | `../eex_scraper/output/curves/POWER` | Root of EEX curve files | |
| | `output_dir` | `output` | Output directory | |
| `eex` | `max_stale_days` | 0, unlimited | Maximum accepted EEX age; positive N rejects older curves | |
| | `warn_stale_days` | 3 | Age at which the log message becomes ERROR | |
| `timezones` | by area | Europe/Berlin | Used only when drafting the mapping | |
| `targets` | `tenors` | Complete configured list | Target labels to calculate | |
| `conventions` | `day` | calendar | D+n in calendar or business days | Review with `detect-conventions` |
| | `weekend_offset` | 0 | Shifts WE+n numbering | |
| `method` | `basis_mode` | auto | Per-target selection, step 3b; ratio forces relative adjustments and additive forces price differences | |
| | `min_volume` | 0 | Minimum known anchor volume; originals remain preserved | Fewer adjustment anchors |
| | `tau_log` | 0.5 | Reach of an anchor along the curve | Distant anchors matter more; smoother curve |
| | `other_kind_weight` | 0.6 | Weight for a different contract kind | More mixing across kinds |
| | `shrink_k` | 1.0 | Evidence required to trust today's anchors | More weight on the prior |
| | `ewma_halflife_days` | 10 | Ratio memory in observation days | More stability, slower response |
| | `hist_auto_min_obs` | 10 | Effective comparison days before `auto` decides; valid history is used beforehand | Later decisions with more evidence |
| | `max_anchor_dev` | 0, disabled | Excludes anchors when abs(VWAP − EEX) / max(abs(EEX), ratio_eex_floor) exceeds the limit; preserves originals | Allows larger deviations |
| | `ratio_eex_floor` | 1.0 | Minimum abs(EEX) for ratio anchors; auto selects additive for targets below it | Excludes more ratio anchors and selects additive for more targets |
| | `max_ratio_deviation` | 1.0 | Maximum abs(VWAP/EEX − 1) for anchors and final ratio adjustment | Allows larger adjustments |
| | `hist_max_age_days` | 60 | Calendar-day expiry since the latest real observation, separately by kind/group/global | Retains history longer |
| `correlation` | `halflife_days` | 20 | Correlation memory for improvement 1 | More stability, slower response |
| | `prior_obs` | 8 | Common evidence scale for measured correlation to dominate | More conservative measured weights |
| `cross` | `min_corr` | 0.5 | Minimum recent correlation to use another product | Fewer eligible products |
| | `min_obs` | 8 | Minimum effective joint observation days | Later activation |
| | `halflife_days` | 20 | Correlation and β memory | |
| `run` | `warmup_days` | 0 | 0 uses all available original history; positive N limits prior calendar days | Positive N limits memory relative to 0 |
| `vwap_columns` | … | `power_row_…` schema | Aliases for reference date, product, region, unit, tenor (`tenor2`), VWAP and volume (`total_volume`) | |

---

## 7. Evaluating the method

- **`python run.py detect-conventions`** compares D+n and WE+n with EEX under each convention.
  Smaller discrepancies help identify the convention; confirm what the labels mean and set
  `[conventions]` accordingly.
- **`python run.py backtest`** performs leave-one-out evaluation: hide an own VWAP, predict it
  from the remaining information, and measure error by tenor group:
  - `eex`: unadjusted EEX.
  - `local_*`, `hist_*`, `blend_*`: analytical variants in ratio and additive modes.
  - `local_corr_*`, `blend_corr_*`: improvement 1.
  - `hist_cross_*`: improvement 2, simulating no own anchors that day; compare with `hist_*`.
  - `pipeline_configured`: calls the same filling path as `daily`/`refill`, using the configured
    layers, filters and limits after removing the hidden period's own quote and all its anchors,
    including aliases **in both modes**. Auto selects the formula again after hiding them,
    rather than retaining a decision based on the observation being predicted. This evaluates
    the deployed configuration.

  Improvement variants are evaluated even when disabled, supporting a data-based decision
  about enabling them. Improvement 2 requires several mapped `fill` or `helper` products.

The report contains `n`, `mae`, `bias` and `rmse`, grouped by unit, method and tenor group;
EUR/MWh and GBP/MWh errors are not averaged together. For a fair comparison with EEX, it adds
`n_paired`, `mae_paired`, `mae_eex_paired` and `mae_improvement`, using only observations where
both methods have a prediction. Positive `mae_improvement` means the method reduces absolute
error relative to EEX on those same cases. Matching uses date, product, region, unit, tenor and, if present,
scenario. Do not compare unpaired overall MAEs when method coverage differs. Detail and summary
are written to `backtest_loo.csv` and `backtest_report.csv`.

Synthetic truth comparison is also grouped by unit, and `detect-conventions` reports its
discrepancies by unit. Keeping identities separate does not convert currencies.

### Historical factor or unadjusted EEX on days without VWAPs? (`[layers] hist`)

The historical factor helps when your deviation from EEX **persists across days**.

- **Persistent factor**, such as 0.992, 0.991, 0.993, 0.992: yesterday's factor informs today,
  and EEX × 0.992 can outperform unadjusted EEX.
- **Unstable factor**, such as 0.985, 1.006, 0.991, 1.009 around 1: yesterday's deviation may
  tell little about today, so applying it adds noise and unadjusted EEX can perform better.

With `hist = auto`, each day with anchors compares the earlier historical factor against
unadjusted EEX on your own observations. Scores are maintained by group (short, month,
quarter, long); the better prior is used when own observations are absent. Until
`hist_auto_min_obs` effective comparison days are available, valid history is used.

This comparison is maintained separately for ratio and additive. For each mode/group, mean
absolute errors across that day's eligible anchors are accumulated with exponential decay.
Once effective mass reaches `hist_auto_min_obs`, history is allowed when its accumulated error
does not exceed EEX error; ties allow history. This chooses whether to use history within a
mode. Choosing ratio or additive is the separate `basis_mode` decision from step 3b.

Illustrative synthetic backtest mean absolute errors:

| Group | `hist_ratio` | `eex` | `auto` choice |
|---|---|---|---|
| Days/Weeks | 0.82 | **0.74** | Unadjusted EEX |
| Months | 0.77 | **0.71** | Unadjusted EEX |
| Quarters | **0.62** | 0.63 | History, nearly tied |
| Seasons/Cals | **0.53** | 0.56 | History |

Real data may give the opposite result, which is why the default is `auto`.
Synthetic data (`make-synthetic` followed by `backtest --truth data/synthetic_truth.csv`)
check the mechanics. **Useful performance conclusions require the real input.** Synthetic
generation defaults to ratio mode, favouring that mode by construction; `--mode additive`
can generate an additive scenario instead.

---

## 8. Current limitations

- Before local EEX coverage begins, 10 August 2026 in the DE example, only own VWAPs and
  contract construction are available.
- The engine can use only EEX history present in local files; filling does not download or
  recover absent publications.
- An isolated daily input cannot reconstruct historical ratios. Earlier original observations
  are required; filled prices are not new training observations.
- After `hist_max_age_days` without valid observations, the corresponding historical factor
  expires. Predictions then rely on valid fallback history, today's anchors, or EEX alone.
- Improvements 1 and 2 require common history to develop sufficient evidence
  (`prior_obs`, `min_obs`).
- The inspected local EEX coverage starts in August 2026. Input observations from 2025 require
  additional historical EEX files to benefit from that year's curve shape.
- The program does not convert currencies/units, substitute another area's curve, or change
  VWAPs to force agreement between months, quarters and years.
- Missing tenors outside `[targets].tenors` are not created. Unknown tenor labels are preserved
  as originals, but the engine cannot resolve their deliveries or estimate them.
- Synthetic metrics test mechanics under the assumptions used to generate the sample.
  **Evaluation using the user's real input and contemporaneous EEX remains pending**, especially
  for days without anchors, near-zero prices, Peak delivery and month-end residuals.

---

## 9. (product, region, unit)-to-EEX mapping (`mappings/products.csv`)

Your input can contain many products, such as `DE_Base load`, `FR_Peak load` and
`GB_Other_Block_1_2`. The engine needs to know **where each product/region/unit combination's
EEX data is located**. An editable CSV, which can be reviewed in Excel, contains one row per
complete curve identity:

| Column | Meaning | Example |
|---|---|---|
| `product` | Exact input name; alone it does not identify a curve | `DE_Base load` |
| `region` | Exact input region; empty matches only empty | `DE` |
| `unit` | Exact input unit; no conversion or wildcard matching | `EUR/MWh` |
| `use` | `fill`: calculate; `helper`: assist; `off`: excluded. Fill/helper also require an assigned `eex_file`; originals remain in every case | `fill` |
| `area`, `profile` | Output labels | `DE`, `Base` |
| `eex_file` | Path relative to `eex_curves_dir`; empty means unassigned and excluded from the engine | `DE/Base.csv` |
| `hours` | Base: actual local hours; Peak: 12 h every day for Day/Weekend, Monday–Friday otherwise; Peak7: 12 h every day | `Base` |
| `timezone` | Delivery time zone | `Europe/Berlin` |
| `comment` | Free text | |

**Workflow:**

1. `python run.py mapping` reads the input and **adds new identities with `use = off`**,
   proposing an EEX file from the name and preserving decisions in existing rows.
2. It reports the target EEX file, whether it exists, the first EEX date and VWAP count.
3. Review `eex_file`, `hours` and other fields, explicitly activate the desired rows as
   `fill` or `helper`, then rerun `mapping`.
4. Other commands process `fill` identities and `helper` identities for assistance
   **only when `eex_file` is nonempty**.
   Unmapped products generate a warning and do not get calculated curves, but their original
   rows, as well as `helper` and `off` rows, remain in the enriched output.

The mapping controls scope: finding an EEX curve does not activate a newly drafted row.
`use = fill/helper` with empty `eex_file` is excluded as `mapping_unassigned`. This differs
from an assigned file that is absent or lacks quotes: that identity is active, the missing
data is reported, and originals/contract construction remain available.

The header is `product,region,unit,use,area,profile,eex_file,hours,timezone,comment`.
The same product name can appear several times when region or unit differs; duplicate complete
identities are an error. Mapping `area`/`profile` fields do not replace `region`/`unit`.
All three identity components match after trimming whitespace, preserving case and spelling.

**Migrating an older mapping.** If `region` or `unit` columns are absent, the `mapping` command
fills them automatically only when every old row matches exactly one input identity using the
columns already present. Existing `eex_file`, `use`, hours and other manual decisions remain.
Zero or multiple compatible identities cause an error without rewriting the file: add the
columns and one explicit row per combination manually. A present column containing an empty
value is not considered absent; its value remains literal. `daily`/`catchup`/`refill` do not perform
this mapping migration themselves.

Draft mapping guesses:

- `XX_Base load` → `XX/Base.csv`; `XX_Peak load` → `XX/Peak.csv`.
- If only a different Peak variant exists, such as ES `PeakMo-Su`, it proposes `hours = Peak7`
  with a comment asking for a product-equivalence review.
- No curve, such as the example BE Peak case → empty `eex_file`, `use = off`, and a comment.
- Other blocks that are not Base/Peak → `use = off` for manual review.

All new rows start as `off`, including Base/Peak rows with a proposed file.

If the EEX source moves, change `eex_file` or `eex_curves_dir`. The replacement file needs
`tradeDate`, `maturityType`, `deliveryStart` and `settlPx`.

**Illustrative EEX coverage gaps** from an earlier test of eight areas × Base/Peak.
This table describes those files and does not guarantee current product coverage. The engine
can estimate only from the quotes it receives.

| Gap | Area/product | Reason in the earlier sample |
|---|---|---|
| M+7 … M+10 | ES, IT, NL, BE | Around seven quoted monthly contracts |
| WE+2, WE+3 | All | Few forward weekends |
| Most tenors | BE Peak and other areas without Peak files: BG, DK, FI, GR, IE, Nordics | No Peak curve in that sample |
| M+4 onward, Peak D+n | GB | Limited GB contract coverage |
| Sum+3 | All | Quarterly horizon does not extend far enough |

A possible approach, **not implemented**, is borrowing another area's shape: retain the
level of an available local contract and distribute it using a reference curve's detail:

```text
ES M+8      = ES Q containing M+8 × (DE M+8 / DE Q)
BE Peak M+1 = BE Base M+1 × (FR Peak M+1 / FR Base M+1)
```

---

## 10. Improvements: implemented, disabled by default

Enable `[layers] correlation` and `[layers] cross` in `config.toml`; their parameters are in
`[correlation]` and `[cross]`. The backtest evaluates their analytical variants regardless.

**The key quantity is the surprise:**

```text
surprise(mode, date, product, group) = today's basis in that mode − its historical basis through yesterday
```

It measures today's deviation from the usual relationship. If market conditions affect
several products similarly during the day, their surprises may share a sign. The improvements
measure **how those surprises move together**, rather than raw price correlation, which EEX
already supplies as part of the curve.

Correlation and β use exponentially weighted memory (`halflife_days`). When a new pair is
observed, prior effective mass `n` is discounted by the calendar time since the previous pair,
including days without joint observations. Only real own observations with same-day EEX
enter those pairs; historical ratio means also have their separate expiry rule.

These calculations are separate in ratio and additive modes: ratio surprises are fractions;
additive surprises are price differences. Covariances, correlations, β and history scores
from one mode are never reused as if they had the other's units. The percentage examples
below show ratio mode; additive uses the same mechanics with price differences.

### Improvement 1 — Measured weights between groups (`[correlation]`)

Without this improvement, an anchor from another group, such as a Day used for a Quarter,
gets the fixed `other_kind_weight`, default 0.6. With the improvement, its weight depends on
measured correlation between the groups' surprises:

```text
a = n / (n + prior_obs)             n = effective common observation days
kind_weight = a × max(corr, 0) + (1 − a) × other_kind_weight
```

- With little data, the fixed 0.6 dominates. With more data, measured correlation dominates.
- If Days have near-zero correlation with Quarters, their effect on Quarter estimates shrinks.
- Measurement is by short/month/quarter/long groups, not each contract pair, because individual
  contract pairs have too few observations.

### Improvement 2 — Use another product on days without own VWAPs (`[cross]`)

For example, DE Base has few or no own VWAPs today while FR Base has observations.

This layer corrects **basis surprises**. It is not a raw-price regression of the form
`price_ES = alpha + beta × price_FR`. It needs an EEX curve for the target, valid own target
history, and an estimated relationship with the helper's surprises. Another country's quotes
cannot by themselves fill a product that never had own history or has no EEX curve. In the
current configuration, `cross = false` and `correlation = false`.

`hist = off`, or rejection by `auto`, does not by itself disable cross. If valid internal
history exists and cross is enabled, the cross surprise can still be applied. The prior is
`(allowed historical adjustment, or 0) + cross_adj`: history is added only when the hist layer
allows it. Therefore `cross_adj` can be present while `basis_hist` is empty.

**Illustrative Month example:**

1. Today's FR ratio is −1.5%, against a historical −0.5%: **surprise = −1.0%**.
2. In earlier joint DE/FR observations:
   - Surprise correlation is **0.8**, above `min_corr = 0.5`.
   - β is **0.8**: the DE surprise moves 0.8 units per unit of FR surprise.
3. The DE adjusted ratio is:
   ```text
   historical DE + β × FR surprise = −0.8% + 0.8 × (−1.0%) = −1.6%
   ```
4. The resulting estimate is:
   ```text
   DE M+3 = DE December EEX × (1 − 0.016)
   ```

Details:

- Several eligible helpers are combined using corr² weights.
- The helper's same group is used when available; otherwise its global surprise is tried.
- If no helper meets `min_corr` with at least `min_obs` effective common days, no cross
  adjustment is applied and valid history can remain as `eex+hist`.
- With some local anchors, the cross-adjusted prior is blended with local evidence using `w`.
- `cross_from` records helpers and their correlations, for example `FR_Base(0.82)`.

**Earlier synthetic result**, DE Base with FR/NL/AT assistance on days without DE observations:
error moved from 0.75 for `eex+hist` to 0.57 in cells where `eex+cross` acted. Improvement 1
barely changed the synthetic result, 0.411 versus 0.411. Those samples deliberately contained
the simulated co-movements: **use a backtest on real data to decide whether to enable them**.

---

## 11. Daily use, pending recovery and historical refill

Both uses share the same configuration, whose default input is `data/vwaps.xlsx`. To test a
separately generated synthetic history, select it explicitly; synthetic files are not included
in the portable package:

```powershell
.\.venv\Scripts\python.exe run.py refill --from 2026-08-10 --to 2026-09-30 --vwap data/synthetic_vwaps.csv
.\.venv\Scripts\python.exe run.py daily --date 2026-09-30 --vwap data/synthetic_vwaps.csv
```

`refill` processes a range; `daily` processes one date. Both rebuild available prior memory
and produce `filled` and `enriched` outputs without switching algorithms. The final date
matches the inspected local coverage. These demonstration commands do not validate real
VWAP input and do not change the configuration's default input path.

When using the real file, follow this preparation and review sequence:

1. Place the accumulated original input at a known location, such as `data/vwaps.xlsx`.
   If it is elsewhere, change `[paths].vwap_input` or pass `--vwap` each time. Relative
   paths are resolved against the configuration file's directory.
2. Confirm `[vwap_columns]`, including region and unit, and run `mapping`. Review complete identities, `use`, `eex_file`,
   `hours` and `timezone`; also check currency/unit and EEX date coverage.
3. Adjust `[targets].tenors` if additional maturities should be created. Run
   `detect-conventions` over comparable observations; its aggregate discrepancies inform the
   decision, but confirm the meaning of the labels.
4. Run `refill` over the available range. Use `enriched_history.csv` for the extended original
   format, and `filled_history.csv` to inspect the aggregated curve.
5. Run `backtest`; compare `pipeline_configured` with EEX on the same observations using
   `mae_improvement` and `n_paired`. Compare configurations on the same data to evaluate a layer.
   Better results on very few cases do not demonstrate improvement across all gaps.
6. For daily execution, supply accumulated originals to reconstruct memory, run `daily`, and
   inspect the log, `missing` cells, EEX age and methods used.

Example commands; substitute files and dates that actually exist:

```powershell
.\.venv\Scripts\python.exe run.py mapping --vwap data/vwaps_reales.xlsx
.\.venv\Scripts\python.exe run.py detect-conventions --vwap data/vwaps_reales.xlsx
.\.venv\Scripts\python.exe run.py refill --from 2026-08-17 --to 2026-09-30 --vwap data/vwaps_reales.xlsx
.\.venv\Scripts\python.exe run.py backtest --from 2026-08-17 --to 2026-09-30 --vwap data/vwaps_reales.xlsx
.\.venv\Scripts\python.exe run.py daily --date 2026-09-30 --vwap data/vwaps_reales.xlsx
.\.venv\Scripts\python.exe run.py status --last 10
```

A global config argument goes before the command:
`.\.venv\Scripts\python.exe run.py --config config_real.toml daily --date 2026-09-30`.
Patterns such as `--vwap "data/vwaps_*.csv"` are supported; all matching files must be
compatible originals. Do not include both an accumulated file and its component files, which
would duplicate engine observations. Enriched output is not training input: reserved
`data_origin`, `estimation_method` and `curve_*` columns are rejected during enrichment.

## 12. Auditing a row

### 12.1. Meaning of each added field

`filled_history.csv` uses engine field names without a prefix. In `enriched_history.csv`,
trace fields use `curve_*` to preserve original columns. Three separate concepts are recorded:
**price origin** (`data_origin`), **summary source** (`curve_source`) and **actual method**
(`estimation_method`). A new row has origin `estimated` or `missing`, even when its price is
obtained from an already observed equivalent contract with another label.

| Enriched field | Meaning |
|---|---|
| `data_origin` | `original`, `estimated` or `missing`, describing this row's usable price |
| `estimation_method` | Applied combination, such as `ratio_local_history_cross`, `additive_local`, `eex`, `contract_residual`, or `own_equivalent_period` for a differently labelled own period |
| `curve_reference_date` | Normalized observation date, not delivery date |
| `curve_product` | Normalized product name used for matching |
| `curve_region` | Normalized identity region; empty is a literal value |
| `curve_unit` | Normalized identity unit; does not imply currency or unit conversion |
| `curve_tenor` | Relative tenor label |
| `curve_row_type` | `original`, `original_invalid` or `added`, relative to the input |
| `curve_price` | Usable price; preserves each valid original VWAP and supplies an estimate for an invalid one when possible |
| `curve_source` | `own`, `eex+local`, `eex+hist`, `eex+cross`, `eex`, `arbitrage` or `missing` |
| `curve_area` | Mapped area |
| `curve_profile` | Mapped profile |
| `curve_kind` | Resolved contract kind: Day, Month, Quarter, etc. |
| `curve_period` | Readable name of the resolved delivery period |
| `curve_delivery_start` | Inclusive delivery start |
| `curve_delivery_end` | Exclusive delivery end |
| `curve_hours` | Target contract hours under its delivery profile and time zone |
| `curve_confidence` | Heuristic score described in section 4 |
| `curve_basis_mode` | Applied mode: `ratio` or `additive`; on an original row this does not mean the observed VWAP was adjusted |
| `curve_configured_basis_mode` | Requested configuration: `auto`, `ratio` or `additive` |
| `curve_own_vwap` | Own observation; valid original rows show their individual value |
| `curve_own_volume` | Original volume when available; not estimated volume |
| `curve_eex_settle` | Direct or constructed EEX price for the target period |
| `curve_eex_method` | `exact`, `strip` or `residual`; for `arbitrage`, describes construction from available prices rather than an EEX quote |
| `curve_eex_asof` | Selected EEX curve date, allowing its age to be checked |
| `curve_basis` | Final applied adjustment, after any configured ratio clipping |
| `curve_basis_local` | Adjustment from today's anchors |
| `curve_basis_hist` | Historical adjustment allowed by layer settings and freshness |
| `curve_cross_adj` | Additional related-product correction, if used |
| `curve_local_weight` | Local blending weight `w` |
| `curve_anchors` | Up to three most influential anchor labels, not a complete anchor list |
| `curve_cross_from` | Products providing the cross correction, with correlations |
| `curve_flag` | Engine flags: `anchor_excluded`, `ratio_adjustment_limited`, `zero_delivery_hours`, and selection reasons `auto_additive_low_eex`, `auto_additive_no_ratio_anchors`, `auto_additive_history_only` |
| `curve_flags` | Engine/enrichment flags: invalid VWAP, unmapped/disabled identity, `mapping_unassigned` when EEX is unassigned, empty unit or ambiguous other metadata |

If an original row has no matching calculated curve row, some engine fields remain empty.
That neither deletes the original nor makes its value an estimate. `anchor_excluded` with
`data_origin = original` is valid: the observation is preserved but rejected as an anchor for
adjusting other contracts.

### 12.2. Reconstructing a calculation

For an estimated `M+4` row, review the following:

1. **Identity and origin.** Locate date/product/region/unit/tenor. Check whether the input lacked the row
   (`curve_row_type = added`) or had an invalid VWAP (`original_invalid`). Review `data_origin`,
   `estimation_method` and flags. An `original` price should be its individual VWAP, without
   adjustment to make it agree with the model.
2. **Delivery.** Resolve `M+4` from the reference date and compare start, end and hours with
   `curve_delivery_*` and `curve_hours`. For Peak, check the contract kind as well as the profile.
3. **EEX.** Check `curve_eex_asof`, `curve_eex_settle` and `curve_eex_method`. For `strip`,
   reconstruct the hours-weighted average of contiguous pieces. For `residual`, review parent,
   head and tail, ensuring Day fixings were already published by `asof`.
4. **Anchors.** Within that date and complete curve identity, group observations by delivery
   period and apply volume,
   deviation filters to prepare both eligible lists. Check `curve_configured_basis_mode`,
   `curve_basis_mode` and, for auto, the step 3b branch and its flag. `history_only` requires
   allowed as well as current history. For the selected mode, compute `VWAP/EEX − 1` or
   `VWAP − EEX`, then each anchor's
   volume/kind/distance weight from step 4a. `curve_anchors` helps identify the main contributors,
   but reproducing the local estimate requires all anchors.
5. **History and cross.** Reconstruct history from earlier originals and contemporaneous EEX,
   expiring each mean under `hist_max_age_days`. Check that `hist = off/auto` allows the
   recorded prior. If `curve_cross_adj` is present, identify the helpers and measured
   relationships. Today's observations update memory only after today's predictions.
6. **Blend and price.** Check `w = W/(W + shrink_k)` and
   `basis = w × basis_local + (1 − w) × (basis_hist + cross_adj)`, using only available
   components and treating a missing prior as 0. Without local anchors, `w = 0`. Apply any
   configured ratio limit and compare with `curve_basis`. Finally compute
   `EEX × (1 + basis)` in ratio mode or `EEX + basis` in additive mode.
7. **Consistency.** If the price contributes to a month/quarter/year, inspect
   `consistency_history.csv`. Deviations are reported; the engine neither changes originals
   nor reoptimizes the full curve to eliminate them.

For `source = eex`, use the recorded EEX price directly. For `arbitrage`, reconstruct the
strip or residual from available daily prices, because no basis blend was applied. For
`missing`, no price is available to audit; inspect which coverage or information was absent.

The CSV does not store the full component list of every strip/residual or a copy of the
configuration and anchors. Reproducible audits require preserving **original inputs, EEX CSVs,
mapping, configuration, code version and execution log**. Changing those files can change a
rerun even when the requested date is identical.

### 12.3. What the backtest demonstrates, and what remains to validate

Leave-one-out tests contracts that have both an own observation and EEX price: hide the
period and try to recover it. `hist_*`/`hist_cross_*` variants explore predictions without
today's own anchors, but that simulation does not guarantee the same error distribution on
actually illiquid days. `pipeline_configured` evaluates the deployed calculation; paired
columns compare it with EEX on identical observations.

Real-world validation should measure coverage and errors by product and tenor family,
distinguishing days with and without anchors, current versus stale EEX, and exact prices
versus strips/residuals. This evaluation with the real input and matching EEX history remains
pending; the earlier synthetic result tables do not replace it.

## 13. Moving the program to the machine containing the real data

The real input lives on another machine. It does not need to be copied to the development
machine: move the program and documentation to where the data already resides.

The `dist/vwaps-portable.zip` package contains code, declared dependencies, configuration and
documentation. It excludes `.venv`, synthetic data, generated outputs and the demonstration
mapping. Its initial `config.toml` uses these relative paths:

```toml
[paths]
vwap_input = "data/vwaps.xlsx"
mapping = "mappings/products.csv"
eex_curves_dir = "../eex_scraper/output/curves/POWER"
output_dir = "output"
```

Adapt these starting values to the destination machine. The EEX directory must contain long
CSVs by area/profile, such as `DE/Base.csv`. Absolute paths also work; forward slashes are
convenient in Windows TOML paths, for example `C:/data/vwaps.xlsx`.

### 13.1. Installation

1. Extract the package into a working directory on the destination machine.
2. Ensure **Python 3.11 or later** is installed.
3. Install dependencies from that directory using either approach:

```powershell
# If uv is already installed:
uv sync

# Alternative using Python and pip:
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install numpy pandas openpyxl
```

`uv sync` uses the project's dependency declarations and lockfile. The pip alternative
installs dependencies for CSV and XLSX inputs but does not pin the same versions. Do not
copy the development machine's `.venv` directory.

### 13.2. Configuration and first execution

1. Edit `[paths]` to point to accumulated real originals, EEX curves, mapping and output.
   Adjust `[vwap_columns]` if the input uses different column names.
2. Run `mapping` to create a map from product/region/unit combinations in that input. Do not reuse a synthetic-data
   mapping without reviewing it.
3. New rows start as `off`: activate only the intended identities with `fill`/`helper` and
   an assigned `eex_file`. Review area, profile, hours and time zone. Confirm currency,
   units and available date range. Initial assignments are proposals inferred from names and
   files, not certified product definitions.
4. Run `refill` over the history available on that machine. Dates below are examples; replace
   them with the actual range:

```powershell
.\.venv\Scripts\python.exe run.py mapping
.\.venv\Scripts\python.exe run.py refill --from 2025-01-02 --to 2025-01-31
.\.venv\Scripts\python.exe run.py status --last 10
.\.venv\Scripts\python.exe run.py backtest --from 2025-01-02 --to 2025-01-31
```

If only 2026 EEX curves are present, a 2025 refill preserves own observations and may construct
some prices from them, but cannot use a 2025 EEX curve shape. Increasing `warmup_days` does
not solve this absence; the corresponding EEX history is required.

### 13.3. Daily execution

Keep `warmup_days = 0` and point `vwap_input` to accumulated originals, or a file pattern that
includes earlier history without duplication. After updating EEX curves and the input, run:

```powershell
.\.venv\Scripts\python.exe run.py daily
# Or select a date to repeat or review:
.\.venv\Scripts\python.exe run.py daily --date 2025-02-03
```

Without `--date`, the machine's local date is used. A file containing only current-day rows
does not supply earlier memory. Do not use `enriched_history.csv` as new input.

Review `output/enriched/<date>.csv`, `output/enriched_history.csv` and the log. `data_origin`
and `estimation_method` distinguish observations from estimates. Exit code 1 requires checking
the log; if the engine recorded errors, existing results have not been replaced by a partial
run. Preserve the package version, configuration, mapping and source files used for a
reproducible review.


To recover pending runs through today, use `python run.py catchup`, optionally with `--from`
and `--to`. It exports only pending fill curves; use daily/refill to revisit processed results
or enrich the complete input. See section 5.


---

## 14. Complete configuration reference: what controls each decision

This chapter is a complete reference to the **46 keys in the supplied `config.toml`**. Defaults below refer to that file, not to a partially omitted configuration. Edit existing TOML sections without duplicating them. A setting changes model behavior or data selection; increasing it does not generally make prices higher, better or more accurate.

The tables distinguish a parameter's effect from the conditions under which it matters. Numeric operating ranges are guidance unless explicitly described as loader validation. Validate finite values and sensible ranges when editing the configuration; the loader does not enforce every recommended bound.

### Paths: selecting the evidence and output

| Key | Supplied default | What it controls and effect of changing it | When it applies / constraints |
|---|---|---|---|
| `paths.vwap_input` | `"data/vwaps.xlsx"` | Original accumulated observations. A broader CSV/Excel glob includes more files and history; a narrower input can remove anchors and historical evidence. | Input-reading commands. Relative to this config; `--vwap` overrides it for one command. Use originals, not enriched output, and avoid overlapping snapshots that duplicate trades. |
| `paths.mapping` | `"mappings/products.csv"` | Exact `(product, region, unit)` to EEX assignments and each curve's `fill/helper/off` decision. Changing files can change the active universe. | Mapping and calculation commands. New drafts stay `off`; `fill/helper` with an empty `eex_file` remains inactive. Review identity, currency and delivery profile before activation. |
| `paths.eex_curves_dir` | `"../eex_scraper/output/curves/POWER"` | Root used to resolve each mapping row's `eex_file`, such as `DE/Base.csv`. A different dataset changes settlements and available history. | EEX loading. Relative to the config; mapping paths are relative to this root. Required EEX fields: `tradeDate`, `maturityType`, `deliveryStart`, `settlPx`. This is not a download command or currency conversion. |
| `paths.output_dir` | `"output"` | Destination for enriched/calculated histories, daily files, reports and logs. A new folder starts a separate result history. | Writing/reporting commands. Preserve a separate output folder when comparing configurations. Legacy result files without complete curve identity are rejected before result writes. |

Absolute paths are allowed. A file assigned in the mapping but unavailable for reading is reported in the log; existing own observations and eligible contract reconstruction can still be used. Missing, nonnumeric and nonfinite EEX prices are excluded with a warning, without changing valid prices.

### Layers: which information can influence an estimate

| Key | Default | What changes when enabled or disabled | When it applies / dependencies |
|---|---|---|---|
| `layers.local` | `true` | On: nearby original VWAPs from today adjust the target's EEX price. Off: removes that local contribution, increasing reliance on permitted history/cross or raw EEX. | Estimated targets with EEX. Distance, volume, type weights and `shrink_k` determine influence. Originals remain unchanged either way. |
| `layers.hist` | `"auto"` | `on`: allow current historical basis. `off`: do not add that historical mean. `auto`: allow history unless sufficient earlier comparisons show raw EEX performs better. | Per mode and target group; needs unexpired history. `hist_auto_min_obs` delays the comparison decision. Off does not erase internal history or disable cross, which has its own switch. |
| `layers.correlation` | `false` | On: measured relationships between tenor groups can replace part of the fixed other-kind weight. Off: use fixed distance/type weights. | Local estimation between different groups. Requires paired surprises; sparse data retain the prior. It does not by itself bring in another product's price. |
| `layers.cross` | `false` | On: correlated surprises in other active curves can adjust the historical prior. Off: a curve uses its own observations/history and EEX only. | Requires the target's EEX and internal historical baseline, usable helper surprises, enough joint observations and adequate correlation. `fill` and `helper` curves with assigned EEX may help; `off` and unassigned curves may not. |
| `layers.arbitrage` | `true` | On: attempt strip/residual reconstruction from known contracts when EEX cannot price a target. Off: such unresolved targets remain missing. | Fallback after direct EEX-based pricing. Needs a compatible delivery-hour calendar and enough covering contracts. It does not rewrite original prices or force every inconsistency away. |

Auto mode selection never turns on a disabled layer. Ratio and additive histories, scores, covariances and helper coefficients are separate. Defaults leave correlation and cross disabled until their usefulness has been checked on real data.

### EEX freshness: coverage versus age

| Key | Default | Increasing / decreasing | When it applies / constraints |
|---|---|---|---|
| `eex.max_stale_days` | `0` | Zero means unlimited past age. Among positive values, increasing admits older publications and may increase coverage; decreasing rejects them sooner. | Publication selection for each reference date; use a nonnegative integer. Never uses future publications. Zero does **not** mean same-day only. Same-day EEX is still required for training history. |
| `eex.warn_stale_days` | `3` | Increasing delays escalation of stale-data messages to ERROR; decreasing makes the log more sensitive. | Logging only. Use a nonnegative integer. It does not reject settlements, alter prices, or fail a run by itself; `max_stale_days` controls acceptance. |

### Time zones: delivery hours, not a price adjustment

These names are IANA delivery time zones. They seed newly drafted mapping rows and supply the fallback for a blank mapping timezone; an explicit mapping value takes precedence. There is no numerical increase/decrease direction: changing the zone changes daylight-saving and delivery-hour interpretation. It can therefore change strip/residual weights, without a fixed direction for the resulting price.

| Key | Default | Scope / effect of replacing it | Constraints and dependencies |
|---|---|---|---|
| `timezones.default` | `"Europe/Berlin"` | Fallback for areas without an explicit override. | Use a valid zone for the actual delivery market; existing explicit mapping zones are not overwritten. |
| `timezones.GB` | `"Europe/London"` | GB drafting/fallback override. | Applies with the mapping's `hours` convention; this is not currency handling. |
| `timezones.IE` | `"Europe/Dublin"` | IE drafting/fallback override. | Same delivery-market requirement; no automatic remapping of existing explicit values. |
| `timezones.PT` | `"Europe/Lisbon"` | PT drafting/fallback override. | Check it against the contract's actual delivery clock. |
| `timezones.GR` | `"Europe/Athens"` | GR drafting/fallback override. | Works together with Base/Peak/Peak7 hours from the mapping. |
| `timezones.RO` | `"Europe/Bucharest"` | RO drafting/fallback override. | Use the contract's zone rather than the operator's computer zone. |
| `timezones.BG` | `"Europe/Sofia"` | BG drafting/fallback override. | The mapping's explicit timezone remains authoritative. |
| `timezones.FI` | `"Europe/Helsinki"` | FI drafting/fallback override. | Additional area keys can be added using the same convention. |

### Targets and label conventions

| Key | Default | Effect of changing it | When it applies / constraints |
|---|---|---|---|
| `targets.tenors` | The 40 labels listed below | Adding labels requests more curve points; removing them reduces calculated coverage and may remove components available to reconstruction. Neither action deletes original observations outside the target list. | Active `fill` curves. Use individual supported strings; duplicate labels are deduplicated. A requested tenor can still be missing or have no delivery hours. |
| `conventions.day` | `"calendar"` | `business` moves D+n over Monday-Friday business days; `calendar` counts every day. This changes the delivery contract being matched, not merely its name. | Resolving day labels in originals and targets. Loader accepts only `calendar` or `business`; no holiday calendar is provided. Check with `detect-conventions`. |
| `conventions.weekend_offset` | `0` | Increasing shifts WE+n further into the future; decreasing shifts it earlier relative to the normal next-weekend convention. | Resolving weekend labels and matching EEX periods. Integer shift; use a convention justified by the source data rather than a parameter search to improve fit. |

The supplied list is `D+1, D+2, D+3, WE, WE+1, WE+2, WE+3, BOW, W+1, W+2, W+3, W+4, BOM, M+1, M+2, M+3, M+4, M+5, M+6, M+7, M+8, M+9, M+10, Q+1, Q+2, Q+3, Q+4, Q+5, Q+6, Q+7, Q+8, Sum+1, Sum+2, Sum+3, Win+1, Win+2, Win+3, Cal+1, Cal+2, Cal+3`.

### Pricing and history: the eleven model controls

| Key | Default | Increasing / decreasing or switching | When it applies / constraints |
|---|---|---|---|
| `method.basis_mode` | `"auto"` | `ratio` uses proportional basis; `additive` uses price differences; `auto` chooses by target using price stability and available evidence. These are alternative formulas, not ordered levels of aggressiveness. | Loader accepts exactly these three values. Own prices are preserved. Output records the configured mode and effective mode. Mode-specific exclusions do not discard otherwise valid additive evidence. |
| `method.min_volume` | `0` | Increasing excludes more known low-volume observations from anchoring; decreasing admits more. This can reduce noise but also reduce coverage/evidence. | Common anchor filter before both modes; use a nonnegative threshold in the input volume units. Missing/invalid volume is unknown, not automatically below the threshold. Originals remain unchanged. |
| `method.tau_log` | `0.5` | Larger spreads anchor influence farther along the delivery curve; smaller makes estimation more local and can reduce total local evidence W. | Local weights use exponential distance in log time to delivery. Loader requires >0. It changes both relative anchor selection and shrinkage through W; it does not affect a disabled local layer. |
| `method.other_kind_weight` | `0.6` | Larger admits more influence from another contract kind; smaller favors same-kind anchors. Zero removes the fixed other-kind contribution. | Local weighting. Use a nonnegative value; 0..1 is a conservative attenuation range. Correlation can still supply a measured between-group component when enabled; same-kind weight is 1. |
| `method.shrink_k` | `1.0` | Larger reduces today's weight `w=W/(W+k)` and favors the permitted prior; smaller trusts today's anchors more. Without a prior, shrinkage is toward raw EEX. | Local/history blending; loader requires >0. Direction of price movement depends on the local basis and prior, so larger k does not necessarily lower price. |
| `method.ewma_halflife_days` | `10` | Larger makes historical basis and its skill scores adapt more slowly; smaller reacts faster and forgets older observations sooner. | Separate ratio/additive histories and historical error scores. Loader requires >0. Counts valid observation updates, not elapsed calendar days; expiry is controlled separately. |
| `method.max_anchor_dev` | `0` | Zero disables this filter. Among positive values, larger admits more deviation; smaller rejects more. Moving from 0 to a positive bound activates filtering rather than loosening it. | Common filter: `abs(Own-EEX)/max(abs(EEX),ratio_eex_floor) > bound`. Use >=0. A rejected anchor still remains an original output value; both modes lose that anchor. |
| `method.ratio_eex_floor` | `1.0` | Larger rejects more near-zero ratio anchors and makes auto choose additive for more low-price targets; smaller permits ratios closer to zero, increasing sensitivity to small denominators. | In the curve's price units; loader requires >0. Exactly at the floor is eligible. Also enters the common deviation filter's denominator. Does not clamp, replace or change the sign of EEX prices. |
| `method.max_ratio_deviation` | `1.0` | Larger admits larger proportional anchor differences and permits a larger final ratio adjustment; smaller tightens both. | Ratio only; loader requires >0. Applies to `abs(Own/EEX-1)` and the final ratio basis. Opposite-sign ratios remain unusable. It does not cap additive differences or overwrite originals. |
| `method.hist_max_age_days` | `60` | Larger permits older basis means to remain usable; smaller expires them sooner and increases reliance on today's evidence or raw EEX. | Positive calendar-day limit; loader requires >0. A kind/group/global mean expires after more than N days since its last valid own observation. A current group/global fallback can remain after one kind expires. |
| `method.hist_auto_min_obs` | `10` | Larger delays evidence-based acceptance/rejection of history; smaller allows an earlier, noisier decision. Before reaching the threshold, available history is allowed. | Only controls `layers.hist="auto"`; use a nonnegative effective observation mass. Scores are separate by mode/group and decay with `ewma_halflife_days`, so this is not a raw row count. |

Auto chooses additive if the target's absolute EEX price is below the floor; otherwise ratio when usable ratio anchors exist; otherwise additive when additive anchors exist; otherwise additive when only an allowed, current additive history exists; otherwise ratio. A low-price fallback with no usable adjustment can still return unadjusted EEX. History learns only from original anchors with same-day EEX, after prediction; estimated output never trains the model.

### Correlation and cross-curve assistance

| Key | Default | Increasing / decreasing | When it applies / constraints |
|---|---|---|---|
| `correlation.halflife_days` | `20` | Larger retains paired surprise evidence longer and smooths changing relationships; smaller adapts faster with less stable effective sample size. | Between-group correlation when `layers.correlation=true`. Use >0. Covariance decay measures calendar gaps between valid paired observations, unlike the basis EWMA update count. |
| `correlation.prior_obs` | `8` | Larger keeps weights closer to `other_kind_weight` for longer; smaller hands control to measured positive correlation sooner. | Blend weight is `n/(n+prior_obs)`. Use >=0; zero removes prior shrinkage when usable covariance exists, but does not create a relationship with no data. |
| `cross.min_corr` | `0.5` | Larger admits fewer, more strongly correlated helpers; smaller broadens eligibility and may admit weaker relationships. | `layers.cross=true`, with usable variance and beta. Normally choose 0..1; thresholds alone do not ensure predictive value. |
| `cross.min_obs` | `8` | Larger waits for more effective joint observations before using a helper; smaller permits earlier, less stable assistance. | Use >=0; effective mass is discounted by `cross.halflife_days`, not simply the number of paired rows. Also subject to the correlation threshold. |
| `cross.halflife_days` | `20` | Larger retains historical helper relationships and beta longer; smaller follows regime changes faster but reduces effective evidence after gaps. | Cross covariance and beta; use >0. Calendar-gap decay, separate by mode and ordered target/helper identity. It does not set the target's historical basis memory. |

Cross coefficients map a helper's surprise to the target's basis scale; they do not validate currencies or convert settlement files. Each mapped EEX series must already match its own curve's currency, unit and delivery contract. The additional layers should stay off until out-of-sample real-data comparisons justify them.

### Replay history

| Key | Default | Increasing / decreasing | When it applies / constraints |
|---|---|---|---|
| `run.warmup_days` | `0` | Zero replays all supplied earlier original history. Among positive values, larger retains more prior context and takes more work; smaller trades historical context for shorter warmup. | Loader requires a nonnegative integer. A positive limit can make a short daily run differ from a long refill. It does not fetch absent inputs: supply accumulated originals and EEX history. |

### Input schema assignments

These seven values are **column names**, not numerical parameters. Changing one redirects the parser; it does not convert units, alter prices or rename the original columns in the enriched output. Choose actual, distinct input columns for their intended meanings.

| Key | Default column | Meaning / effect of replacement | Constraints and dependencies |
|---|---|---|---|
| `vwap_columns.reference_date` | `"reference_date"` | Select the curve's observation/reference date column. | Mandatory; dates must parse and cannot be blank. This is not the delivery start date. |
| `vwap_columns.product` | `"product"` | First component of exact curve identity. | Mandatory, nonempty names; surrounding whitespace is normalized for matching, originals retained. |
| `vwap_columns.region` | `"region"` | Second identity component; separates same-named products by region. | Column mandatory; a blank value is a literal identity, not a wildcard or inferred market. |
| `vwap_columns.unit` | `"unit"` | Third identity component, including currency/price unit as supplied. | Column mandatory; no automatic FX/unit conversion. Different unit strings form distinct curves. |
| `vwap_columns.tenor` | `"tenor2"` | Select the relative delivery label, such as M+1. | Column mandatory. Unsupported labels are preserved as original rows but cannot provide a resolvable anchor. Depends on label conventions. |
| `vwap_columns.vwap` | `"vwap"` | Select observed prices. Numeric values, including zero/negative prices, can be originals. | Column mandatory. Empty, invalid and nonfinite values remain in original cells but are excluded from anchors; use `curve_price` for their usable filled value. |
| `vwap_columns.volume` | `"total_volume"` | Select observation volume used in aggregation and anchor weighting. | Column optional. Missing/nonfinite/negative volume is unknown; it does not invent volume for added rows. Known volume interacts with `min_volume`; influence grows with log volume. |

For a controlled comparison, change one family of settings at a time, retain the same original data and mapping, and write to a separate output directory. Compare `pipeline_configured` against EEX on matching held-out observations within each unit. Passing mechanical tests or improving synthetic errors does not establish predictive quality on the real production dataset.

Missing, nonnumeric or nonfinite EEX settlements are excluded with a warning; valid quotes
remain. A nonfinite calculated result is an error and prevents result writes.


---

## 15. Select parameters against real originals: `tune`

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
