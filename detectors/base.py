"""Detector inputs and interface.

A detector sees only what an honest node sees at runtime: its own trusted link
costs and the history of distance vectors its direct neighbors have gossiped to
it. No detector may reference attacker config, node IDs, or attack modes.

Scores are produced over the observer's direct neighbors, because an adversary
manipulates its own outgoing advertisement and is therefore observed by its
honest neighbors. The harness aggregates per-observer scores into global
per-node scores.
"""

from dataclasses import dataclass, field

import routing

INF = routing.INF


def is_finite(cost):
    """A usable advertised cost: present and not poisoned/unreachable."""
    return cost is not None and cost < INF


@dataclass
class Observation:
    """One honest observer's view.

    Attributes:
        link_costs: ``{neighbor: cost}`` -- the observer's trusted direct links.
        history: ``{neighbor: [vector, ...]}`` -- per neighbor, the time-ordered
            list of advertised ``{dest: cost}`` vectors (most recent last).
    """

    link_costs: dict = field(default_factory=dict)
    history: dict = field(default_factory=dict)

    def neighbors(self):
        """Sources we can name: direct neighbors that have advertised at least once."""
        return sorted(n for n in self.link_costs if self.history.get(n))

    def latest(self, n):
        h = self.history.get(n) or [{}]
        return h[-1]

    def advertised(self, n, dest):
        """Finite advertised cost from ``n`` to ``dest``, or ``None``."""
        c = self.latest(n).get(dest)
        return c if is_finite(c) else None

    def path_cost(self, n, dest):
        """Cost the observer would pay to reach ``dest`` via ``n`` (``None`` if no route)."""
        adv = self.advertised(n, dest)
        if adv is None:
            return None
        return self.link_costs[n] + adv

    def destinations(self):
        dests = set()
        for n in self.neighbors():
            for d, c in self.latest(n).items():
                if is_finite(c):
                    dests.add(d)
        return sorted(dests)

    def series(self, n, dest, window=None):
        """Time-ordered advertised costs of ``n`` for ``dest`` (latest last)."""
        h = self.history.get(n) or []
        if window is not None:
            h = h[-window:]
        return [vec.get(dest) for vec in h]


class Detector:
    """Maps an :class:`Observation` to ``{neighbor: suspicion_score}`` (>= 0)."""

    name = "detector"

    def score(self, obs):
        raise NotImplementedError

    @staticmethod
    def _zeros(obs):
        return {n: 0.0 for n in obs.neighbors()}
