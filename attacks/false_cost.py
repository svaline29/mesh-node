"""FALSE_COST: advertise artificially low costs to attract / blackhole traffic.

By claiming a very low (or zero) cost to one or more destinations, the attacker
makes honest neighbors prefer routing through it. Combined with a node that then
drops or misroutes the traffic, this is a route hijack / blackhole.
"""

from .base import Attack


class FalseCost(Attack):
    def __init__(self, cost=0, targets=None):
        """
        Args:
            cost: the bogus low cost to advertise.
            targets: destinations to lie about. ``None``/empty means *every*
                destination currently in the advertisement.
        """
        self.cost = cost
        self.targets = list(targets) if targets else None

    def apply(self, advertisement, ctx):
        ad = dict(advertisement)
        targets = self.targets if self.targets is not None else list(ad.keys())
        for dest in targets:
            if dest == ctx.node_id:
                continue  # don't lie about the route to ourselves
            ad[dest] = self.cost
        return ad

    def describe(self):
        scope = ",".join(self.targets) if self.targets else "*"
        return f"FALSE_COST(cost={self.cost}, targets={scope})"
