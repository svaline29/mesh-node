"""Pure, transport-free distance-vector routing core.

This module contains no sockets, threads, or global state. It is imported by
the live UDP node (``node.py``) and by the offline benchmarking harness so that
both run identical routing logic. Everything here is deterministic and unit
testable.

Data shapes used throughout:

* ``link_costs``: ``{neighbor_id: cost}`` -- this node's direct, weighted links.
* ``vector``:     ``{dest_id: cost}``     -- a distance vector (what a node
  advertises / what a neighbor reports). Costs are non-negative numbers; the
  sentinel ``INF`` marks an explicitly unreachable destination (used by poison
  reverse).
* ``table``:      ``{dest_id: {"cost": cost, "next_hop": neighbor_id}}`` -- a
  full routing table with chosen next hops.
"""

# Sentinel "infinity". A plain large integer keeps gossip messages valid JSON
# (unlike float('inf'), which serializes to the non-standard token Infinity).
INF = 10 ** 9


def to_vector(table):
    """Project a routing table down to a bare distance vector ``{dest: cost}``."""
    return {dest: info["cost"] for dest, info in table.items()}


def compute_table(node_id, link_costs, neighbor_vectors):
    """Recompute this node's least-cost routing table from scratch.

    This is one relaxation pass of Bellman-Ford over the most recent distance
    vector advertised by each neighbor. Because neighbor vectors already encode
    each neighbor's own best costs, a single pass per gossip round is the
    standard distance-vector formulation and converges over successive rounds.

    Args:
        node_id: this node's id.
        link_costs: ``{neighbor_id: cost}`` for direct, currently-live links.
        neighbor_vectors: ``{neighbor_id: {dest: cost}}`` latest advertisements.
            Vectors from ids that are not current neighbors are ignored.

    Returns:
        ``{dest: {"cost": cost, "next_hop": neighbor_id}}``. Always contains a
        zero-cost self route. Unreachable destinations are omitted.
    """
    best = {node_id: (0, node_id)}

    # Direct links: cost to reach a neighbor is at most the link cost itself.
    for neighbor, cost in link_costs.items():
        if cost < best.get(neighbor, (INF, None))[0]:
            best[neighbor] = (cost, neighbor)

    # Indirect routes learned via each neighbor's advertised vector.
    for neighbor, vector in neighbor_vectors.items():
        link = link_costs.get(neighbor)
        if link is None:
            # Not a current neighbor (e.g. stale vector after a link drop).
            continue
        for dest, advertised in vector.items():
            if dest == node_id:
                continue
            if advertised >= INF:
                # Neighbor explicitly poisoned this route; treat as unreachable.
                continue
            total = link + advertised
            if total < best.get(dest, (INF, None))[0]:
                best[dest] = (total, neighbor)

    return {dest: {"cost": cost, "next_hop": nh} for dest, (cost, nh) in best.items()}


def build_advertisement(table, recipient, split_horizon=True, poison_reverse=True):
    """Build the distance vector this node should send to ``recipient``.

    With ``split_horizon`` off, the full vector is advertised to everyone
    (classic naive distance-vector, prone to count-to-infinity).

    With ``split_horizon`` on, any destination whose next hop is ``recipient``
    is either omitted (plain split horizon) or advertised as ``INF``
    (split horizon with poison reverse). Poison reverse breaks two-node routing
    loops faster because it actively tells the neighbor "do not route to this
    destination through me".

    Returns a ``{dest: cost}`` vector.
    """
    advertisement = {}
    for dest, info in table.items():
        learned_from_recipient = info["next_hop"] == recipient and dest != recipient
        if split_horizon and learned_from_recipient:
            if poison_reverse:
                advertisement[dest] = INF
            # else: plain split horizon -> omit entirely.
            continue
        advertisement[dest] = info["cost"]
    return advertisement


def adjacency_from_links(links, default_cost=1):
    """Build an undirected weighted adjacency map from a config ``links`` list.

    ``links`` is a list of ``{"a": id, "b": id, "cost": number}`` (cost
    optional). Returns ``{node: {neighbor: cost}}``. The lower cost wins if a
    pair is listed more than once.
    """
    adjacency = {}
    for link in links:
        a, b = link["a"], link["b"]
        cost = link.get("cost", default_cost)
        for x, y in ((a, b), (b, a)):
            adjacency.setdefault(x, {})
            if cost < adjacency[x].get(y, INF):
                adjacency[x][y] = cost
    return adjacency


def link_costs_from_config(config, node_id, default_cost=1):
    """Extract ``{neighbor: cost}`` for ``node_id`` from a parsed config dict."""
    adjacency = adjacency_from_links(config.get("links", []), default_cost)
    return dict(adjacency.get(node_id, {}))


def all_pairs_shortest(adjacency):
    """All-pairs least-cost distances via Floyd-Warshall.

    Args:
        adjacency: ``{node: {neighbor: cost}}`` (undirected or directed).

    Returns:
        ``{src: {dest: cost}}`` including ``dist[n][n] == 0`` and excluding
        unreachable pairs.
    """
    nodes = set(adjacency)
    for neighbors in adjacency.values():
        nodes.update(neighbors)
    nodes = sorted(nodes)

    dist = {u: {v: (0 if u == v else INF) for v in nodes} for u in nodes}
    for u, neighbors in adjacency.items():
        for v, cost in neighbors.items():
            if cost < dist[u][v]:
                dist[u][v] = cost

    for k in nodes:
        dk = dist[k]
        for u in nodes:
            duk = dist[u][k]
            if duk >= INF:
                continue
            du = dist[u]
            for v in nodes:
                through = duk + dk[v]
                if through < du[v]:
                    du[v] = through

    return {
        u: {v: c for v, c in row.items() if c < INF}
        for u, row in dist.items()
    }
