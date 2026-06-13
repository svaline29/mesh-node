"""Attack interface shared by every adversarial behavior.

An attack is a *pure transform* on the distance vector a node is about to
advertise to one specific neighbor. Attacks take a ``{dest: cost}`` advertisement
plus an :class:`AttackContext` and return a (possibly modified) advertisement.
They contain no sockets or threads, so they are importable and unit testable
independently of the live UDP simulation, and are reused unchanged by the
offline benchmarking harness.
"""

from dataclasses import dataclass, field


@dataclass
class AttackContext:
    """Everything an attack needs to decide what to advertise.

    Attributes:
        node_id: the (malicious) node doing the advertising.
        recipient: the neighbor this particular advertisement is being sent to.
        round: the sender's gossip-round counter -- the canonical, reproducible
            clock for attacks (used by FLAPPING and for start gating).
        elapsed: wall-clock seconds since the node started (live runs only).
        honest_table: the node's true routing table, ``{dest: {"cost", "next_hop"}}``.
    """

    node_id: str
    recipient: str
    round: int = 0
    elapsed: float = 0.0
    honest_table: dict = field(default_factory=dict)


class Attack:
    """Base class: subclasses implement :meth:`apply`."""

    def apply(self, advertisement, ctx):
        """Return a transformed copy of ``advertisement`` (a ``{dest: cost}`` dict)."""
        raise NotImplementedError

    def describe(self):
        return self.__class__.__name__
