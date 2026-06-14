"""Deterministic, round-based distance-vector simulation (no UDP).

Reuses the same pure modules as the live node:
- ``routing.compute_table`` / ``routing.build_advertisement`` for the DV math,
- ``attacks`` for adversarial advertisement transforms,
so the harness measures the identical logic that runs over the wire.

A run advances in discrete synchronous gossip rounds. Each round every node
builds a per-recipient advertisement (with split horizon / poison reverse),
adversaries rewrite their own advertisements, vectors are delivered, and every
node recomputes its table. We record, for each honest observer, the time-ordered
advertisement history of each neighbor -- exactly the input the detectors expect.
"""

from dataclasses import dataclass, field

import routing
import attacks
import detectors


@dataclass
class SimulationResult:
    tables: dict                     # {node: {dest: {"cost", "next_hop"}}} final
    history: dict                    # {observer: {neighbor: [vector, ...]}}
    link_costs: dict                 # {node: {neighbor: cost}}
    attacker_ids: frozenset          # ground-truth malicious nodes
    converged_round: int = None      # round at which it last stabilized, or None
    rounds_run: int = 0

    def honest_nodes(self):
        return [n for n in self.tables if n not in self.attacker_ids]

    def observation(self, observer):
        """Build a detectors.Observation for one honest observer."""
        return detectors.Observation(
            link_costs=dict(self.link_costs[observer]),
            history={nb: list(vs) for nb, vs in self.history[observer].items()},
        )

    def observations(self, up_to_round=None):
        """All honest observers' observations, optionally truncated to a round.

        Truncating the history reconstructs the detector input as of an earlier
        round -- used to measure detection latency.
        """
        obs = {}
        for observer in self.honest_nodes():
            hist = self.history[observer]
            if up_to_round is not None:
                hist = {nb: vs[:up_to_round] for nb, vs in hist.items()}
            obs[observer] = detectors.Observation(
                link_costs=dict(self.link_costs[observer]),
                history={nb: list(vs) for nb, vs in hist.items()},
            )
        return obs


def simulate(topology, attackers=None, split_horizon=True, max_rounds=200,
             stop_when_stable=True, min_rounds=1):
    """Run the deterministic gossip simulation.

    Args:
        topology: ``{node: {neighbor: cost}}`` undirected weighted adjacency.
        attackers: ``{node: attacks.Attacker}`` (honest nodes omitted).
        split_horizon: enable split horizon + poison reverse.
        max_rounds: hard cap on rounds.
        stop_when_stable: stop early once a round produces no table change
            (won't trigger under flapping, which never stabilizes).
        min_rounds: never early-stop before this round. Used to run through a
            warmup-then-attack schedule: with attackers gated to ``start_round``,
            set ``min_rounds > start_round`` so the run does not stop at the
            pre-attack honest convergence but continues until it re-converges
            under attack.

    Returns:
        :class:`SimulationResult`.
    """
    attackers = attackers or {}
    nodes = list(topology)
    link_costs = {n: dict(topology[n]) for n in nodes}

    tables = {n: routing.compute_table(n, link_costs[n], {}) for n in nodes}
    history = {n: {nb: [] for nb in link_costs[n]} for n in nodes}

    converged_round = None
    rounds_run = 0
    for r in range(1, max_rounds + 1):
        rounds_run = r
        # 1) build advertisements (per recipient), applying adversarial transforms
        ads = {}
        for src in nodes:
            atk = attackers.get(src)
            for dst in link_costs[src]:
                ad = routing.build_advertisement(
                    tables[src], dst, split_horizon=split_horizon, poison_reverse=split_horizon)
                if atk is not None:
                    ctx = attacks.AttackContext(
                        node_id=src, recipient=dst, round=r, honest_table=tables[src])
                    ad = atk.transform(ad, ctx)
                ads[(src, dst)] = ad

        # 2) record what each observer received from each neighbor this round
        for observer in nodes:
            for nb in link_costs[observer]:
                history[observer][nb].append(ads[(nb, observer)])

        # 3) every node recomputes from the vectors it just received
        changed = False
        new_tables = {}
        for n in nodes:
            received = {nb: ads[(nb, n)] for nb in link_costs[n]}
            new = routing.compute_table(n, link_costs[n], received)
            new_tables[n] = new
            if new != tables[n]:
                changed = True
        tables = new_tables

        if not changed:
            converged_round = r
            if stop_when_stable and r >= min_rounds:
                break

    return SimulationResult(
        tables=tables, history=history, link_costs=link_costs,
        attacker_ids=frozenset(attackers), converged_round=converged_round,
        rounds_run=rounds_run,
    )
