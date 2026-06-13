"""FALSE_TOPOLOGY: advertise destinations / links that do not exist.

The attacker injects fabricated destinations (or fabricated cheap routes to real
destinations that it cannot actually reach) into its advertisement, polluting
neighbors' tables with phantom topology.
"""

from .base import Attack


class FalseTopology(Attack):
    def __init__(self, fake=None):
        """
        Args:
            fake: ``{dest: cost}`` of non-existent destinations/routes to inject.
        """
        self.fake = dict(fake) if fake else {}

    def apply(self, advertisement, ctx):
        ad = dict(advertisement)
        for dest, cost in self.fake.items():
            if dest == ctx.node_id:
                continue
            ad[dest] = cost
        return ad

    def describe(self):
        return f"FALSE_TOPOLOGY(fake={self.fake})"
