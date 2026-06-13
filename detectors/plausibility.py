"""Detector 1 -- plausibility bounds (hard, geometric).

Invariant: honest advertised costs are true shortest-path distances and obey the
triangle inequality. Anchored on the observer's own trusted links, for any two
neighbors n, m and destination D:

    adv_n(D) >= adv_m(D) - d(n, m) >= adv_m(D) - (link(n) + link(m))

The last step replaces the unknown d(n, m) with the sound detour bound through
the observer, so an honest node never violates it (no static false positives).

Score: the average provable deficit by which n undercuts the greatest lower bound
implied by any other neighbor. One-sided -- it targets implausibly *low* (i.e.
traffic-attracting) advertisements.
"""

from .base import Detector


class PlausibilityDetector(Detector):
    name = "plausibility"

    def score(self, obs):
        out = self._zeros(obs)
        neighbors = obs.neighbors()
        dests = obs.destinations()

        for n in neighbors:
            link_n = obs.link_costs[n]
            total, counted = 0.0, 0
            for d in dests:
                adv_n = obs.advertised(n, d)
                if adv_n is None:
                    continue
                # greatest lower bound on adv_n(d) implied by the other neighbors
                lower_bound = None
                for m in neighbors:
                    if m == n:
                        continue
                    adv_m = obs.advertised(m, d)
                    if adv_m is None:
                        continue
                    candidate = adv_m - link_n - obs.link_costs[m]
                    if lower_bound is None or candidate > lower_bound:
                        lower_bound = candidate
                if lower_bound is None:
                    continue  # no other source for d -> no bound to test
                counted += 1
                total += max(0.0, lower_bound - adv_n)
            out[n] = total / counted if counted else 0.0
        return out
