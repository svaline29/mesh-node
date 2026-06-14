"""Principled anomaly detectors for adversarial routing.

Each detector reasons from an invariant that honest gossip satisfies and lies
tend to violate (see ``docs/detector_design.md``). Detectors are pure functions
of an :class:`Observation` (the observer's own link costs + neighbor
advertisement history) and import nothing from ``attacks/`` or any config.

Design guarantees encoded here:

* Every detector emits a **continuous** per-node score (never a binary), so the
  harness can sweep a decision threshold for ROC / precision-recall.
* Detectors are reported **individually**; the ensemble is a fixed, equal-weight
  combination used only for a single headline number. **No weight or detector
  constant is fit to the attack scenarios** -- the only swept knob is the
  threshold.
* Scoring uses leave-one-out references (see :mod:`detectors.cross_source`) so an
  attacker cannot bias its own baseline.
"""

from .base import Detector, Observation, is_finite
from .plausibility import PlausibilityDetector
from .cross_source import CrossSourceDetector
from .temporal import TemporalDetector

__all__ = [
    "Detector", "Observation", "is_finite",
    "PlausibilityDetector", "CrossSourceDetector", "TemporalDetector",
    "default_detectors", "per_detector_scores", "normalize",
    "aggregate_observers", "combine_ensemble", "analyze",
]


def default_detectors():
    """The standard detector suite (fresh instances)."""
    return [PlausibilityDetector(), CrossSourceDetector(), TemporalDetector()]


def per_detector_scores(obs, detectors=None):
    """Run each detector on one observation: ``{detector_name: {neighbor: score}}``."""
    detectors = detectors or default_detectors()
    return {d.name: d.score(obs) for d in detectors}


def normalize(scores):
    """Min-max scale a ``{node: score}`` mapping into ``[0, 1]``.

    A flat distribution (no spread) maps to all zeros, so a detector that fires
    on nobody contributes nothing to the ensemble.
    """
    if not scores:
        return {}
    values = list(scores.values())
    lo, hi = min(values), max(values)
    if hi <= lo:
        return {k: 0.0 for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


def aggregate_observers(per_observer, reduce="mean"):
    """Aggregate one detector's per-observer scores into a global per-node score.

    Args:
        per_observer: list of ``{target: score}`` dicts, one per honest observer.
        reduce: ``"mean"`` (consensus of honest observers, default) or ``"max"``
            (flagged by anyone).
    """
    bucket = {}
    for scores in per_observer:
        for target, value in scores.items():
            bucket.setdefault(target, []).append(value)
    if reduce == "max":
        return {t: max(v) for t, v in bucket.items()}
    return {t: sum(v) / len(v) for t, v in bucket.items()}


def combine_ensemble(per_detector_global, weights=None):
    """Combine global per-detector scores into one ensemble score per node.

    Each detector's scores are min-max normalized across nodes, then combined
    with fixed weights (equal by default). Weights are a presentation choice,
    deliberately not fit to the attacks.
    """
    if not per_detector_global:
        return {}
    names = list(per_detector_global)
    if weights is None:
        weights = {name: 1.0 for name in names}
    weight_sum = sum(weights.get(name, 0.0) for name in names) or 1.0

    normed = {name: normalize(scores) for name, scores in per_detector_global.items()}
    nodes = set()
    for scores in per_detector_global.values():
        nodes.update(scores)

    return {
        node: sum(weights.get(name, 0.0) * normed[name].get(node, 0.0) for name in names) / weight_sum
        for node in nodes
    }


def analyze(observations, detectors=None, weights=None, reduce="mean"):
    """End-to-end analysis across all honest observers.

    Args:
        observations: ``{observer_id: Observation}`` for the honest observers.
        detectors: detector suite (defaults to :func:`default_detectors`).
        weights: ensemble weights (defaults to equal).
        reduce: cross-observer aggregation, ``"mean"`` or ``"max"``.

    Returns:
        ``{"per_detector": {name: {node: score}}, "ensemble": {node: score}}``.
    """
    detectors = detectors or default_detectors()
    per_detector_global = {}
    for det in detectors:
        per_observer = [det.score(obs) for obs in observations.values()]
        per_detector_global[det.name] = aggregate_observers(per_observer, reduce)
    return {
        "per_detector": per_detector_global,
        "ensemble": combine_ensemble(per_detector_global, weights),
    }
