"""Detector 2 -- cross-source consistency (soft, statistical).

Invariant: neighbors all adjacent to the observer have comparable access to the
rest of the network, so the path costs P_n(D) = link(n) + adv_n(D) should
cluster; no single source should be a persistent, large, unilateral low-outlier.

The reference distribution for scoring n is computed with n *removed* -- a
leave-one-out (LOO) median. This is the crux: if n were included in its own
baseline, an aggressive liar would drag the baseline toward itself and mask its
deviation. Excluding n denies the attacker a vote in its own reference, and the
median tolerates up to ~half of the *other* witnesses being corrupt -- which is
exactly why a colluding majority is the documented breaking point.

For a destination with only one source among the observer's neighbors, the
detector abstains (no second witness), to avoid false-positives on legitimate
single-path pendants.
"""

import statistics

from .base import Detector


class CrossSourceDetector(Detector):
    name = "cross_source"

    def score(self, obs):
        out = self._zeros(obs)
        neighbors = obs.neighbors()
        dests = obs.destinations()

        for n in neighbors:
            total, counted = 0.0, 0
            for d in dests:
                p_n = obs.path_cost(n, d)
                if p_n is None:
                    continue
                # leave-one-out: the consensus excludes n itself
                others = [obs.path_cost(m, d) for m in neighbors if m != n]
                others = [p for p in others if p is not None]
                if not others:
                    continue  # single-source destination -> abstain
                consensus = statistics.median(others)
                counted += 1
                total += max(0.0, consensus - p_n)  # only flag undercutting (low) outliers
            out[n] = total / counted if counted else 0.0
        return out
