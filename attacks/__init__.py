"""Composable adversarial behaviors for the mesh simulator.

Attacks are pure ``{dest: cost}`` transforms (see :mod:`attacks.base`). They are
declared per node in the config under an ``attackers`` block and applied, in
order, to every outgoing advertisement once the attacker is active.

Config schema (all attack params are optional with sensible defaults)::

    "attackers": {
      "F": {
        "start_round": 3,
        "modes": [
          {"type": "FALSE_COST", "targets": ["J"], "cost": 0},
          {"type": "FLAPPING", "targets": ["G"], "low": 1, "high": 99, "period": 1},
          {"type": "FALSE_TOPOLOGY", "fake": {"Z9": 1}},
          {"type": "SELECTIVE", "victims": ["C"],
           "inner": [{"type": "FALSE_COST", "targets": ["A"], "cost": 0}]}
        ]
      }
    }

``start_round`` gates *all* of the node's modes on the gossip-round counter, so
runs are reproducible.
"""

from .base import Attack, AttackContext
from .false_cost import FalseCost
from .false_topology import FalseTopology
from .flapping import Flapping
from .selective import Selective

__all__ = [
    "Attack", "AttackContext", "FalseCost", "FalseTopology", "Flapping",
    "Selective", "Attacker", "build_attack", "from_config",
]


def build_attack(spec):
    """Construct a single :class:`Attack` from a config ``mode`` spec dict."""
    kind = spec["type"].upper()
    if kind == "FALSE_COST":
        return FalseCost(cost=spec.get("cost", 0), targets=spec.get("targets"))
    if kind == "FALSE_TOPOLOGY":
        return FalseTopology(fake=spec.get("fake", {}))
    if kind == "FLAPPING":
        return Flapping(
            targets=spec.get("targets"),
            low=spec.get("low", 1),
            high=spec.get("high", 99),
            period=spec.get("period", 1),
        )
    if kind == "SELECTIVE":
        return Selective(
            victims=spec.get("victims"),
            inner=[build_attack(s) for s in spec.get("inner", [])],
        )
    raise ValueError(f"unknown attack type: {spec['type']!r}")


class Attacker:
    """An ordered chain of attacks for one node, gated by a start round."""

    def __init__(self, node_id, chain, start_round=0):
        self.node_id = node_id
        self.chain = list(chain)
        self.start_round = start_round

    def active(self, round):
        return round >= self.start_round

    def transform(self, advertisement, ctx):
        """Apply the chain to an advertisement, or pass it through if not yet active."""
        if not self.active(ctx.round):
            return advertisement
        ad = advertisement
        for attack in self.chain:
            ad = attack.apply(ad, ctx)
        return ad

    def describe(self):
        modes = "; ".join(a.describe() for a in self.chain)
        return f"Attacker({self.node_id}, start_round={self.start_round}, [{modes}])"


def from_config(config, node_id):
    """Build an :class:`Attacker` for ``node_id`` from the config, or ``None``."""
    spec = config.get("attackers", {}).get(node_id)
    if not spec:
        return None
    chain = [build_attack(s) for s in spec.get("modes", [])]
    if not chain:
        return None
    return Attacker(node_id, chain, start_round=spec.get("start_round", 0))
