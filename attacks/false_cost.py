"""FALSE_COST: advertise artificially low costs to attract / blackhole traffic.

By claiming a very low (or zero) cost to one or more destinations, the attacker
makes honest neighbors prefer routing through it. Combined with a node that then
drops or misroutes the traffic, this is a route hijack / blackhole.
"""

from .base import Attack


class FalseCost(Attack):
    def __init__(self, cost=0, targets=None, shave_fraction=None):
        """
        Args:
            cost: the bogus absolute low cost to advertise (used when
                ``shave_fraction`` is ``None``).
            targets: destinations to lie about. ``None``/empty means *every*
                destination currently in the advertisement.
            shave_fraction: if set (in ``[0, 1]``), advertise a *fraction* of the
                node's true cost instead of an absolute value: the lie becomes
                ``round(true_cost * (1 - shave_fraction))``. ``0`` is honest, ``1``
                is a full zero-cost blackhole. This parameterizes attack
                intensity for the impact-vs-detectability sweep.
        """
        self.cost = cost
        self.targets = list(targets) if targets else None
        self.shave_fraction = shave_fraction

    def _lie_for(self, dest, ctx):
        if self.shave_fraction is None:
            return self.cost
        true = ctx.honest_table.get(dest)
        if true is None:
            return self.cost  # no honest route to shave -> fall back to absolute
        true_cost = true["cost"] if isinstance(true, dict) else true
        return max(0, round(true_cost * (1.0 - self.shave_fraction)))

    def apply(self, advertisement, ctx):
        ad = dict(advertisement)
        targets = self.targets if self.targets is not None else list(ad.keys())
        for dest in targets:
            if dest == ctx.node_id:
                continue  # don't lie about the route to ourselves
            ad[dest] = self._lie_for(dest, ctx)
        return ad

    def describe(self):
        scope = ",".join(self.targets) if self.targets else "*"
        if self.shave_fraction is not None:
            return f"FALSE_COST(shave_fraction={self.shave_fraction}, targets={scope})"
        return f"FALSE_COST(cost={self.cost}, targets={scope})"
