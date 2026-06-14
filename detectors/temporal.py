"""Detector 3 -- temporal stability (dynamics).

Invariant: with bounded churn, honest advertised costs are piecewise-constant --
a value changes only when topology changes, then re-settles. A node should not
induce far more oscillation than the network-wide churn justifies.

Score: over a sliding window of the last W rounds, count *direction reversals* of
adv_n(D) (which distinguish oscillation from a one-time step), minus a
per-destination baseline (the median reversal count across neighbors) so that
genuine churn affecting everyone does not implicate a single node. A period-p
flapper produces ~W/p reversals, far above baseline.
"""

import statistics

from .base import Detector, is_finite

DEFAULT_WINDOW = 8


def count_reversals(series):
    """Number of direction changes in a cost time-series, ignoring gaps."""
    values = [c for c in series if is_finite(c)]
    reversals = 0
    last_sign = 0
    for prev, curr in zip(values, values[1:]):
        if curr == prev:
            continue
        sign = 1 if curr > prev else -1
        if last_sign != 0 and sign != last_sign:
            reversals += 1
        last_sign = sign
    return reversals


class TemporalDetector(Detector):
    name = "temporal"

    def __init__(self, window=DEFAULT_WINDOW):
        # Structural constant, set from gossip dynamics -- not fit to the attacks.
        self.window = window

    def score(self, obs):
        out = self._zeros(obs)
        neighbors = obs.neighbors()
        dests = obs.destinations()

        # per-destination churn baseline across all neighbors
        reversals = {
            n: {d: count_reversals(obs.series(n, d, self.window)) for d in dests}
            for n in neighbors
        }
        baseline = {
            d: statistics.median([reversals[n][d] for n in neighbors]) if neighbors else 0
            for d in dests
        }

        for n in neighbors:
            if not dests:
                continue
            excess = [max(0.0, reversals[n][d] - baseline[d]) for d in dests]
            out[n] = sum(excess) / len(dests)
        return out
