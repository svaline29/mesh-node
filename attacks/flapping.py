"""FLAPPING: rapidly alternate advertised costs to induce instability.

The attacker oscillates the advertised cost to its targets every ``period``
gossip rounds, forcing honest nodes to repeatedly recompute and re-advertise
routes. Driving this from the gossip-round counter keeps it deterministic and
reproducible in both the live sim and the offline harness.
"""

from .base import Attack


class Flapping(Attack):
    def __init__(self, targets=None, low=1, high=99, period=1):
        """
        Args:
            targets: destinations to flap. ``None``/empty means every destination.
            low: cost advertised during the "low" phase.
            high: cost advertised during the "high" phase.
            period: number of gossip rounds spent in each phase (>= 1).
        """
        self.targets = list(targets) if targets else None
        self.low = low
        self.high = high
        self.period = max(1, period)

    def apply(self, advertisement, ctx):
        ad = dict(advertisement)
        phase = (ctx.round // self.period) % 2
        value = self.low if phase == 0 else self.high
        targets = self.targets if self.targets is not None else list(ad.keys())
        for dest in targets:
            if dest == ctx.node_id:
                continue
            ad[dest] = value
        return ad

    def describe(self):
        scope = ",".join(self.targets) if self.targets else "*"
        return f"FLAPPING(low={self.low}, high={self.high}, period={self.period}, targets={scope})"
