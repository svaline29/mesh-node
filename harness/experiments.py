"""Experiment drivers: each returns plain data structures (lists of dict rows)
that :mod:`harness.run` writes to CSV and :mod:`harness.plots` renders.

Measurement conventions (shared by every attack experiment):

* **Warmup, then attack.** Each trial first runs the honest network to
  convergence; the attack is then activated at ``onset = honest_converged + 1``.
* **Impact is measured at the post-attack steady state** -- the fraction of
  honest src->dst demand whose converged route passes through the attacker
  (:func:`harness.metrics.passthrough_share`).
* **Detectability is measured at attack onset** -- the round the lie first
  appears, before the false routes propagate. This is the moment of maximal
  cross-source contrast and the lowest-latency detection point. At steady state a
  gross lie homogenizes the neighborhood and is no longer a local outlier, so
  onset is the honest place to ask "can this be caught?".
* **Thresholds are calibrated on honest scores only** (a per-detector threshold
  holding honest FPR <= ``max_fpr``), reused unchanged across every intensity.
  No detector constant is fit to the attacks; the threshold is the single swept
  knob.
"""

import statistics

import attacks
import detectors
from . import simulator, scenarios, metrics

DETECTOR_NAMES = ["plausibility", "cross_source", "temporal"]
ALL_CURVES = DETECTOR_NAMES + ["ensemble"]


# --------------------------------------------------------------------------- #
# Small numeric helpers (kept dependency-free; numpy is only used for plots).
# --------------------------------------------------------------------------- #

def _percentile(values, q):
    """Linear-interpolation percentile, ``q`` in [0, 100]."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * q / 100.0
    lo = int(pos)
    frac = pos - lo
    if lo + 1 >= len(s):
        return s[-1]
    return s[lo] + frac * (s[lo + 1] - s[lo])


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _stderr(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    return statistics.pstdev(xs) / (n ** 0.5)


def _bin_stderr(p, n):
    """Standard error of a proportion ``p`` from ``n`` Bernoulli trials."""
    if n == 0:
        return 0.0
    return (p * (1.0 - p) / n) ** 0.5


# --------------------------------------------------------------------------- #
# Per-trial primitive: run one attacked scenario and score it at onset.
# --------------------------------------------------------------------------- #

def _run_scenario(topo, attacker_map, attacker_ids, split_horizon=True, margin=40):
    """Run warmup->attack and return ``(impact, onset_scores, honest_nodes)``.

    ``onset_scores`` is ``{detector_name: {node: raw_score}}`` evaluated at the
    onset snapshot. ``impact`` is the steady-state passthrough share.
    """
    honest = simulator.simulate(topo, {}, split_horizon=split_horizon)
    onset = (honest.converged_round or 1) + 1

    # re-gate every attacker to start at the shared onset round
    for atk in attacker_map.values():
        atk.start_round = onset

    result = simulator.simulate(
        topo, attacker_map, split_horizon=split_horizon,
        max_rounds=onset + margin, min_rounds=onset + 1, stop_when_stable=True)

    impact = metrics.passthrough_share(result.tables, attacker_ids)
    onset_obs = result.observations(up_to_round=onset)
    analysis = detectors.analyze(onset_obs)
    onset_scores = analysis["per_detector"]  # {name: {node: raw_score}}
    return impact, onset_scores, list(result.honest_nodes())


# --------------------------------------------------------------------------- #
# Threshold calibration + detection scoring shared across experiments.
# --------------------------------------------------------------------------- #

def _ensemble_scales(records):
    """Honest-only per-detector scales used to build a comparable ensemble.

    scale_d = 95th percentile of honest raw scores for detector d (>=1e-9).
    Calibrated on honest nodes only, so it leaks no attack labels.
    """
    scales = {}
    for name in DETECTOR_NAMES:
        honest_vals = [r["scores"][name] for r in records if not r["is_attacker"]]
        p95 = _percentile(honest_vals, 95.0)
        scales[name] = p95 if p95 > 1e-9 else 1.0
    return scales


def _ensemble_score(score_by_det, scales):
    return _mean([score_by_det[name] / scales[name] for name in DETECTOR_NAMES])


def _calibrate_thresholds(records, scales, max_fpr):
    """One threshold per curve, holding honest FPR <= ``max_fpr`` over all records."""
    thresholds = {}
    for name in DETECTOR_NAMES:
        honest = [r["scores"][name] for r in records if not r["is_attacker"]]
        thresholds[name] = metrics.operating_threshold(honest, max_fpr)
    honest_ens = [_ensemble_score(r["scores"], scales) for r in records if not r["is_attacker"]]
    thresholds["ensemble"] = metrics.operating_threshold(honest_ens, max_fpr)
    return thresholds


def _detected(record, curve, scales, thresholds):
    """Was the attacker in this record flagged by ``curve`` at the operating point?"""
    if curve == "ensemble":
        s = _ensemble_score(record["scores"], scales)
    else:
        s = record["scores"][curve]
    return s > thresholds[curve]


# --------------------------------------------------------------------------- #
# HEADLINE: attack-intensity sweep -> impact vs detectability frontier.
# --------------------------------------------------------------------------- #

def intensity_frontier(intensities=None, n_nodes=40, n_trials=12, base_seed=1000,
                       avg_degree=4.0, split_horizon=True, max_fpr=0.05):
    """Sweep FALSE_COST lie magnitude; measure impact and detectability.

    For each intensity (``shave_fraction``: 0 = honest, 1 = zero-cost blackhole),
    over ``n_trials`` random topologies, record the attacker's steady-state impact
    and its onset suspicion under every detector. Returns a dict with:

    * ``"frontier"``: per (curve, intensity) rows with mean impact and detection
      rate (+ standard errors) -- the headline plot data.
    * ``"attacker_scores"``: per (curve, intensity) mean normalized attacker score.
    * ``"raw"``: per (intensity, trial) impact, for auditing.
    * ``"thresholds"``, ``"max_fpr"``: the calibrated operating points.
    """
    if intensities is None:
        intensities = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.65, 0.8, 1.0]

    records = []   # one per (intensity, trial, node)
    raw_rows = []  # one per (intensity, trial): impact
    impacts = {i: [] for i in intensities}

    for trial in range(n_trials):
        seed = base_seed + trial
        topo = scenarios.random_connected_topology(n_nodes, seed=seed, avg_degree=avg_degree)
        attacker = scenarios.pick_central_node(topo)

        for intensity in intensities:
            atk = {attacker: scenarios.false_cost_attacker(attacker, shave_fraction=intensity)}
            impact, onset_scores, honest_nodes = _run_scenario(
                topo, atk, {attacker}, split_horizon=split_horizon)

            impacts[intensity].append(impact)
            raw_rows.append({"intensity": intensity, "trial": trial,
                             "attacker": attacker, "impact": impact})

            scored_nodes = set()
            for name in DETECTOR_NAMES:
                scored_nodes.update(onset_scores[name])
            for node in scored_nodes:
                records.append({
                    "intensity": intensity, "trial": trial, "node": node,
                    "is_attacker": node == attacker,
                    "scores": {name: onset_scores[name].get(node, 0.0) for name in DETECTOR_NAMES},
                })

    scales = _ensemble_scales(records)
    thresholds = _calibrate_thresholds(records, scales, max_fpr)

    # detection per (curve, intensity): one Bernoulli outcome per trial (the
    # attacker record for that intensity+trial).
    frontier = []
    attacker_score_rows = []
    for curve in ALL_CURVES:
        for intensity in intensities:
            attacker_records = [r for r in records
                                if r["is_attacker"] and r["intensity"] == intensity]
            detected = [1.0 if _detected(r, curve, scales, thresholds) else 0.0
                        for r in attacker_records]
            det_rate = _mean(detected)
            mean_impact = _mean(impacts[intensity])
            frontier.append({
                "curve": curve,
                "intensity": intensity,
                "mean_impact": mean_impact,
                "impact_se": _stderr(impacts[intensity]),
                "detection_rate": det_rate,
                "detection_se": _bin_stderr(det_rate, len(detected)),
                "n_trials": len(detected),
            })
            if curve == "ensemble":
                scores = [_ensemble_score(r["scores"], scales) for r in attacker_records]
            else:
                scores = [r["scores"][curve] for r in attacker_records]
            attacker_score_rows.append({
                "curve": curve, "intensity": intensity,
                "mean_attacker_score": _mean(scores),
            })

    return {
        "frontier": frontier,
        "attacker_scores": attacker_score_rows,
        "raw": raw_rows,
        "thresholds": thresholds,
        "max_fpr": max_fpr,
        "params": {"n_nodes": n_nodes, "n_trials": n_trials, "avg_degree": avg_degree,
                   "split_horizon": split_horizon, "intensities": intensities},
    }


# --------------------------------------------------------------------------- #
# Collusion sweep -> Byzantine threshold story.
# --------------------------------------------------------------------------- #

def collusion_sweep(group_sizes=(1, 2, 3), n_trials=12, base_seed=2000,
                    split_horizon=True, max_fpr=0.05):
    """Measure how detection degrades as the colluding group grows.

    Uses the controlled :func:`harness.scenarios.collusion_demo` gadget: a central
    honest observer with ``k`` colluders and ``m`` honest witnesses among its
    neighbors. The colluders advertise the same plausible undercut to shared
    targets, manufacturing a fake consensus that drags the leave-one-out median
    toward the lie once they reach a local majority. The undercut is sized to stay
    above the geometric plausibility bound, so only the cross-source detector
    could catch it -- and collusion is precisely what defeats it.

    Reports per-detector recall (fraction of colluders flagged) vs group size.
    """
    # Detection is measured AT the central honest observer H, against H's own
    # honest witnesses. This isolates the leave-one-out-median mechanism that
    # collusion attacks (a colluder's reference excludes itself but still includes
    # the other colluders) without the structural cross-source false positives
    # that global aggregation suffers (a node is always its own cheapest source).
    records = []  # per (size, trial, neighbor-of-H)

    for trial in range(n_trials):
        seed = base_seed + trial
        for size in group_sizes:
            topo, group, targets, false_cost = scenarios.collusion_demo(size, seed=seed)
            attacker_map = {
                node: attacks.Attacker(node, [attacks.FalseCost(cost=false_cost, targets=targets)])
                for node in group
            }
            honest = simulator.simulate(topo, {}, split_horizon=split_horizon)
            onset = (honest.converged_round or 1) + 1
            for atk in attacker_map.values():
                atk.start_round = onset
            result = simulator.simulate(topo, attacker_map, split_horizon=split_horizon,
                                        max_rounds=onset + 40, min_rounds=onset + 1)
            obs_H = result.observation("H")  # the observer whose median collusion corrupts
            per_det = {name: det.score(obs_H)
                       for name, det in zip(DETECTOR_NAMES, detectors.default_detectors())}
            group_set = set(group)
            for neighbor in obs_H.neighbors():
                records.append({
                    "size": size, "trial": trial, "node": neighbor,
                    "is_attacker": neighbor in group_set,
                    "scores": {name: per_det[name].get(neighbor, 0.0) for name in DETECTOR_NAMES},
                })

    scales = _ensemble_scales(records)
    thresholds = _calibrate_thresholds(records, scales, max_fpr)

    rows = []
    for curve in ALL_CURVES:
        for size in group_sizes:
            attacker_records = [r for r in records if r["is_attacker"] and r["size"] == size]
            flags = [1.0 if _detected(r, curve, scales, thresholds) else 0.0
                     for r in attacker_records]
            recall = _mean(flags)
            if curve == "ensemble":
                scores = [_ensemble_score(r["scores"], scales) for r in attacker_records]
            else:
                scores = [r["scores"][curve] for r in attacker_records]
            rows.append({
                "curve": curve, "group_size": size,
                "recall": recall, "recall_se": _bin_stderr(recall, len(flags)),
                "mean_colluder_score": _mean(scores),
                "n_attacker_instances": len(flags),
            })
    return {"collusion": rows, "thresholds": thresholds, "max_fpr": max_fpr,
            "params": {"n_trials": n_trials, "group_sizes": list(group_sizes)}}


# --------------------------------------------------------------------------- #
# ROC / PR by detector at a representative intensity.
# --------------------------------------------------------------------------- #

def roc_experiment(intensity=0.5, n_nodes=40, n_trials=20, base_seed=3000,
                   avg_degree=4.0, split_horizon=True):
    """Per-detector ROC by pooling onset scores across trials at one intensity."""
    records = []
    for trial in range(n_trials):
        seed = base_seed + trial
        topo = scenarios.random_connected_topology(n_nodes, seed=seed, avg_degree=avg_degree)
        attacker = scenarios.pick_central_node(topo)
        atk = {attacker: scenarios.false_cost_attacker(attacker, shave_fraction=intensity)}
        _, onset_scores, _ = _run_scenario(topo, atk, {attacker}, split_horizon=split_horizon)

        scored_nodes = set()
        for name in DETECTOR_NAMES:
            scored_nodes.update(onset_scores[name])
        for node in scored_nodes:
            records.append({
                "is_attacker": node == attacker,
                "scores": {name: onset_scores[name].get(node, 0.0) for name in DETECTOR_NAMES},
            })

    scales = _ensemble_scales(records)
    curves = {}
    aucs = []
    for curve in ALL_CURVES:
        if curve == "ensemble":
            labeled = [(_ensemble_score(r["scores"], scales), r["is_attacker"]) for r in records]
        else:
            labeled = [(r["scores"][curve], r["is_attacker"]) for r in records]
        pts = metrics.roc_curve(labeled)
        curves[curve] = [{"fpr": fpr, "tpr": tpr} for fpr, tpr, _ in pts]
        aucs.append({"curve": curve, "auc": metrics.auc(pts), "intensity": intensity})
    return {"roc": curves, "auc": aucs,
            "params": {"intensity": intensity, "n_nodes": n_nodes, "n_trials": n_trials}}


# --------------------------------------------------------------------------- #
# Honest convergence time vs network size.
# --------------------------------------------------------------------------- #

def convergence_vs_size(sizes=(10, 20, 30, 50, 70, 100), n_trials=8, base_seed=4000,
                        avg_degree=4.0):
    """Rounds to global convergence vs network size, split horizon on vs off."""
    rows = []
    for n in sizes:
        for sh in (True, False):
            rounds = []
            for trial in range(n_trials):
                topo = scenarios.random_connected_topology(
                    n, seed=base_seed + trial, avg_degree=avg_degree)
                result = simulator.simulate(topo, {}, split_horizon=sh,
                                            max_rounds=8 * n, stop_when_stable=True)
                rounds.append(result.converged_round if result.converged_round else 8 * n)
            rows.append({
                "n_nodes": n, "split_horizon": sh,
                "mean_rounds": _mean(rounds), "rounds_se": _stderr(rounds),
            })
    return {"convergence": rows, "params": {"sizes": list(sizes), "n_trials": n_trials}}
