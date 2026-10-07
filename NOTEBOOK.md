# Inspect saved curves interactively

[Español](NOTEBOOK.es.md) · [Notebook](notebooks/inspect_curves.ipynb) · [Output dictionary](OUTPUT.md)

The notebook reads **one filled output CSV only**, usually `filled_history.csv`. It does not
load original VWAP files, mapping files or raw EEX files, run the filler, adjust prices, or
write data. Interactive Plotly charts and selectors are available in three separate tabs.

## Start on this or another computer

Copy the repository and the output CSV you want to inspect. Python 3.11 or later is required.
From the repository root:

```powershell
uv sync --group notebook
uv run --group notebook jupyter lab notebooks/inspect_curves.ipynb
```

The optional `notebook` group adds JupyterLab, ipywidgets and Plotly; it does not change the
production dependencies. No server is started by importing `vwaps.visualization`.

Without uv, activate a Python environment, then:

```powershell
python -m pip install "numpy>=1.26" "pandas>=2.2" "openpyxl>=3.1" "jupyterlab>=4" "ipywidgets>=8" "plotly>=5"
python -m jupyter lab notebooks/inspect_curves.ipynb
```

Select the Python kernel from that environment and run the cells in order. The interface is
in Spanish; code and docstrings are in English. Neither method requires the original input data.

### Open in Visual Studio Code

Open the **repository root folder**, rather than the notebook file alone. Install Microsoft's
**Python** and **Jupyter** extensions if necessary. In the notebook's top-right corner, choose
**Select Kernel → Select Another Kernel → Python Environments**, then select `.venv`.
Its interpreter is `.venv\Scripts\python.exe` on Windows or `.venv/bin/python` on Linux/macOS.
The terminal interpreter and notebook kernel may differ; check both when imports fail.

If the environment is missing from the list, run from the repository root:

```powershell
uv sync --group notebook
uv run --group notebook python -m ipykernel install --user --name vwaps --display-name "Python (VWAPS .venv)"
```

Run **Developer: Reload Window** from VS Code's command palette, then select
**Python (VWAPS .venv)** from the Jupyter kernel picker. Registration is local to the computer:
repeat it on another computer or after moving the repository. Recreate `.venv` using
`uv sync --group notebook` instead of copying it between computers.

Verify the active interpreter in a notebook cell:

```python
import sys
print(sys.executable)
```

It should point to this repository's `.venv` Python. **`.venv` is a folder containing Python
and its dependencies; `.env` is an environment-variable file that this notebook does not need.**
If a message literally requests `.env`, inspect the extension or setting requesting it;
creating that file does not select a kernel or install packages. These steps follow
[VS Code's kernel-management documentation](https://code.visualstudio.com/docs/datascience/jupyter-kernel-management).

## Select the file

The path cell is set up for the local validation run using
`output/notebook_validation/filled_history.csv`, a **synthetic CSV that is not included in
GitHub**. On another computer, replace `OUTPUT_PATH` with the output CSV you generated or
copied. The cell includes commented examples for both locations.

Edit the first code cell if necessary:

```python
PROJECT_ROOT = None
CONFIG_PATH = None
OUTPUT_PATH = "output/filled_history.csv"
```

The repository root is discovered from the current directory or its ancestors, so both the
root and `notebooks/` work. If Jupyter starts elsewhere, set `PROJECT_ROOT` explicitly.
There are no machine-specific paths in the notebook.

- An explicit `OUTPUT_PATH` wins. It can be a CSV or a directory containing `filled_history.csv`.
  Relative explicit paths are resolved from the repository root.
- Otherwise, the notebook reads `paths.output_dir` from `CONFIG_PATH`, or the root's
  `config.toml`. Paths inside the TOML remain relative to that TOML's directory.
- If no default TOML exists, it tries `output/filled_history.csv`. An explicitly specified
  missing TOML is an error.
- A missing or empty CSV displays guidance without creating selectors. Invalid schemas,
  dates, nonnumeric price text or conflicting aliases produce explicit errors.

After changing a path, rerun the load cell and the following cells. Data is loaded once;
rerun those cells to inspect a newer output. Use a snapshot if another process is writing
the same CSV during inspection.

## The three views

**Una fecha — one reference date.** Select the exact `(product, region, unit)` identity,
contract kind and reference date. Month is selected initially when available; Day and the
other saved kinds are also available. The chart compares final `price` with saved
`eex_settle`. Optional markers show `own_vwap`; an optional line shows `price_before_shape`.
The detail table exposes source, flags, `eex_asof`, EEX age and shape status when available.

Choosing all kinds uses markers only. It never joins monthly prices and quarterly averages
into one mixed line. Delivery intervals use an exclusive end date.

**Medias por rango — date-range averages.** Choose inclusive start/end dates, alignment,
then click **Comparar rango**. Default alignment follows the same absolute delivery period
through label changes. Relative-tenor alignment deliberately combines different deliveries:
M+1 in September and M+1 in October are different contracts. The notebook displays a warning
and reports `n_delivery_periods`.

For each point, both means use **only reference dates where final price and EEX are finite**.
Each paired date has equal weight; no volume or delivery-hour weighting is used here. Missing
prices do not become zeros. Valid zero and negative prices remain in the calculation.
Different points may have different paired dates and sample sizes; this is not a global
common-date intersection across all contracts. A stale EEX quote can therefore appear on more
than one reference date, which is consistent with daily weighting; inspect its publication date.

**Evolución de una entrega — fixed-contract evolution.** Choose an absolute delivery period.
The chart follows it through reference dates even when its relative label changes. It shows
the entire saved history for that contract, independently of the range-average date controls.
Price changes can reflect new data, a different calculation route or shape adjustment; the
plot alone does not diagnose the cause.

## Counts and interpretation

The summary reports unique saved observations, available final prices/EEX values, paired
observations, missing final prices and original/estimated final prices. Adjusted originals
(`own+shape`) form a subgroup of estimates. These are engine-output classifications, not
counts of physical input rows or trades. `own_vwap` may already aggregate equivalent input rows.

The range table includes `n_observations`, `n_price`, `n_eex`, `n_paired`, delivery counts,
paired means and their mean difference. With no paired dates, both means are missing.
Coverage is the fraction of **saved rows** with a finite final price; contracts entirely absent
from the CSV are outside that denominator. It is not a prediction-accuracy measurement.

One observation is retained per reference date, full identity, kind and absolute delivery
period. Equivalent labels are recorded in `tenor_aliases`; they do not increase counts or
weights. Conflicting aliases are rejected rather than averaged. Distinct kinds remain distinct.

For shape `audit`, `price` remains the accepted price without applying the proposal.
`price_before_shape` is the pre-stage value, not the hypothetical audit proposal. The notebook
does not apply shape or reconstruct missing shape metadata. Shape-off outputs work without
any optional shape columns. See [OUTPUT.md](OUTPUT.md) for the field definitions.

## Supported CSV schema

Required columns are `reference_date`, `product`, `region`, `unit`, `tenor`, `kind`,
`delivery_start`, `delivery_end`, `price`, `eex_settle`, and `source`. Use a filled CSV, not
`enriched_history.csv`. Blank region/unit values are literal identities; missing identity
columns are rejected. Regenerate older outputs with the current engine instead of guessing
their regions or currencies.

ISO and day-first reference dates are supported. Shape fields, `own_vwap`, `eex_asof` and
other diagnostic columns are optional. An absent EEX publication date is shown as unknown;
it does not imply a fresh quote. All plotted prices retain the selected curve's own unit.

If only text appears instead of widgets/charts, confirm the notebook dependency group is
installed and select its Python kernel. The repository's helper tests do not require Jupyter.

Execution check: all notebook cells and interactive callbacks ran without errors on synthetic
output containing 168 rows, seven dates and three curve identities, including range means
under both absolute-period and rolling-label alignment.
