"""Parse reference dates without applying day-first rules to ISO dates."""

from __future__ import annotations

import pandas as pd


def parse_reference_dates(values: pd.Series) -> pd.Series:
    """Accept ISO YYYY-MM-DD, day-first text and spreadsheet date objects.

    ISO dates use an explicit parser: applying dayfirst=True to mixed ISO
    text can silently exchange the month and day on some pandas versions.
    Invalid dates remain NaT so each caller can report its input context.
    """
    text = values.astype(str).str.strip()
    iso = text.str.match(r"^\d{4}-\d{2}-\d{2}(?:$|[ T])")
    parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    if iso.any():
        parsed.loc[iso] = pd.to_datetime(text.loc[iso], format="ISO8601", errors="coerce")
    if (~iso).any():
        parsed.loc[~iso] = pd.to_datetime(values.loc[~iso], dayfirst=True,
                                         format="mixed", errors="coerce")
    return parsed
