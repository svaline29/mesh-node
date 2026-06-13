"""Unit tests for the pure weighted-routing core."""

import routing


# A small weighted, cyclic topology where the least-cost path differs from the
# fewest-hops path (A->B is cheaper via C than over the direct, expensive link).
ADJACENCY = {
    "A": {"B": 5, "C": 1},
    "B": {"A": 5, "C": 1, "D": 1},
    "C": {"A": 1, "B": 1, "D": 1},
    "D": {"C": 1, "B": 1, "E": 1},
    "E": {"D": 1},
}


def run_rounds(adjacency, split_horizon, max_rounds=200):
    """Synchronously run distance-vector gossip to a fixpoint.

    Returns ``(tables, rounds)`` where ``tables`` maps node -> routing table and
    ``rounds`` is the number of full rounds until no table changed. This mirrors
    the live gossip loop but is deterministic and transport-free.
    """
    nodes = list(adjacency)
    tables = {n: routing.compute_table(n, adjacency[n], {}) for n in nodes}

    for r in range(1, max_rounds + 1):
        ads = {
            (src, dst): routing.build_advertisement(tables[src], dst, split_horizon, split_horizon)
            for src in nodes
            for dst in adjacency[src]
        }
        changed = False
        new_tables = {}
        for n in nodes:
            vectors = {nb: ads[(nb, n)] for nb in adjacency[n]}
            new = routing.compute_table(n, adjacency[n], vectors)
            new_tables[n] = new
            if new != tables[n]:
                changed = True
        tables = new_tables
        if not changed:
            return tables, r
    return tables, max_rounds


def test_self_route_is_zero_cost():
    table = routing.compute_table("A", {"B": 5, "C": 1}, {})
    assert table["A"] == {"cost": 0, "next_hop": "A"}


def test_direct_links_seeded_without_vectors():
    table = routing.compute_table("A", {"B": 5, "C": 1}, {})
    assert table["B"]["cost"] == 5
    assert table["C"]["cost"] == 1
    assert table["C"]["next_hop"] == "C"


def test_least_cost_beats_fewest_hops():
    # A reaches B via C (cost 1 + 1 = 2), cheaper than the direct 5-cost link.
    vectors = {"C": {"A": 1, "B": 1, "C": 0, "D": 1}}
    table = routing.compute_table("A", {"B": 5, "C": 1}, vectors)
    assert table["B"]["cost"] == 2
    assert table["B"]["next_hop"] == "C"


def test_poisoned_route_is_unreachable():
    # A neighbor advertising INF for a destination must not create a route.
    vectors = {"C": {"B": routing.INF}}
    table = routing.compute_table("A", {"C": 1}, vectors)
    assert "B" not in table


def test_unknown_neighbor_vector_is_ignored():
    # A vector from a node that is not a current neighbor is dropped.
    vectors = {"Z": {"B": 1}}
    table = routing.compute_table("A", {"C": 1}, vectors)
    assert "B" not in table


def test_build_advertisement_split_horizon_poisons_reverse_route():
    table = {
        "A": {"cost": 0, "next_hop": "A"},
        "B": {"cost": 2, "next_hop": "C"},  # learned via C
        "C": {"cost": 1, "next_hop": "C"},
    }
    ad = routing.build_advertisement(table, "C", split_horizon=True, poison_reverse=True)
    assert ad["B"] == routing.INF        # poisoned back toward C
    assert ad["A"] == 0                   # our own route is advertised honestly


def test_build_advertisement_plain_split_horizon_omits_route():
    table = {"B": {"cost": 2, "next_hop": "C"}, "C": {"cost": 1, "next_hop": "C"}}
    ad = routing.build_advertisement(table, "C", split_horizon=True, poison_reverse=False)
    assert "B" not in ad


def test_build_advertisement_off_advertises_everything():
    table = {"B": {"cost": 2, "next_hop": "C"}, "C": {"cost": 1, "next_hop": "C"}}
    ad = routing.build_advertisement(table, "C", split_horizon=False)
    assert ad["B"] == 2


def test_all_pairs_shortest_matches_hand_computation():
    dist = routing.all_pairs_shortest(ADJACENCY)
    assert dist["A"] == {"A": 0, "B": 2, "C": 1, "D": 2, "E": 3}
    assert dist["E"] == {"E": 0, "D": 1, "C": 2, "B": 2, "A": 3}


def test_distance_vector_converges_to_shortest_paths():
    expected = routing.all_pairs_shortest(ADJACENCY)
    for split_horizon in (True, False):
        tables, rounds = run_rounds(ADJACENCY, split_horizon)
        assert rounds < 200, "did not converge"
        for node in ADJACENCY:
            assert routing.to_vector(tables[node]) == expected[node]
