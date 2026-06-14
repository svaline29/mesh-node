"""Correctness tests for the offline benchmarking harness.

These pin down the two things experiments depend on: the deterministic simulator
reproduces Bellman-Ford shortest paths in the honest case, and the metrics
(impact tracing, ROC, operating point) are right on hand-checkable inputs.
"""

import routing
import detectors
from harness import simulator, scenarios, metrics


# --------------------------------------------------------------------------- #
# Simulator
# --------------------------------------------------------------------------- #

def _square_with_chord():
    # n0 - n1 - n2 - n3 - n0 ring, plus a chord n0-n2, weighted.
    return {
        "n0": {"n1": 1, "n3": 1, "n2": 5},
        "n1": {"n0": 1, "n2": 1},
        "n2": {"n1": 1, "n3": 1, "n0": 5},
        "n3": {"n2": 1, "n0": 1},
    }


def test_simulator_matches_all_pairs_shortest_when_honest():
    topo = _square_with_chord()
    result = simulator.simulate(topo, attackers={}, split_horizon=True)
    assert result.converged_round is not None
    expected = routing.all_pairs_shortest(topo)
    for node, table in result.tables.items():
        got = routing.to_vector(table)
        assert got == expected[node], node


def test_simulator_records_history_for_detectors():
    topo = _square_with_chord()
    result = simulator.simulate(topo, attackers={}, split_horizon=True)
    obs = result.observations()
    # one observation per honest node, each with history keyed by its neighbors
    assert set(obs) == set(topo)
    for node, ob in obs.items():
        assert set(ob.history) == set(topo[node])
        assert all(len(v) == result.rounds_run for v in ob.history.values())


def test_random_topology_is_connected_and_reproducible():
    a = scenarios.random_connected_topology(20, seed=7)
    b = scenarios.random_connected_topology(20, seed=7)
    assert a == b  # reproducible from seed
    # connected: all-pairs shortest reaches every node from n0
    dist = routing.all_pairs_shortest(a)
    assert len(dist["n0"]) == 20


# --------------------------------------------------------------------------- #
# Impact tracing
# --------------------------------------------------------------------------- #

def test_trace_path_follows_next_hops():
    tables = {
        "A": {"C": {"cost": 2, "next_hop": "B"}},
        "B": {"C": {"cost": 1, "next_hop": "C"}},
        "C": {"C": {"cost": 0, "next_hop": "C"}},
    }
    path, reached = metrics.trace_path(tables, "A", "C")
    assert reached and path == ["A", "B", "C"]


def test_trace_path_detects_loop():
    tables = {
        "A": {"C": {"cost": 9, "next_hop": "B"}},
        "B": {"C": {"cost": 9, "next_hop": "A"}},
    }
    path, reached = metrics.trace_path(tables, "A", "C")
    assert not reached


def test_passthrough_share_counts_attacker_on_path():
    # Line A-B-C: only pair touching B (as a transit) is A->C and C->A.
    tables = {
        "A": {"A": {"cost": 0, "next_hop": "A"},
              "B": {"cost": 1, "next_hop": "B"},
              "C": {"cost": 2, "next_hop": "B"}},
        "B": {"A": {"cost": 1, "next_hop": "A"},
              "B": {"cost": 0, "next_hop": "B"},
              "C": {"cost": 1, "next_hop": "C"}},
        "C": {"A": {"cost": 2, "next_hop": "B"},
              "B": {"cost": 1, "next_hop": "B"},
              "C": {"cost": 0, "next_hop": "C"}},
    }
    # honest nodes A, C; attacker B. ordered honest pairs: A->C, C->A (both via B).
    share = metrics.passthrough_share(tables, {"B"}, honest_nodes=["A", "C"])
    assert share == 1.0


def test_false_cost_intensity_increases_impact():
    topo = scenarios.random_connected_topology(25, seed=3, avg_degree=3)
    attacker = scenarios.pick_central_node(topo)

    honest = simulator.simulate(topo, {}, split_horizon=True)
    honest_share = metrics.passthrough_share(honest.tables, {attacker})

    big_lie = {attacker: scenarios.false_cost_attacker(attacker, shave_fraction=1.0)}
    attacked = simulator.simulate(topo, big_lie, split_horizon=True)
    attacked_share = metrics.passthrough_share(attacked.tables, {attacker})

    assert attacked_share >= honest_share
    assert attacked_share > 0.0


# --------------------------------------------------------------------------- #
# Detection metrics
# --------------------------------------------------------------------------- #

def test_roc_and_auc_perfect_separation():
    labels = [(0.1, False), (0.2, False), (0.9, True), (0.8, True)]
    pts = metrics.roc_curve(labels)
    assert abs(metrics.auc(pts) - 1.0) < 1e-9


def test_roc_auc_no_separation_is_half():
    # tied scores -> classifier is uninformative -> AUC 0.5
    labels = [(0.5, True), (0.5, False), (0.5, True), (0.5, False)]
    pts = metrics.roc_curve(labels)
    assert abs(metrics.auc(pts) - 0.5) < 1e-9


def test_operating_threshold_holds_fpr():
    honest = [0.0, 0.0, 0.1, 0.1, 0.2, 0.2, 0.3, 0.3, 0.4, 0.4]
    tau = metrics.operating_threshold(honest, max_fpr=0.2)
    fpr = sum(1 for s in honest if s > tau) / len(honest)
    assert fpr <= 0.2


def test_detection_rate():
    assert metrics.detection_rate([0.9, 0.1], threshold=0.5) == 0.5


def test_detectors_flag_attacker_at_onset():
    # A central attacker lies cheaply about everything. Evaluated at attack
    # ONSET (before the poison propagates) the ensemble ranks the attacker top
    # and the hard plausibility bound fires on the attacker alone.
    topo = scenarios.random_connected_topology(30, seed=11, avg_degree=4)
    attacker = scenarios.pick_central_node(topo)
    honest = simulator.simulate(topo, {}, split_horizon=True)
    onset = honest.converged_round + 1

    atk = {attacker: scenarios.false_cost_attacker(attacker, shave_fraction=1.0,
                                                   start_round=onset)}
    result = simulator.simulate(topo, atk, split_horizon=True,
                                max_rounds=onset + 40, min_rounds=onset + 1)
    analysis = detectors.analyze(result.observations(up_to_round=onset))

    ensemble = analysis["ensemble"]
    assert max(ensemble, key=ensemble.get) == attacker
    # plausibility (hard bound) flags the attacker and only the attacker
    plaus = analysis["per_detector"]["plausibility"]
    assert plaus[attacker] > 0
    assert all(v == 0 for n, v in plaus.items() if n != attacker)


def test_gross_lie_homogenizes_by_convergence():
    # By full convergence the gross lie has propagated everywhere, so the
    # attacker is no longer a local outlier -- this is why detectability is
    # measured at onset, not at steady state. Documents the regime.
    topo = scenarios.random_connected_topology(30, seed=11, avg_degree=4)
    attacker = scenarios.pick_central_node(topo)
    honest = simulator.simulate(topo, {}, split_horizon=True)
    onset = honest.converged_round + 1
    atk = {attacker: scenarios.false_cost_attacker(attacker, shave_fraction=1.0,
                                                   start_round=onset)}
    result = simulator.simulate(topo, atk, split_horizon=True,
                                max_rounds=onset + 40, min_rounds=onset + 1)
    onset_scores = detectors.analyze(result.observations(up_to_round=onset))["ensemble"]
    final_scores = detectors.analyze(result.observations())["ensemble"]
    # attacker is clearly top at onset, but its margin collapses at steady state
    assert max(onset_scores, key=onset_scores.get) == attacker
    onset_margin = onset_scores[attacker] - max(v for n, v in onset_scores.items() if n != attacker)
    final_margin = final_scores[attacker] - max(v for n, v in final_scores.items() if n != attacker)
    assert onset_margin > final_margin
