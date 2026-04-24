"""
Calibrate LinearUtilityModel parameters from Hytch behavioral features.

Maps the aggregates produced by scripts.extract_behavioral_features into
a PopulationParameters instance so simulations can be seeded with
empirically-grounded betas instead of the library defaults.

Estimator is method-of-moments: we treat the observed overall carpool
rate as a binary-choice probability and back out beta_incentive via the
logit inverse. This is a deliberately simple, scipy-free estimator that
runs on tiny samples and degrades gracefully — once the full Hytch dump
(369K trips) is loaded into the warehouse the same pipeline yields a
much tighter estimate without code changes.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Optional

from ..agents.base import PopulationParameters


# Defaults from CLAUDE.md / the existing PopulationParameters dataclass.
DEFAULT_PARAMS = PopulationParameters()


def calibrate_from_features(
    features: dict[str, Any],
    base: Optional[PopulationParameters] = None,
) -> PopulationParameters:
    """
    Derive PopulationParameters from an extract_features() dict.

    Falls back to the provided base (or library defaults) for any
    coefficient where the sample is too thin to estimate reliably.
    """
    base = base or DEFAULT_PARAMS
    summary = features.get("trip_summary") or {}

    n = _as_float(summary.get("total_trips", 0))
    if n < 5:  # below this, don't bother — the defaults are better
        return base

    carpool_rate = _as_float(summary.get("overall_carpool_rate"))
    mean_incentive_carpool = _as_float(summary.get("mean_incentive_carpool"))
    mean_incentive_solo = _as_float(summary.get("mean_incentive_solo"))

    beta_incentive_mean = _estimate_beta_incentive(
        carpool_rate=carpool_rate,
        inc_carpool=mean_incentive_carpool,
        inc_solo=mean_incentive_solo,
        fallback=base.beta_incentive_mean,
    )

    # Time coefficient: if we have duration data, scale it relative to a
    # 30-minute reference trip. Otherwise keep defaults.
    mean_duration = _as_float(summary.get("mean_duration_min"))
    beta_time_mean = base.beta_time_mean
    if mean_duration and mean_duration > 0:
        # Longer observed trips → weaker per-minute aversion (travelers
        # who actually commute 40 min are less time-sensitive than those
        # who drop out at 15). Bounded to the range used in the library.
        scale = 30.0 / mean_duration
        beta_time_mean = max(-0.2, min(-0.01, base.beta_time_mean * scale))

    return replace(
        base,
        beta_incentive_mean=beta_incentive_mean,
        beta_time_mean=beta_time_mean,
    )


def _estimate_beta_incentive(
    carpool_rate: float,
    inc_carpool: float,
    inc_solo: float,
    fallback: float,
) -> float:
    """
    Method-of-moments inverse logit.

    If observed carpool rate is p and carpool vs solo offers differ in
    expected incentive by ∆, then beta_incentive ≈ logit(p) / ∆ under
    the simplifying assumption that all other utility differences wash
    out in the aggregate. Clamped to a plausible range.
    """
    if carpool_rate is None or carpool_rate <= 0 or carpool_rate >= 1:
        return fallback

    delta = (inc_carpool or 0.0) - (inc_solo or 0.0)
    if delta <= 0.01:  # no signal — the two groups had the same incentive
        return fallback

    try:
        logit = math.log(carpool_rate / (1 - carpool_rate))
    except ValueError:
        return fallback

    raw = logit / delta
    return max(0.01, min(0.5, raw))


def _as_float(x: Any) -> float:
    if x is None:
        return 0.0
    try:
        value = float(x)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(value):
        return 0.0
    return value


def load_and_calibrate(
    db_path: str = "warehouse.duckdb",
    base: Optional[PopulationParameters] = None,
) -> PopulationParameters:
    """Convenience: extract features from warehouse then calibrate."""
    from scripts.extract_behavioral_features import extract_features

    features = extract_features(db_path)
    # trip_summary comes back as a list via the script; normalize it here.
    if isinstance(features.get("trip_summary"), list):
        features["trip_summary"] = features["trip_summary"][0] if features["trip_summary"] else {}
    return calibrate_from_features(features, base=base)
