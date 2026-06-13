"""Unit tests for the convergence-detection logic in observer.py."""

import observer


CONFIG = {
    "nodes": {n: {"port": 5000 + i} for i, n in enumerate("ABCDE", start=1)},
    "links": [
        {"a": "A", "b": "B", "cost": 5},
        {"a": "A", "b": "C", "cost": 1},
        {"a": "B", "b": "C", "cost": 1},
        {"a": "B", "b": "D", "cost": 1},
        {"a": "C", "b": "D", "cost": 1},
        {"a": "D", "b": "E", "cost": 1},
    ],
}


def test_expected_vectors_are_least_cost():
    expected = observer.expected_vectors(CONFIG)
    assert expected["A"] == {"A": 0, "B": 2, "C": 1, "D": 2, "E": 3}


def test_tables_match_expected_true_when_equal():
    expected = observer.expected_vectors(CONFIG)
    assert observer.tables_match_expected(dict(expected), expected)


def test_tables_match_expected_false_on_mismatch():
    expected = observer.expected_vectors(CONFIG)
    reported = {n: dict(v) for n, v in expected.items()}
    reported["A"]["B"] = 99  # one wrong cost
    assert not observer.tables_match_expected(reported, expected)


def _reported_from(expected, now, age=10.0):
    """Build a reported-state dict where every node converged ``age`` seconds ago."""
    return {n: {"table": dict(v), "last_change": now - age} for n, v in expected.items()}


def test_evaluate_convergence_success():
    expected = observer.expected_vectors(CONFIG)
    now = 1000.0
    converged, _ = observer.evaluate_convergence(_reported_from(expected, now), expected, now)
    assert converged


def test_evaluate_convergence_waits_for_missing_node():
    expected = observer.expected_vectors(CONFIG)
    now = 1000.0
    reported = _reported_from(expected, now)
    del reported["E"]
    converged, reason = observer.evaluate_convergence(reported, expected, now)
    assert not converged
    assert "E" in reason


def test_evaluate_convergence_rejects_inconsistent_tables():
    expected = observer.expected_vectors(CONFIG)
    now = 1000.0
    reported = _reported_from(expected, now)
    reported["A"]["table"]["B"] = 1  # adversarially low / wrong
    converged, reason = observer.evaluate_convergence(reported, expected, now)
    assert not converged
    assert "consistent" in reason


def test_evaluate_convergence_rejects_recent_change():
    expected = observer.expected_vectors(CONFIG)
    now = 1000.0
    reported = _reported_from(expected, now, age=0.1)  # changed within the last round
    converged, reason = observer.evaluate_convergence(reported, expected, now, gossip_interval=2)
    assert not converged
    assert "changed" in reason
