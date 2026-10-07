# Backtesting: what is measured, and what still needs testing

[Español](BACKTEST.es.md) · [Algorithm](ALGORITHM.md) · [Output dictionary](OUTPUT.md)

This guide distinguishes **implemented evaluation** from **proposed experiments**. The proposals
below are not pricing features. The optional shape layer in the final section is implemented and off by default. A reasonable-looking curve is a hypothesis to test, not
evidence that its missing prices are accurate.

The [MLflow notebook and guide](MLFLOW.md) provide editable candidate lists, local experiment
tracking, a synthetic demo and an expanded model grid. In this guide, `tune` refers to the
command-line interface with its original six grid fields unless stated otherwise. Both use
the same coverage-first objective and chronological winner-only validation. The notebook
example reserves five dates; the CLI default remains twenty.

## 1. A curve can look plausible and still need explanation

In the synthetic M+1/Q+2 example, EEX January, February and March all equal **150**. Additive
estimates are **132.239522, 128.569541 and 130.903094**. The trough in February comes from
local weighting: Q+2's delivery midpoint coincides with February's midpoint, strengthening
its negative basis and local evidence there.

A quarter is a **delivery-period average**, not a physical price observation at its midpoint.
Representing its influence through that midpoint is a modeling choice. Own Q+2 remains **120**,
while its estimated months average **130.637302 by delivery hours**. Neither visual smoothness
nor preservation of the quarterly original proves accurate monthly allocation.

Plot months along their delivery timeline and show quarters as separate interval averages.
Do not connect mixed M/Q labels as one continuous sequence. Power curves need not be monotonic:
seasonality and shocks can justify rises and falls.

## 2. The local model is one weighted basis estimator

Each eligible anchor contributes its basis with weight:

```text
L(t) = ln(1 + max(days to delivery midpoint, 0.5))
weight = volume_factor × kind_factor × exp(−abs(L_target−L_anchor)/tau_log)
local_basis = sum(weight×anchor_basis)/sum(weight)
w = W/(W+shrink_k); final_basis = w×local_basis + (1−w)×permitted_prior
```

Positive volume uses `ln(1+volume)`; otherwise its factor is 1. Correlation changes the kind
factor within this estimator; it is not another interpolation method. Ratio and additive
change basis coordinates and price conversion, not this distance geometry, when eligibility
matches. Without history/cross, the prior adjustment is zero.

## 3. What backtest and tune implement today

Errors target the **hidden own VWAP**, not EEX. EEX is an input and benchmark. Evaluate
`pipeline_configured`: `local_*`, `hist_*` and `blend_*` are component diagnostics that need
not reproduce production settings or its complete fallback behavior.

The CLI tune command supports six fields: `basis_mode`, `tau_log`, `shrink_k`, `layer_hist`,
`layer_correlation`, `layer_cross`. It selects **one global configuration**, not separate
parameters per curve. Other parameters remain fixed. The Cartesian grid is bounded by
`--max-trials` (default 50).

Selection first maximizes calibration coverage. Among those candidates, it minimizes the
equal-weight-per-curve mean of `MAE_model/MAE_EEX`, scored on the prediction intersection of
**all** candidates. Both errors use the same hidden originals. Coverage-first can choose a
candidate with worse MAE: that tradeoff is an explicit business policy, not a mathematical
guarantee of better predictions.
If a curve's EEX MAE is zero, its ratio is defined as 1 when the model is also perfect,
otherwise infinity.

The latest **20 distinct eligible observation dates** are reserved by default. Only the
selected candidate is evaluated there with fixed parameters; earlier originals continue
updating history chronologically. Tune requires `warmup_days=0`.

```powershell
python run.py backtest
python run.py tune --basis-modes auto,ratio,additive --hist-modes off,auto --validation-days 20 --max-trials 50
```

The second command tests six configurations when other grid flags are omitted. It needs at
least 22 eligible observation dates, including at least two calibration dates with predictions
common to all candidates, and usable holdout EEX. The one-day M+1/Q+2 experiment cannot tune.
Tune writes reports and a proposed configuration patch; it does not apply it automatically.

## 4. What hiding one period can establish

Current leave-one-out evaluation hides one own delivery period and **all equivalent aliases**
on that date, recomputes the configured targets, and scores the hidden period. Prediction
precedes that day's historical update; future publications are excluded. No direct future-price
leakage was identified in the reviewed path.

With only observed M+1 and Q+2, this can test predicting either from remaining evidence.
It cannot establish the accuracy of an unobserved M+3. Hiding one point differs from losing
a block of months or every own observation that day.

Evaluated originals need EEX and must pass common filters such as `min_volume` and
`max_anchor_dev`. Tune coverage therefore concerns **EEX-evaluable observations**, not all
requested gaps. Do not improve reported accuracy by filtering away difficult cases. Comparing
filters requires an independently fixed evaluation universe; neither the CLI nor the expanded notebook grid
vary those filters.

## 5. Proposed protocol: complete truth, realistic missingness

This protocol is **not implemented by the current leave-one-out command**:

1. Generate complete synthetic truth on a delivery grid. For coherent valuation scenarios,
   derive quarters and years from its hours-weighted pieces; test inconsistent observed-VWAP
   aggregates as a separate, explicitly defined scenario. Include additive, proportional and
   mixed worlds, seasonality, shocks, zero and negative prices.
2. Apply identical masks to every candidate: isolated periods, consecutive month blocks, only
   M+1/Q+2 visible, and days without own observations. Follow fixed absolute delivery periods
   through tenor/calendar rolls instead of confusing successive M+1 labels.
3. For persistent missingness, remove hidden observations before preparation **and every later
   history update**, including helper inputs. Do not let a hidden label re-enter training later.
   Ordinary current leave-one-out instead treats the real original as observed after scoring.
4. Separate chronological calibration, validation and a final untouched test interval. Never
   use later labels to select earlier parameters. Repeat across forecast origin dates to test
   changing regimes; this repeated-origin protocol is a proposed extension, not today's tune.

The existing synthetic generator uses group-level basis and random volumes without an explicit
volume-to-noise relationship. It is not a neutral experiment for learning whether volume
weighting or maturity structure helps. New generators must state and vary those hypotheses.

## 6. Accuracy, coverage and shape are different measurements

Current reports provide **MAE, RMSE, bias and coverage**; consistency reports compare aggregates
with available pieces. Absolute price errors must remain separated by unit. Read coverage
alongside accuracy, including missing predictions and the paired-sample size.
Zero holdout predictions mean zero coverage and unassessable errors, not perfect accuracy.

Recommended additions are P95 absolute error, adjacent-delivery spread error, quarter/month
discrepancies, and changes in the estimated **basis curvature**. Do not reward smooth or
monotonic absolute prices regardless of market structure. Track fixed-delivery price drift
through calendar rolls separately from genuine new-information moves. These added metrics
are proposals, not fields already provided by the standard reports.

## 7. Parameter families: what to compare deliberately

The CLI grid varies the six fields listed above. The [experiment notebook](MLFLOW.md) also
supports model-memory, fallback and shape fields, using flat Python names listed in that guide.
Omitted and unsupported fields stay fixed. This table is an experiment map, not an instruction
to optimize every setting or vary observation filters inside a shared ranking.

| Family | Relevant controls |
|---|---|
| Local reach and evidence | `tau_log`, `other_kind_weight`, `shrink_k`, `min_volume` |
| Coordinates and guards | `basis_mode`, `ratio_eex_floor`, `max_ratio_deviation`, `max_anchor_dev` |
| Own history | `ewma_halflife_days`, `hist_max_age_days`, `hist_auto_min_obs`, `layers.hist` |
| EEX fallback | `eex_fallback.price_method`, `price_window`, `ewma_halflife`, `spread_window`, `anchor_months` |
| Relationships | `layers.correlation`, `correlation.halflife_days`, `correlation.prior_obs`; `layers.cross`, `cross.min_corr`, `cross.min_obs`, `cross.halflife_days` |
| Availability and execution | `eex.max_stale_days`, `layers.local`, `layers.arbitrage`, `run.warmup_days` |
| Meaning and scope | Targets, identity mapping, units, schema aliases and calendar conventions: establish these correctly, rather than fitting them to reduce errors |

Increasing history, reach or complexity is not automatically an improvement. Freeze data,
scope and evaluation cases while comparing a small, interpretable family of changes.

## 8. Alternatives to test, not existing features

Potential alternatives are calendar-distance kernels, delivery-hours-overlap weights,
same-kind-first with fallback, and linear or PCHIP interpolation of monthly basis. None is
implemented as an alternative local estimator. Strict same-kind weighting is already possible
with `other_kind_weight=0` and correlation disabled, but is not same-kind-first-then-fallback.

Volume experiments could compare equal weights, current log weights, and capped/normalized
weights only when volume units are known. Start with the current model versus an overlap/calendar
candidate and equal volume weights; do not launch a search over every setting or add machine
learning before this comparison is informative.

Enforcing aggregate equalities is a separate model version, not a cosmetic smoothing change.
If fixed originals contradict each other, report the residual. The optional shape layer
uses soft penalties and permits original movement only through an explicit configuration option.
Arbitrage on pending targets does not reconcile already resolved prices.

<a id="shape-investigation"></a>

## 9. Shape investigation: evidence and conclusion

**Primary research.** Callegaro et al. (2022), section 5.2 and Appendix A, smooth the
adjustment to preserve seasonality and match delivery-period averages. This supports
investigating interval-based fitting rather than locating an entire quarter at its midpoint.
[Full article](https://onlinelibrary.wiley.com/doi/full/10.1002/asmb.2645).

Fleten and Lemming (2003) combine market observations, seasonal shape and a smoothness
objective with price constraints. Their construction is more than visual smoothing.
[Original publication](https://www.sciencedirect.com/science/article/pii/S0140988303000392).

**Implemented optional application:** the shape layer regularizes monthly adjustments around
EEX and adds soft Q/Cal hours-weighted coherence penalties; see [its actual scope](#optional-shape-layer). Using EEX as the shape reference is our adaptation, not
proof from these papers that it improves this input. Do not require flat, monotonic or
universally positive prices.

**Executed sensitivity experiment.** The same two synthetic anchors were run in additive
mode, without history, cross, correlation or arbitrage, across all 27 combinations of:

- `tau_log`: 0.25, 0.5, 1.
- `shrink_k`: 0.5, 1, 2.
- `other_kind_weight`: 0, 0.2, 0.6.

Own M+1=110 and Q+2=120 were preserved. A strict interior trough means
`February < min(January, March)`. Being below the neighbors' mean alone is insufficient:
that can occur along a curved monotonic sequence.

| Finding | Interpretation |
|---|---|
| All 18 combinations with other-kind weight 0.2/0.6 have a February interior minimum | The effect persists across this grid, beyond the default parameters. |
| None of the 9 combinations with other-kind weight 0 has that minimum | Removing quarterly influence removes this trough, but also discards that information. |
| The monthly average exceeds own Q+2 by 6.979617–35.411089 | These parameters do not enforce quarterly equality. These are not errors against known monthly truth. |

At tau=0.5 and shrink=1, changing other-kind weight from 0.6 to 0 moves January–March from
**132.239522, 128.569541, 130.903094** to **151.054476, 150.681660, 150.474199**.
The latter has no interior trough but its average, **150.738738**, moves farther from own
Q+2=120. A more regular-looking shape alone does not identify the better predictor.

There is also an algebraic explanation in this scenario. Let a and b be the nonnegative month
and quarter weights, with a+b>0, k=shrink_k>0 and no history/cross:

```text
basis = (10*a - 30*b)/(a+b+k)
basis + 30 = (40*a + 30*k)/(a+b+k) > 0
```

With monthly EEX=150, each estimate exceeds 120. Even a=0 cannot reach 120 while k>0 and
local evidence exists. Weight tuning cannot impose an equality absent from the estimator.
This argument applies to these anchors and assumptions, not every possible market input.

**Controls to compare before selecting a different refill:** errors on hidden gaps, delivery
spreads, abrupt basis changes, hours-weighted aggregation, sensitivity to one anchor, and
fixed-delivery stability across reference dates. Distinguish original from estimated changes.
Thresholds need calibration by curve/horizon; own evidence can justify a jump. Only part of
this monitoring currently exists in consistency output.

For preserved historical VWAPs, aggregation differences do not establish an executable
arbitrage: trades can come from different times or samples. EEX publishes settlements among
its end-of-day data. [EEX End-of-Day](https://www.eex.com/en/market-data/eex-group-datasource/end-of-day-prices).
Whether exact equalities are needed depends on the purpose: coherent valuation or completing
observations while retaining their differences. It is a use-case decision.

Local artifacts are `output/anchor_influence_test/run_shape_sensitivity.py`,
`shape_sensitivity.csv` and `shape_sensitivity.json` in that same directory. Output is
Git-ignored and these artifacts are not included in the published repository. This study
measures sensitivity and structure, **not real predictive accuracy or optimal parameters**.
Production behavior was not changed.

<a id="rollover-audit"></a>

## 10. Fixed-contract rollover audit

A second synthetic audit runs the actual engine on September 30 and October 1, 2026,
following **the same absolute delivery periods**. There are no own observations, so local
has no anchors; history, correlation, cross and output arbitrage are off. Nine EEX
publications end on September 30, with no new October 1 publication. The accepted snapshot
is therefore identical on both dates. Price smoothing uses five observations, EWMA
half-life 2, nine simple spread observations and `anchor_months=2`.

| Fixed delivery period | September 30 estimate | October 1 estimate | Change |
|---|---|---|---:|
| November 2026 | M+2, monthly cascade: 114.000000 | M+1, direct EWMA: 116.659473 | +2.659473 |
| January–March 2027 | Q+2, direct EWMA: 156.659473 | Q+1, direct EWMA: 156.659473 | 0 |

October's prices are constantly 100. The nine same-publication November-minus-October
spreads are 10 through 18, so the September estimate is `100 + mean(10,...,18) = 114`.
After rollover, November becomes an anchor month: its last five prices are 114, 115, 116,
117 and 118. Normalized EWMA weights, oldest first, are approximately 0.088947, 0.125790,
0.177894, 0.251580 and 0.355788, producing **116.659473**. November's raw settlement remains
118 and `eex_asof` remains September 30 throughout.

This change follows the implemented rules: M0 and M1 are counted from the **reference
month**, so November switches from a cascade to direct averaging. It is not a new price
observation or the wrong delivery contract. Moving the last anchor can also affect more
distant months that stay in the cascade. The fixed January–March quarter has no monthly
cascade: the same direct EWMA of 154 through 158 produces 156.659473 on both dates.

The benefit of this design is explicit, auditable level and spread smoothing with complete
historical windows. Its limitation is that these two calculations need not meet continuously
at calendar rollover. Compare `delivery_start` and `delivery_end`: the label M+1 itself
changes delivery month, and Q+1 changes from October–December to January–March in this test.

Local weights also depend on time to delivery, and history pools observations by kind,
group and overall curve rather than maintaining only one fixed contract's history. These
are separate considerations for future rollover studies; neither explains this isolated
no-own, history-off result. Investigating fixed-contract continuity is a proposed next
test, **not an implemented fix or a reason to force a flat curve**.

The local script is `output/rollover_audit/run_audit.py`; run it from the repository root
with `.venv/Scripts/python.exe -B output/rollover_audit/run_audit.py`. Its `summary.json` and
`README.md` record the calculation and settings. These output artifacts are Git-ignored and
not distributed in the repository. All eight engine rows have `source=eex+smooth`, manual
calculations match, and no engine errors occurred. This documentation records behavior;
production configuration and code were unchanged, and the audit demonstrates no accuracy
or performance improvement.

<a id="optional-shape-layer"></a>

## 11. Implemented optional shape layer and how to validate it

The layer is now implemented and **off by default**. It runs after refill, jointly balancing
small changes, second differences of the monthly additive adjustment `price-eex_settle`,
and hours-weighted Quarter/Year aggregation residuals. It uses current accepted raw EEX,
not the fallback's EWMA template. Monthly smoothness needs three consecutive months with a
shared `eex_asof`; aggregate terms need all three/twelve months but do not require EEX.
No missing prices are filled and no Day/Week/Season/BOM/BOW prices are adjusted.

Modes are `off`, `audit` (proposals only), and `adjust` (apply a validated bounded solution).
Original curve prices stay fixed by default. The explicit `adjust_originals=true` option
permits them to move with a larger fidelity penalty; raw input columns always remain intact.
Changed originals are labelled `estimated`/`own+shape`/`shape_adjusted_original`, not passed
off as observations. Adjusted estimates retain their pre-shape provenance and gain `+shape`.

The implemented controls and initial values are `shape.mode="off"`,
`shape.adjust_originals=false`, `shape.smoothness_weight=1.0`,
`shape.coherence_weight=10.0`, `shape.coherence_tolerance=0.01`, `shape.max_abs_adjustment=10.0` and
`shape.original_weight=10.0`. These are starter values, not a calibrated optimum.
[SHAPE.md](SHAPE.md) explains the exact objective, limits, CLI overrides and examples.
A NumPy bounded convex solver validates KKT conditions; failed solutions preserve pre-shape
prices. Aggregate agreement is soft, so conflicting originals or tight bounds can leave a
residual even in a successful solve. Existing heuristic confidence is not used as a variance.

**Aggregation and shape are different.** Subtracting 10.637302 from each month in the earlier
example makes their hours-weighted average 120 but preserves all monthly spreads, including
the February trough. It also exceeds the initial movement bound of 10. This arithmetic is
not an expected output of the new solver. Smoothness and coherence must be assessed jointly;
aliases and multiple estimates from shared anchors must not count as independent evidence.

The same-date solve needs no extra history; the initial refill's memory and EEX-window
requirements remain. Historical data are needed to choose penalties and limits: test missing
blocks, later dates, seasons, horizons and rollovers using the same evaluation universe.
A number of years alone does not establish sufficient overlap or coverage.

`pipeline_configured` now evaluates shape after hiding the observed period and all its aliases;
the hidden truth cannot act as an original shape constraint. History and cross still learn
from actual originals only. The CLI keeps its six search dimensions and fixed shape settings;
the [experiment notebook](MLFLOW.md) can explicitly include shape settings in its grid.
Compare shape settings on matched observations, including errors, large errors, coverage, aggregate
residuals, modification sizes and original movements. Block masking and repeated-origin
validation remain proposed protocols, not new features of this layer.

The research motivation for smoothing a correction to preserve seasonality is section 5.2,
Remark 10 of [Callegaro et al.](https://onlinelibrary.wiley.com/doi/full/10.1002/asmb.2645).
Our EEX-reference adaptation is not proof of predictive improvement. It does not impose a
flat, monotonic or positive curve. A jointly smoothed EEX template and temporal regularization
are not implemented. Cross-maturity agreement cannot by itself cure the same-contract
[rollover jump](#rollover-audit); that needs a separate temporal test and must not be hidden
by a visually smoother curve.

**Coherence tolerance is a diagnostic, not a hard constraint.** `shape.coherence_tolerance=0.01`
compares the absolute monthly-average-minus-parent residual with 0.01 in the curve's price
unit. Increasing it relaxes the reported test; decreasing it tightens it. It changes neither
the optimizer nor the accepted price. Soft penalties, protected originals and movement
bounds can leave a result outside tolerance. Audit flags the proposal; adjust flags the
published result. The trace reports each aggregate test and the overall result, or null
when there is no applicable aggregate. The same numeric setting is interpreted in each
curve's own unit; it is not a percentage or a currency conversion.

See the [power-specific scope and local EEX sample](SHAPE.md#why-this-is-power-specific-and-what-the-eex-sample-showed): aggregate agreement does not require equal month prices and is not a universal rule for every asset.

## 12. Day-ahead influence: current behavior and validation limits

An isolated synthetic audit uses September 30, 2026, an own D+1 price of 100 versus EEX 80,
volume 100, additive mode, no history and the existing distance/type/shrink settings. With
target EEX 120, this +20 anchor produces **M+1=121.069779, M+4=120.028826 and
Q+2=120.017899**. Influence becomes tiny but remains nonzero. Available LOCAL adjustment
therefore prevents the smoothed-EEX fallback: small price influence can still change the
calculation route. This is existing behavior, not a demonstrated accuracy improvement.

Current correlation learns own-minus-EEX **basis surprises between contract groups**;
it is neither an EEX-only model nor a separate learned M+1-versus-M+4 relationship.
An EEX-only check used 42 publications, August 10–October 6, 2026: April 2027 daily price
changes correlated about 0.81–0.85 with fixed November–February contracts over 41 pairs.
Without own historical truth, this cannot rank refill methods or validate a single winning
anchor. Family eligibility rules and an EEX-derived prior with own-price validation remain
proposals. Local evidence is in Git-ignored `output/local_anchor_review/`; no production
logic was changed for this audit.
