"""Curve filling engine shared by `daily` and `refill`: a single day is a
one-day refill with previous days replayed as warmup.

Each series is one mapped (product, region, unit) curve. All series are
processed together, day by day, to share information (enhancement 2).

Cascade per (day, curve identity, target tenor); see ALGORITMO.md for details.
Each layer is enabled or disabled in config.toml [layers]:
  own        Original VWAP; min_volume controls anchor eligibility.
  eex+local  EEX adjusted with today's anchors                    [layers] local
  eex+cross  EEX adjusted with history and other products' shocks [layers] cross
  eex+hist   EEX adjusted with history (no anchors today)         [layers] hist
  eex        Unadjusted EEX
  arbitrage  Without EEX: use contracts already filled            [layers] arbitrage
  missing    No estimate is available.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from itertools import combinations

import pandas as pd

from vwaps.basis import (
    Anchor, BasisHistory, KindFactor, apply_basis, daily_basis, distance_kind_factor,
    local_basis, log_ttm,
)
from vwaps.comove import EWCov
from vwaps.config import Config
from vwaps.consistency import check_day
from vwaps.hours import hours_fn
from vwaps.identity import CurveKey, curve_keys
from vwaps.io_eex import EexBook
from vwaps.log import get_logger
from vwaps.mapping import ProductMap
from vwaps.pricer import Pricer
from vwaps.tenors import Key, Period, resolve_tenor

MODES = ("additive", "ratio")
GROUPS = ("short", "month", "quarter", "long")


@dataclass
class OwnQuote:
    period: Period
    tenors: list[str]
    vwap: float
    volume: float


class HistSkill:
    """For layers.hist = "auto", compare historical adjustments with raw EEX
    on days WITH anchors, using each anchor as the observed price.
    Track exponentially weighted mean errors by group (Days, Months...)."""

    def __init__(self, halflife_days: float):
        self.lam = 0.5 ** (1.0 / max(halflife_days, 1e-9))
        self.stats: dict[str, list[float]] = {}  # group -> [err_hist, err_eex, n]

    def update(self, errors: dict[str, list[tuple[float, float]]]) -> None:
        for g, pairs in errors.items():
            eh = sum(abs(a) for a, _ in pairs) / len(pairs)
            ee = sum(abs(b) for _, b in pairs) / len(pairs)
            s = self.stats.setdefault(g, [0.0, 0.0, 0.0])
            s[0] = self.lam * s[0] + eh
            s[1] = self.lam * s[1] + ee
            s[2] = self.lam * s[2] + 1.0

    def use_hist(self, group: str, min_obs: float) -> bool:
        s = self.stats.get(group)
        if s is None or s[2] < min_obs:
            return True  # Not enough evidence yet: use history.
        return s[0] <= s[1]


@dataclass
class Series:
    m: ProductMap
    book: EexBook | None
    own_by_day: dict
    hfn: object
    hist: dict[str, BasisHistory]
    skill: dict[str, HistSkill]
    gcov: dict[tuple[str, str, str], EWCov] = field(default_factory=dict)  # (mode, group, group)

    @property
    def key(self) -> CurveKey:
        return self.m.key

    @property
    def name(self) -> str:
        return self.m.label

    @property
    def output(self) -> bool:
        return self.m.use == "fill"


@dataclass
class DayPrep:
    asof: date | None
    eex: Pricer
    own: dict[Key, OwnQuote]
    anchors: list[Anchor]
    surprises: dict[str, float]  # today's basis - historical basis, by group and "all"
    rejected: set = field(default_factory=set)
    mode_anchors: dict[str, list[Anchor]] = field(default_factory=dict)
    evaluation_anchors: list[Anchor] = field(default_factory=list)
    mode_surprises: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class RunResult:
    filled: pd.DataFrame
    consistency: pd.DataFrame
    loo: pd.DataFrame = field(default_factory=pd.DataFrame)
    errors: list[dict] = field(default_factory=list)


class CurveFiller:
    def __init__(self, cfg: Config, vwaps: pd.DataFrame, maps: list[ProductMap],
                 books: dict[CurveKey | str, EexBook | None]):
        self.cfg = cfg
        self.vwaps = vwaps
        self.maps = [m for m in maps if m.active]
        self.books = books
        self._curve_labels = {m.key: m.label for m in self.maps}
        self.cross: dict[tuple, EWCov] = {}  # (mode, curve, other curve, group) -> co-movement

    # ------------------------------------------------------------------ run
    def _build_series(self) -> list[Series]:
        cfg = self.cfg
        by_curve = {key: frame for key, frame in self.vwaps.groupby(curve_keys(self.vwaps), sort=False)}
        out = []
        for m in self.maps:
            g = by_curve.get(m.key)
            legacy_book = self.books.get(m.product) if not m.region and not m.unit else None
            out.append(Series(
                m, self.books.get(m.key, legacy_book),
                {d: x for d, x in g.groupby("date")} if g is not None else {},
                hours_fn(m.hours, m.timezone),
                {md: BasisHistory(md, cfg.ewma_halflife_days) for md in MODES},
                {md: HistSkill(cfg.ewma_halflife_days) for md in MODES},
            ))
        return out

    def run(self, start: date, end: date, loo: bool = False,
            *, output_keys: set[tuple[date, CurveKey]] | None = None) -> RunResult:
        cfg = self.cfg
        log = get_logger()
        series = self._build_series()
        self.cross = {}
        if start > end:
            raise ValueError("The start date cannot be later than the end date")
        warm = start - timedelta(days=cfg.warmup_days) if cfg.warmup_days else date.min
        log.info("Engine %s -> %s | mode=%s | cross=%s | warmup=%s",
                 start, end, cfg.basis_mode, cfg.layer_cross,
                 f"{cfg.warmup_days} days (limited history)" if cfg.warmup_days else "all original history")
        if cfg.warmup_days:
            log.warning("Limited warmup: daily and a longer refill may use different history")
        days: set[date] = set()
        for s in series:
            days |= {d for d in s.own_by_day if warm <= d <= end}
            if s.book is not None:
                days |= {d for d in s.book.trade_dates if warm <= d <= end}
        d = start
        while d <= end:  # Include every weekday in the range, even without data.
            if d.weekday() < 5:
                days.add(d)
            d += timedelta(days=1)
        if output_keys is not None:
            days.update(day for day, _ in output_keys if start <= day <= end)

        no_eex: dict[str, list[date]] = {}
        filled, cons, loo_rows, errors = [], [], [], []
        for day in sorted(days):
            preps = {}
            for s in series:  # A curve failure does not stop the other curves.
                try:
                    preps[s.key] = self._prep(s, day)
                except Exception:
                    errors.append({"reference_date": day, "product": s.m.product,
                                   "region": s.m.region, "unit": s.m.unit, "phase": "prepare"})
                    log.exception("%s %s: error preparing the day; skipping this curve", day, s.name)
            for s in series:
                if not s.output or day < start or s.key not in preps:
                    continue
                if output_keys is not None and (day, s.key) not in output_keys:
                    continue
                try:
                    rows = self._fill(s, day, preps)
                    cons += check_day(rows, s.hfn)
                    if loo:
                        loo_rows += self._loo(s, day, preps)
                except Exception:
                    errors.append({"reference_date": day, "product": s.m.product,
                                   "region": s.m.region, "unit": s.m.unit, "phase": "fill"})
                    log.exception("%s %s: error filling the curve; skipping this curve", day, s.name)
                    continue
                filled += rows
                log.info("%s %s | anchors=%d | EEX=%s | methods=%s",
                         day, s.name, len(preps[s.key].anchors), preps[s.key].asof,
                         dict(Counter(r["estimation_method"] for r in rows)))
                asof = preps[s.key].asof
                if s.book is not None and asof is None:
                    no_eex.setdefault(s.name, []).append(day)
                elif asof is not None and asof != day:
                    age = (day - asof).days
                    lvl = log.error if age >= cfg.warn_stale_days else log.warning
                    lvl("%s %s: EEX for %s is unavailable; using EEX from %s (%d days earlier)",
                        day, s.name, day, asof, age)
            self._update(series, day, preps)
        for name, ds in no_eex.items():
            log.warning("%s: no EEX settlement available yet from %s to %s (%d days): "
                        "using only VWAPs + arbitrage", name, ds[0], ds[-1], len(ds))
        return RunResult(pd.DataFrame(filled), pd.DataFrame(cons), pd.DataFrame(loo_rows), errors)

    # ------------------------------------------------------- prepare the day
    def _own_quotes(self, day: date, g: pd.DataFrame | None, hfn) -> dict[Key, OwnQuote]:
        out: dict[Key, OwnQuote] = {}
        if g is None:
            return out
        for tenor, vwap, vol in g[["tenor", "vwap", "volume"]].itertuples(index=False):
            per = resolve_tenor(tenor, day, self.cfg.day_convention, self.cfg.weekend_offset)
            if per is None or not math.isfinite(float(vwap)):
                continue
            # Peak BOW/BOM may share dates with WE/Day but have no delivery
            # hours. They are not aliases of the quoted contract.
            if hfn(per.start, per.end, kind=per.kind) <= 0:
                continue
            vol = float(vol) if vol == vol else float("nan")
            q = out.get(per.key)
            if q is None:
                out[per.key] = OwnQuote(per, [tenor], float(vwap), vol)
            else:  # Repeated delivery period: aggregate using volume weights.
                w1 = q.volume if q.volume == q.volume and q.volume > 0 else 1.0
                w2 = vol if vol == vol and vol > 0 else 1.0
                q.vwap = (q.vwap * w1 + float(vwap) * w2) / (w1 + w2)
                q.volume = (q.volume if q.volume == q.volume else 0) + (vol if vol == vol else 0)
                q.tenors.append(tenor)
        return out

    def _prep(self, s: Series, day: date) -> DayPrep:
        cfg = self.cfg
        for hist in s.hist.values():
            hist.expire(day, cfg.hist_max_age_days)
        quotes, asof = s.book.quotes(day, cfg.max_stale_days) if s.book is not None else ({}, None)
        eex = Pricer(quotes, s.hfn)
        own = self._own_quotes(day, s.own_by_day.get(day), s.hfn)
        candidates, bad, rejected = [], [], set()
        for q in own.values():
            r = eex.price(q.period.start, q.period.end, kind=q.period.kind)
            if r is None or not math.isfinite(r[0]):
                continue
            deviation = abs(q.vwap - r[0]) / max(abs(r[0]), cfg.ratio_eex_floor)
            if (math.isfinite(q.volume) and q.volume < cfg.min_volume) or (
                    cfg.max_anchor_dev > 0 and deviation > cfg.max_anchor_dev):
                bad.append(f"{','.join(q.tenors)} {q.vwap:g} vs EEX {r[0]:g}")
                rejected.add(q.period.key)
                continue
            candidates.append(Anchor(",".join(q.tenors), q.period, q.vwap, r[0], q.volume,
                                  log_ttm(q.period, day)))
        by_mode = {md: [a for a in candidates if self._usable_anchor(a, md)] for md in MODES}
        # Auto can use every additive anchor; each target later selects its mode.
        summary_mode = "additive" if cfg.basis_mode == "auto" else cfg.basis_mode
        anchors = by_mode[summary_mode]
        rejected.update(a.period.key for a in candidates if not self._usable_anchor(a, summary_mode))
        if bad:
            get_logger().warning("%s %s: anchors excluded by volume/deviation; originals preserved: %s",
                                 day, s.name, "; ".join(bad))
        unstable = len(candidates) - len(anchors)
        if unstable:
            get_logger().warning("%s %s: %d anchors excluded by unstable ratios; originals preserved",
                                 day, s.name, unstable)
        mode_surprises: dict[str, dict[str, float]] = {md: {} for md in MODES}
        if asof == day:
            for md in MODES:
                h = s.hist[md].values
                for k, v in daily_basis(by_mode[md], md).items():
                    if (k in GROUPS or k == "all") and k in h:
                        mode_surprises[md][k] = v - h[k]
        return DayPrep(asof, eex, own, anchors, mode_surprises[summary_mode],
                       rejected, by_mode, candidates, mode_surprises)

    def _usable_anchor(self, a: Anchor, mode: str) -> bool:
        if not (math.isfinite(a.own) and math.isfinite(a.eex)):
            return False
        if mode == "additive":
            return True
        if abs(a.eex) < self.cfg.ratio_eex_floor:
            return False
        factor = a.own / a.eex
        return factor > 0 and abs(factor - 1) <= self.cfg.max_ratio_deviation

    # -------------------------------------------------- enhancements 1 and 2
    def _kind_factor(self, s: Series, use_corr: bool, mode: str) -> KindFactor:
        cfg = self.cfg
        base = distance_kind_factor(cfg.other_kind_weight)
        if not use_corr:
            return base

        def f(anchor: Period, target: Period) -> float:
            if anchor.kind == target.kind or anchor.group == target.group:
                return base(anchor, target)
            c = s.gcov.get((mode, *sorted((anchor.group, target.group))))
            if c is None or c.corr is None:
                return cfg.other_kind_weight
            a = c.n / (c.n + cfg.corr_prior_obs)
            return a * max(c.corr, 0.0) + (1 - a) * cfg.other_kind_weight
        return f

    def _cross_adj(self, s: Series, per: Period, preps: dict, mode: str) -> tuple[float, list[str]] | None:
        """Today's correlated surprises in the selected mode, scaled by beta."""
        cfg = self.cfg
        num = den = 0.0
        used = []
        for key, p in preps.items():
            surprises = p.mode_surprises.get(mode, {})
            if key == s.key or not surprises:
                continue
            k = per.group if per.group in surprises else "all"
            if k not in surprises:
                continue
            c = self.cross.get((mode, s.key, key, k))
            if c is None or c.n < cfg.cross_min_obs or c.corr is None or c.corr < cfg.cross_min_corr or c.beta is None:
                continue
            w = c.corr ** 2
            num += w * c.beta * surprises[k]
            den += w
            used.append(f"{self._curve_labels[key]}({c.corr:.2f})")
        return (num / den, used) if den > 0 else None

    def _hist_for(self, s: Series, per: Period, mode: str) -> float | None:
        cfg = self.cfg
        if cfg.layer_hist == "off":
            return None
        if cfg.layer_hist == "auto" and not s.skill[mode].use_hist(per.group, cfg.hist_auto_min_obs):
            return None
        return s.hist[mode].get(per)

    def _select_mode(self, s: Series, per: Period, eex: float | None, p: DayPrep) -> tuple[str, str]:
        """Select a target's mode from visible anchors and usable past history."""
        cfg = self.cfg
        if cfg.basis_mode != "auto":
            return cfg.basis_mode, ""
        if eex is not None and abs(eex) < cfg.ratio_eex_floor:
            return "additive", "auto_additive_low_eex"
        ratio_anchors = p.mode_anchors.get("ratio", [])
        additive_anchors = p.mode_anchors.get("additive", [])
        if not ratio_anchors and additive_anchors:
            return "additive", "auto_additive_no_ratio_anchors"
        if not ratio_anchors and not additive_anchors:
            if self._hist_for(s, per, "ratio") is None and self._hist_for(s, per, "additive") is not None:
                return "additive", "auto_additive_history_only"
        return "ratio", ""

    # ------------------------------------------------------------ fill
    def _fill(self, s: Series, day: date, preps: dict, labels: list[str] | None = None) -> list[dict]:
        cfg = self.cfg
        p = preps[s.key]
        kind_factors = {md: self._kind_factor(s, cfg.layer_correlation, md) for md in MODES}
        rows, pending = [], []
        for label in dict.fromkeys(labels if labels is not None else cfg.tenors):
            per = resolve_tenor(label, day, cfg.day_convention, cfg.weekend_offset)
            if per is None:
                continue
            delivery_hours = s.hfn(per.start, per.end, kind=per.kind)
            q = p.own.get(per.key) if delivery_hours > 0 else None
            r = p.eex.price(per.start, per.end, kind=per.kind)
            mode, auto_reason = self._select_mode(s, per, r[0] if r is not None else None, p)
            row = {
                "reference_date": day, "product": s.m.product,
                "region": s.m.region, "unit": s.m.unit, "area": s.m.area,
                "profile": s.m.profile, "tenor": label, "kind": per.kind, "period": per.name,
                "delivery_start": per.start, "delivery_end": per.end,
                "hours": delivery_hours,
                "price": math.nan, "source": "missing", "confidence": 0.0,
                "data_origin": "missing", "estimation_method": "unavailable", "basis_mode": mode,
                "configured_basis_mode": cfg.basis_mode,
                "own_vwap": q.vwap if q else math.nan, "own_volume": q.volume if q else math.nan,
                "eex_settle": r[0] if r else math.nan, "eex_method": r[1] if r else "",
                "eex_asof": p.asof, "basis": math.nan, "basis_local": math.nan,
                "basis_hist": math.nan, "cross_adj": math.nan, "local_weight": math.nan,
                "anchors": "", "cross_from": "",
                "flag": "anchor_excluded" if per.key in p.rejected else "",
            }
            if delivery_hours <= 0:
                row["flag"] = ";".join(filter(None, [row["flag"], "zero_delivery_hours"]))
                rows.append(row)
                continue
            if q is not None:
                row.update(price=q.vwap, source="own", confidence=1.0,
                           data_origin="original", estimation_method="none")
            elif r is not None:
                if auto_reason:
                    row["flag"] = ";".join(filter(None, [row["flag"], auto_reason]))
                if cfg.layer_local:
                    b_loc, W, used = local_basis(per, day, p.mode_anchors[mode], mode,
                                               cfg.tau_log, kind_factors[mode])
                else:
                    b_loc, W, used = None, 0.0, []
                b_hist = self._hist_for(s, per, mode)
                cross = None
                if cfg.layer_cross and s.hist[mode].get(per) is not None:
                    cross = self._cross_adj(s, per, preps, mode)
                prior = (b_hist or 0.0) + cross[0] if cross else b_hist
                b, w, src = _blend(b_loc, W, prior, cfg.shrink_k)
                if mode == "ratio" and abs(b) > cfg.max_ratio_deviation:
                    b = max(-cfg.max_ratio_deviation, min(cfg.max_ratio_deviation, b))
                    row["flag"] = ";".join(filter(None, [row["flag"], "ratio_adjustment_limited"]))
                if cross and src == "eex+hist":
                    src = "eex+cross"
                conf = 0.5 + 0.4 * w if src != "eex" else 0.4
                if r[1] != "exact":
                    conf *= 0.85
                if p.asof != day:
                    conf *= 0.9
                row.update(
                    price=apply_basis(r[0], b, mode), source=src, confidence=round(conf, 3),
                    basis=b, basis_local=b_loc if b_loc is not None else math.nan,
                    basis_hist=b_hist if b_hist is not None else math.nan,
                    cross_adj=cross[0] if cross else math.nan, local_weight=w,
                    anchors=",".join(used), cross_from=",".join(cross[1]) if cross else "",
                    data_origin="estimated",
                    estimation_method=_estimation_method(mode, b_loc, b_hist, cross),
                )
            else:
                pending.append(row)
            rows.append(row)

        if pending and cfg.layer_arbitrage:  # Filled contracts plus VWAPs outside the target list.
            known = {(x["delivery_start"], x["delivery_end"]): x["price"]
                     for x in rows if x["source"] != "missing" and x["hours"] > 0}
            for k, q in p.own.items():
                if k not in p.rejected:
                    known.setdefault(k, q.vwap)
            arb = Pricer(known, s.hfn)
            for row in pending:
                r = arb.price(row["delivery_start"], row["delivery_end"], kind=row["kind"])
                if r is not None:
                    row.update(price=r[0], source="arbitrage", confidence=0.4, eex_method=r[1],
                               data_origin="estimated", estimation_method=f"contract_{r[1]}")
        for row in rows:
            if row["source"] != "missing" and not math.isfinite(row["price"]):
                raise ValueError(f"{s.name} {day} {row['tenor']}: computed price must be finite")
        return rows

    # ------------------------------------------------ update history
    def _update(self, series: list[Series], day: date, preps: dict) -> None:
        """Use only real VWAPs and same-day EEX: stale EEX would mix market
        movements into the estimated basis."""
        cfg = self.cfg
        series = [s for s in series if s.key in preps and preps[s.key].asof == day]
        for s in series:
            p = preps[s.key]
            for mode in MODES:
                # Each mode has its own historical skill and covariance units.
                errs: dict[str, list[tuple[float, float]]] = {}
                for a in p.mode_anchors[mode]:
                    bh = s.hist[mode].get(a.period)
                    if bh is not None:
                        errs.setdefault(a.period.group, []).append(
                            (apply_basis(a.eex, bh, mode) - a.own, a.eex - a.own))
                s.skill[mode].update(errs)
                sur = p.mode_surprises[mode]
                for g1, g2 in combinations(GROUPS, 2):
                    if g1 in sur and g2 in sur:
                        s.gcov.setdefault((mode, *sorted((g1, g2))), EWCov(cfg.corr_halflife_days)).update(
                            sur[g1], sur[g2], day)
                for other in series:
                    if other is s:
                        continue
                    so = preps[other.key].mode_surprises[mode]
                    for k in set(sur) & set(so):
                        self.cross.setdefault((mode, s.key, other.key, k), EWCov(cfg.cross_halflife_days)).update(
                            so[k], sur[k], day)  # x = the other curve, y = this curve
        for s in series:
            for md in MODES:
                s.hist[md].update(preps[s.key].mode_anchors.get(md, []), day)

    # ------------------------------------------------------------ backtest
    def _loo(self, s: Series, day: date, preps: dict) -> list[dict]:
        """Hide each anchor and predict it with each method:
          eex, local_*, hist_*, blend_*   (in ratio and additive modes)
          local_corr, blend_corr          (enhancement 1, both modes in auto)
          hist_cross                      (enhancement 2: no own anchors today)"""
        cfg = self.cfg
        p = preps[s.key]
        kf_dist = distance_kind_factor(cfg.other_kind_weight)
        kf_corr = {md: self._kind_factor(s, True, md) for md in MODES}
        out = []
        for a in p.evaluation_anchors:
            others = [x for x in p.anchors if x.period.key != a.period.key]
            others_by_mode = {md: [x for x in p.mode_anchors[md] if x.period.key != a.period.key]
                              for md in MODES}
            base = {"reference_date": day, "product": s.m.product,
                    "region": s.m.region, "unit": s.m.unit, "tenor": a.tenor,
                    "kind": a.period.kind, "group": a.period.group, "own": a.own,
                    "volume": a.volume, "n_other_anchors": len(others),
                    "configured_basis_mode": cfg.basis_mode}
            preds = {"eex": a.eex}
            applied_modes = {"eex": ""}
            for m in MODES:
                others_md = others_by_mode[m]
                b_loc, W, _ = local_basis(a.period, day, others_md, m, cfg.tau_log, kf_dist)
                b_hist = s.hist[m].get(a.period)
                if b_loc is not None:
                    preds[f"local_{m}"] = apply_basis(a.eex, b_loc, m)
                if b_hist is not None:
                    preds[f"hist_{m}"] = apply_basis(a.eex, b_hist, m)
                preds[f"blend_{m}"] = apply_basis(a.eex, _blend(b_loc, W, b_hist, cfg.shrink_k)[0], m)
                if cfg.basis_mode in ("auto", m):
                    b_loc, W, _ = local_basis(a.period, day, others_md, m, cfg.tau_log, kf_corr[m])
                    if b_loc is not None:
                        preds[f"local_corr_{m}"] = apply_basis(a.eex, b_loc, m)
                    preds[f"blend_corr_{m}"] = apply_basis(a.eex, _blend(b_loc, W, b_hist, cfg.shrink_k)[0], m)
                    if b_hist is not None:
                        cross = self._cross_adj(s, a.period, preps, m)
                        preds[f"hist_cross_{m}"] = apply_basis(a.eex, b_hist + (cross[0] if cross else 0.0), m)
                applied_modes.update({method: m for method in preds if method.endswith(f"_{m}")})
            # Hide the observation from every mode before auto selects a mode.
            hidden = replace(p, own={k: q for k, q in p.own.items() if k != a.period.key},
                             anchors=others, mode_anchors=others_by_mode)
            label = p.own[a.period.key].tenors[0]
            deployed = self._fill(s, day, {**preps, s.key: hidden}, labels=[label])
            if deployed and math.isfinite(deployed[0]["price"]):
                preds["pipeline_configured"] = deployed[0]["price"]
                applied_modes["pipeline_configured"] = deployed[0]["basis_mode"]
            for method, pr in preds.items():
                out.append({**base, "method": method, "basis_mode": applied_modes[method],
                            "pred": pr, "error": pr - a.own})
        return out


def _blend(b_loc: float | None, W: float, b_hist: float | None, k: float) -> tuple[float, float, str]:
    """Blend local and historical basis: w = W / (W + k). Without history,
    shrink toward 0 (unadjusted EEX)."""
    if b_loc is None or W <= 0:
        if b_hist is not None:
            return b_hist, 0.0, "eex+hist"
        return 0.0, 0.0, "eex"
    w = W / (W + k)
    prior = b_hist if b_hist is not None else 0.0
    b = w * b_loc + (1 - w) * prior
    if w >= 0.5 or b_hist is None:
        return b, w, "eex+local"
    return b, w, "eex+hist"


def _estimation_method(mode: str, local: float | None, hist: float | None, cross) -> str:
    parts = []
    if local is not None:
        parts.append("local")
    if hist is not None:
        parts.append("history")
    if cross is not None:
        parts.append("cross")
    return f"{mode}_" + "_".join(parts) if parts else "eex"
