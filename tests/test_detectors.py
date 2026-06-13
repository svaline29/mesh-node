"""Detector unit tests against synthetic routing tables with planted lies.

Each test maps to a row of the should / should-not-catch tables in
docs/detector_design.md, plus explicit tests for the leave-one-out reference,
the collusion breaking point, and the documented structural limits.
"""

import detectors
from detectors import (
    Observation, PlausibilityDetector, CrossSourceDetector, TemporalDetector,
)


def obs(link_costs, vectors):
    """Single-snapshot observation. vectors: {neighbor: {dest: cost}}."""
    return Observation(link_costs=link_costs, history={n: [v] for n, v in vectors.items()})


def obs_hist(link_costs, histories):
    """Multi-snapshot observation. histories: {neighbor: [vector, ...]}."""
    return Observation(link_costs=link_costs, history=histories)


# --- honest baseline: no false positives ----------------------------------

def test_honest_network_scores_zero_everywhere():
    o = obs({"P": 1, "Q": 1, "R": 1},
            {"P": {"T1": 5, "T2": 6}, "Q": {"T1": 5, "T2": 6}, "R": {"T1": 5, "T2": 6}})
    for det in detectors.default_detectors():
        scores = det.score(o)
        assert all(v == 0.0 for v in scores.values()), f"{det.name} false-positived"


# --- plausibility: hard bound catches gross low lies -----------------------

def test_plausibility_catches_gross_false_cost():
    # P claims cost 0 to T1; honest Q,R say 5. Bound B = 5 - 1 - 1 = 3 > 0.
    o = obs({"P": 1, "Q": 1, "R": 1},
            {"P": {"T1": 0}, "Q": {"T1": 5}, "R": {"T1": 5}})
    scores = PlausibilityDetector().score(o)
    assert scores["P"] > 0
    assert scores["Q"] == 0.0 and scores["R"] == 0.0


def test_plausibility_misses_subtle_lie_below_slack():
    # P claims 4 (true 5); bound is only 3, so 4 >= 3 -> no provable violation.
    # This is the deliberate loose-bound gap that motivates the statistical detector.
    o = obs({"P": 1, "Q": 1, "R": 1},
            {"P": {"T1": 4}, "Q": {"T1": 5}, "R": {"T1": 5}})
    assert PlausibilityDetector().score(o)["P"] == 0.0


# --- cross-source: statistical detector + the handoff ----------------------

def test_cross_source_catches_blackhole():
    o = obs({"P": 1, "Q": 1, "R": 1},
            {"P": {"T1": 0, "T2": 0}, "Q": {"T1": 5, "T2": 6}, "R": {"T1": 5, "T2": 6}})
    scores = CrossSourceDetector().score(o)
    assert scores["P"] > scores["Q"] and scores["P"] > scores["R"]


def test_cross_source_extends_coverage_to_subtle_lie():
    # The lie plausibility missed (4 vs 5) still produces a positive cross-source score.
    o = obs({"P": 1, "Q": 1, "R": 1},
            {"P": {"T1": 4}, "Q": {"T1": 5}, "R": {"T1": 5}})
    assert CrossSourceDetector().score(o)["P"] > 0


# --- leave-one-out: the attacker cannot bias its own baseline --------------

def test_cross_source_uses_leave_one_out_reference():
    # Two neighbors: liar P (path 1) and honest Q (path 6).
    # LOO median for P excludes P -> consensus = 6 -> score 5.
    # If P were (wrongly) included, median([1,6]) = 3.5 -> score 2.5.
    o = obs({"P": 1, "Q": 1}, {"P": {"T1": 0}, "Q": {"T1": 5}})
    score_p = CrossSourceDetector().score(o)["P"]
    assert score_p == 5.0          # consensus excludes the liar
    assert score_p != 2.5          # the include-self (biased) value


# --- collusion: the documented breaking point of cross-source --------------

def test_cross_source_degrades_as_collusion_grows():
    links = {"A": 1, "B": 1, "C": 1}
    # size 1: only A lies
    one = obs(links, {"A": {"T": 0}, "B": {"T": 6}, "C": {"T": 6}})
    # size 2: A and B collude
    two = obs(links, {"A": {"T": 0}, "B": {"T": 0}, "C": {"T": 6}})
    # size 3: all three corroborate the lie
    three = obs(links, {"A": {"T": 0}, "B": {"T": 0}, "C": {"T": 0}})

    s1 = CrossSourceDetector().score(one)["A"]
    s2 = CrossSourceDetector().score(two)["A"]
    s3 = CrossSourceDetector().score(three)["A"]
    assert s1 > s2 > s3            # detection collapses as the fake consensus grows
    assert s3 == 0.0              # full corroboration -> undetectable


def test_plausibility_also_defeated_by_full_collusion():
    links = {"A": 1, "B": 1, "C": 1}
    three = obs(links, {"A": {"T": 0}, "B": {"T": 0}, "C": {"T": 0}})
    assert PlausibilityDetector().score(three)["A"] == 0.0


# --- temporal: flapping vs steady / one-time step --------------------------

def test_temporal_catches_flapping():
    o = obs_hist({"F": 1, "S": 1}, {
        "F": [{"T": 1}, {"T": 99}, {"T": 1}, {"T": 99}, {"T": 1}, {"T": 99}],
        "S": [{"T": 5}] * 6,
    })
    scores = TemporalDetector().score(o)
    assert scores["F"] > 0
    assert scores["S"] == 0.0


def test_temporal_ignores_one_time_step():
    # A single legitimate convergence step is not an oscillation.
    o = obs_hist({"F": 1, "S": 1}, {
        "F": [{"T": 5}, {"T": 5}, {"T": 3}, {"T": 3}],
        "S": [{"T": 5}] * 4,
    })
    assert TemporalDetector().score(o)["F"] == 0.0


def test_temporal_invisible_to_constant_lie():
    # A constant FALSE_COST lie has zero reversals -> correctly left to detectors 1/2.
    o = obs_hist({"L": 1, "S": 1}, {
        "L": [{"T": 0}] * 5,
        "S": [{"T": 6}] * 5,
    })
    assert TemporalDetector().score(o)["L"] == 0.0


# --- documented structural limits ------------------------------------------

def test_pure_phantom_pendant_is_not_flagged():
    # F invents Z reachable only via F; no other witness. Detectors abstain (limit 3).
    o = obs({"P": 1, "F": 1},
            {"P": {"T": 5}, "F": {"T": 5, "Z": 1}})
    plaus = PlausibilityDetector().score(o)
    xsrc = CrossSourceDetector().score(o)
    assert plaus["F"] == 0.0 and xsrc["F"] == 0.0


def test_node_with_no_honest_neighbor_is_absent_from_results():
    # The attacker X is nobody's neighbor here, so no honest observer scores it (limit 2).
    observations = {
        "O1": obs({"P": 1, "Q": 1}, {"P": {"T": 5}, "Q": {"T": 5}}),
        "O2": obs({"P": 1, "R": 1}, {"P": {"T": 5}, "R": {"T": 5}}),
    }
    result = detectors.analyze(observations)
    assert "X" not in result["ensemble"]


# --- ensemble / aggregation plumbing ---------------------------------------

def test_normalize_handles_flat_and_spread():
    assert detectors.normalize({"a": 3, "b": 3}) == {"a": 0.0, "b": 0.0}
    assert detectors.normalize({"a": 0, "b": 10}) == {"a": 0.0, "b": 1.0}


def test_aggregate_observers_mean_and_max():
    per_obs = [{"X": 1.0}, {"X": 3.0}, {"Y": 2.0}]
    assert detectors.aggregate_observers(per_obs, "mean") == {"X": 2.0, "Y": 2.0}
    assert detectors.aggregate_observers(per_obs, "max") == {"X": 3.0, "Y": 2.0}


def test_analyze_reports_per_detector_and_ensemble():
    observations = {
        "O": obs({"P": 1, "Q": 1, "R": 1},
                 {"P": {"T1": 0, "T2": 0}, "Q": {"T1": 5, "T2": 6}, "R": {"T1": 5, "T2": 6}}),
    }
    result = detectors.analyze(observations)
    assert set(result["per_detector"]) == {"plausibility", "cross_source", "temporal"}
    # P is the planted blackhole -> highest ensemble suspicion.
    ens = result["ensemble"]
    assert ens["P"] == max(ens.values()) and ens["P"] > 0
