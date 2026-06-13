"""COLLUSION: multiple adversaries that corroborate each other's lies.

A single liar is exposed by cross-source consistency: its claim about a
destination disagrees with what every honest neighbor independently implies.
Colluding nodes defeat this by telling the *same* lie and vouching for one
another, so an honest observer sees a (fabricated) consensus instead of an
outlier.

Each colluder:

1. advertises the same coordinated false `cost` to the same `targets`
   (identical stories => no disagreement to detect), and
2. advertises a cheap route to each accomplice (`vouch_cost`), so the group
   looks like a tight, cheap cluster that plausibly owns those routes.

As the colluding group grows, the fake consensus increasingly outweighs the
honest one — this is exactly the Byzantine-threshold degradation the harness
sweeps (1 vs 2 vs 3 colluders).
"""

from .base import Attack


class Collusion(Attack):
    def __init__(self, group, targets, cost=0, vouch_cost=1):
        """
        Args:
            group: ids of all colluding nodes (including this one). Used to know
                which accomplices to vouch for, and documents the conspiracy.
            targets: destinations the group jointly claims a cheap route to.
            cost: the shared, coordinated false cost advertised to ``targets``.
            vouch_cost: cost advertised toward each accomplice (mutual vouching).
        """
        self.group = list(group)
        self.targets = list(targets)
        self.cost = cost
        self.vouch_cost = vouch_cost

    def apply(self, advertisement, ctx):
        ad = dict(advertisement)
        for dest in self.targets:
            if dest == ctx.node_id:
                continue
            ad[dest] = self.cost
        for ally in self.group:
            if ally == ctx.node_id:
                continue
            ad[ally] = self.vouch_cost
        return ad

    def describe(self):
        peers = ",".join(sorted(self.group))
        scope = ",".join(self.targets) if self.targets else "*"
        return f"COLLUSION(group={peers}, targets={scope}, cost={self.cost})"
