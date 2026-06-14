"""Seeded topology generation and attacker placement for the harness.

Everything here is a pure function of an integer seed, so every reported number
is reproducible. Topologies are connected weighted graphs; attacker placement is
deterministic (most-central node by degree) so the intensity sweep isolates lie
magnitude rather than position.
"""

import random

import attacks


def random_connected_topology(n, seed, avg_degree=3.0, min_cost=1, max_cost=10):
    """Generate a connected weighted undirected graph.

    Construction: a random spanning tree (guarantees connectivity) plus extra
    random edges until the target average degree is reached. Integer link costs
    are drawn uniformly from ``[min_cost, max_cost]``.

    Returns ``{node: {neighbor: cost}}`` with node ids ``"n0"..``.
    """
    if n < 2:
        raise ValueError("need at least 2 nodes")
    rng = random.Random(seed)
    nodes = [f"n{i}" for i in range(n)]
    adj = {node: {} for node in nodes}

    def connect(a, b):
        cost = rng.randint(min_cost, max_cost)
        adj[a][b] = cost
        adj[b][a] = cost

    # Random spanning tree: attach each node to a uniformly random earlier node.
    for i in range(1, n):
        connect(nodes[i], nodes[rng.randrange(i)])

    target_edges = int(avg_degree * n / 2)
    current_edges = n - 1
    max_attempts = max(1, target_edges) * 20
    attempts = 0
    while current_edges < target_edges and attempts < max_attempts:
        attempts += 1
        a, b = rng.sample(nodes, 2)
        if b in adj[a]:
            continue
        connect(a, b)
        current_edges += 1
    return adj


def degree(adjacency):
    return {node: len(neighbors) for node, neighbors in adjacency.items()}


def pick_central_node(adjacency):
    """Pick the most central node as the attacker: highest degree, id tie-break.

    Degree is a cheap, deterministic proxy for how much transit traffic a node
    naturally sees -- a higher-degree attacker has more opportunity to attract
    traffic, which makes the impact axis meaningful.
    """
    deg = degree(adjacency)
    return max(adjacency, key=lambda node: (deg[node], node))


def false_cost_attacker(node_id, shave_fraction, targets=None, start_round=0):
    """An :class:`attacks.Attacker` running one FALSE_COST mode at a given intensity.

    ``targets=None`` lies about *every* destination (maximally aggressive
    blackhole), so impact is driven purely by ``shave_fraction``.
    """
    mode = attacks.FalseCost(shave_fraction=shave_fraction, targets=targets)
    return attacks.Attacker(node_id, [mode], start_round=start_round)


def collusion_attackers(group, targets, cost=0, vouch_cost=1, start_round=0):
    """Build an ``{node: Attacker}`` map for a colluding group.

    Every member advertises the same false ``cost`` to ``targets`` and vouches
    for the other members at ``vouch_cost`` (mutual corroboration), matching the
    COLLUSION config used elsewhere.
    """
    group = list(group)
    attackers = {}
    for node_id in group:
        mode = attacks.Collusion(group=group, targets=targets, cost=cost,
                                 vouch_cost=vouch_cost)
        attackers[node_id] = attacks.Attacker(node_id, [mode], start_round=start_round)
    return attackers
