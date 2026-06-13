"""Unit tests for the composable attack modules (UDP-free)."""

import attacks
from attacks.base import AttackContext


def ctx(recipient="C", round=5, node_id="F"):
    return AttackContext(node_id=node_id, recipient=recipient, round=round)


HONEST = {"A": 6, "E": 8, "J": 3, "F": 0}


def test_false_cost_lowers_targeted_destinations():
    atk = attacks.FalseCost(cost=0, targets=["A", "J"])
    ad = atk.apply(HONEST, ctx())
    assert ad["A"] == 0
    assert ad["J"] == 0
    assert ad["E"] == 8          # untargeted destination untouched
    assert ad["F"] == 0          # self route preserved


def test_false_cost_can_advertise_unreachable_destination():
    # Claiming a cheap route to a destination we do not currently carry.
    atk = attacks.FalseCost(cost=1, targets=["Q"])
    ad = atk.apply(HONEST, ctx())
    assert ad["Q"] == 1


def test_false_cost_all_destinations_when_no_targets():
    atk = attacks.FalseCost(cost=0)
    ad = atk.apply(HONEST, ctx())
    assert ad["A"] == 0 and ad["E"] == 0 and ad["J"] == 0
    assert ad["F"] == 0  # self stays 0 (skipped, but already 0)


def test_false_cost_never_lies_about_self():
    atk = attacks.FalseCost(cost=99, targets=["F"])
    ad = atk.apply(HONEST, ctx())
    assert ad["F"] == 0


def test_false_topology_injects_phantom_destinations():
    atk = attacks.FalseTopology(fake={"Z9": 1, "Z8": 2})
    ad = atk.apply(HONEST, ctx())
    assert ad["Z9"] == 1 and ad["Z8"] == 2
    assert ad["A"] == 6  # real entries preserved


def test_flapping_alternates_with_round():
    atk = attacks.Flapping(targets=["J"], low=1, high=99, period=1)
    assert atk.apply(HONEST, ctx(round=0))["J"] == 1
    assert atk.apply(HONEST, ctx(round=1))["J"] == 99
    assert atk.apply(HONEST, ctx(round=2))["J"] == 1


def test_flapping_respects_period():
    atk = attacks.Flapping(targets=["J"], low=1, high=99, period=2)
    assert atk.apply(HONEST, ctx(round=0))["J"] == 1
    assert atk.apply(HONEST, ctx(round=1))["J"] == 1
    assert atk.apply(HONEST, ctx(round=2))["J"] == 99
    assert atk.apply(HONEST, ctx(round=3))["J"] == 99


def test_selective_lies_only_to_victims():
    inner = [attacks.FalseCost(cost=0, targets=["A"])]
    atk = attacks.Selective(victims=["C"], inner=inner)
    lied = atk.apply(HONEST, ctx(recipient="C"))
    honest = atk.apply(HONEST, ctx(recipient="G"))
    assert lied["A"] == 0
    assert honest["A"] == 6        # untouched for non-victim
    assert honest == HONEST


def test_attacker_gates_on_start_round():
    chain = [attacks.FalseCost(cost=0, targets=["A"])]
    attacker = attacks.Attacker("F", chain, start_round=3)
    before = attacker.transform(HONEST, ctx(round=2))
    after = attacker.transform(HONEST, ctx(round=3))
    assert before["A"] == 6        # not yet active -> honest
    assert after["A"] == 0         # active -> lying


def test_attacker_chain_composes_modes():
    chain = [
        attacks.FalseCost(cost=0, targets=["A"]),
        attacks.FalseTopology(fake={"Z9": 1}),
    ]
    attacker = attacks.Attacker("F", chain, start_round=0)
    ad = attacker.transform(HONEST, ctx(round=0))
    assert ad["A"] == 0 and ad["Z9"] == 1


def test_from_config_builds_attacker_and_honest_nodes_are_none():
    config = {
        "attackers": {
            "F": {
                "start_round": 2,
                "modes": [
                    {"type": "SELECTIVE", "victims": ["C"], "inner": [
                        {"type": "FALSE_COST", "targets": ["A"], "cost": 0}
                    ]}
                ],
            }
        }
    }
    attacker = attacks.from_config(config, "F")
    assert attacker is not None
    assert attacker.start_round == 2
    # F lies to C but not G, and only once active.
    assert attacker.transform(HONEST, ctx(recipient="C", round=2))["A"] == 0
    assert attacker.transform(HONEST, ctx(recipient="G", round=2))["A"] == 6
    assert attacker.transform(HONEST, ctx(recipient="C", round=1))["A"] == 6

    assert attacks.from_config(config, "G") is None


def test_unknown_attack_type_raises():
    import pytest
    with pytest.raises(ValueError):
        attacks.build_attack({"type": "BOGUS"})
