"""Benchmark harness entry point.

Runs the experiments with known ground truth and writes CSVs + plots to an
output directory (``results/`` by default). Everything is seed-reproducible.

Usage::

    python -m harness.run                 # full run (all experiments)
    python -m harness.run --quick         # fast smaller run for iteration
    python -m harness.run --only frontier # just the headline experiment
    python -m harness.run --out results --seed 1000
"""

import argparse
import csv
import json
import os
import time

from . import experiments, plots

EXPERIMENTS = ["frontier", "collusion", "roc", "convergence"]


def _write_csv(path, rows, fieldnames=None):
    if not rows:
        return
    if fieldnames is None:
        fieldnames = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _log(msg):
    print(f"[harness] {msg}", flush=True)


def run_frontier(outdir, cfg):
    _log("HEADLINE: attack-intensity sweep (impact vs detectability) ...")
    res = experiments.intensity_frontier(
        n_nodes=cfg["n_nodes"], n_trials=cfg["n_trials"],
        avg_degree=cfg["avg_degree"], max_fpr=cfg["max_fpr"], base_seed=cfg["seed"])
    _write_csv(os.path.join(outdir, "frontier.csv"), res["frontier"])
    _write_csv(os.path.join(outdir, "frontier_attacker_scores.csv"), res["attacker_scores"])
    _write_csv(os.path.join(outdir, "frontier_impact_raw.csv"), res["raw"])
    plots.plot_impact_vs_detectability(res, os.path.join(outdir, "impact_vs_detectability.png"))
    plots.plot_detection_vs_intensity(res, os.path.join(outdir, "detection_vs_intensity.png"))
    plots.plot_impact_vs_intensity(res, os.path.join(outdir, "impact_vs_intensity.png"))
    return {"thresholds": res["thresholds"], "params": res["params"]}


def run_collusion(outdir, cfg):
    _log("collusion sweep (Byzantine threshold) ...")
    res = experiments.collusion_sweep(
        n_trials=max(cfg["n_trials"], 12), max_fpr=cfg["max_fpr"],
        base_seed=cfg["seed"] + 1000)
    _write_csv(os.path.join(outdir, "collusion.csv"), res["collusion"])
    plots.plot_collusion_recall(res, os.path.join(outdir, "collusion_recall.png"))
    return {"thresholds": res["thresholds"]}


def run_roc(outdir, cfg):
    _log("ROC by detector ...")
    res = experiments.roc_experiment(
        intensity=cfg["roc_intensity"], n_nodes=cfg["n_nodes"],
        n_trials=max(cfg["n_trials"], 12), avg_degree=cfg["avg_degree"],
        base_seed=cfg["seed"] + 2000)
    roc_rows = []
    for curve, pts in res["roc"].items():
        for p in pts:
            roc_rows.append({"curve": curve, "fpr": p["fpr"], "tpr": p["tpr"]})
    _write_csv(os.path.join(outdir, "roc.csv"), roc_rows)
    _write_csv(os.path.join(outdir, "roc_auc.csv"), res["auc"])
    plots.plot_roc(res, os.path.join(outdir, "roc.png"))
    return {"auc": res["auc"]}


def run_convergence(outdir, cfg):
    _log("honest convergence vs network size ...")
    sizes = (10, 20, 30) if cfg["quick"] else (10, 20, 30, 50, 70, 100)
    res = experiments.convergence_vs_size(
        sizes=sizes, n_trials=cfg["n_trials"], avg_degree=cfg["avg_degree"],
        base_seed=cfg["seed"] + 3000)
    _write_csv(os.path.join(outdir, "convergence.csv"), res["convergence"])
    plots.plot_convergence_vs_size(res, os.path.join(outdir, "convergence_vs_size.png"))
    return {}


RUNNERS = {
    "frontier": run_frontier,
    "collusion": run_collusion,
    "roc": run_roc,
    "convergence": run_convergence,
}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Mesh adversarial-routing benchmark harness")
    parser.add_argument("--out", default="results", help="output directory")
    parser.add_argument("--seed", type=int, default=1000, help="base RNG seed")
    parser.add_argument("--quick", action="store_true",
                        help="smaller/faster run for iteration")
    parser.add_argument("--only", nargs="+", choices=EXPERIMENTS,
                        help="run only these experiments (default: all)")
    parser.add_argument("--n-nodes", type=int, default=None)
    parser.add_argument("--n-trials", type=int, default=None)
    parser.add_argument("--avg-degree", type=float, default=4.0)
    parser.add_argument("--max-fpr", type=float, default=0.05)
    parser.add_argument("--roc-intensity", type=float, default=0.5)
    args = parser.parse_args(argv)

    cfg = {
        "n_nodes": args.n_nodes or (25 if args.quick else 40),
        "n_trials": args.n_trials or (5 if args.quick else 15),
        "avg_degree": args.avg_degree,
        "max_fpr": args.max_fpr,
        "roc_intensity": args.roc_intensity,
        "seed": args.seed,
        "quick": args.quick,
    }

    os.makedirs(args.out, exist_ok=True)
    selected = args.only or EXPERIMENTS

    started = time.time()
    summary = {"config": cfg, "experiments": {}}
    for name in selected:
        t0 = time.time()
        summary["experiments"][name] = RUNNERS[name](args.out, cfg)
        _log(f"  {name} done in {time.time() - t0:.1f}s")

    summary["elapsed_s"] = round(time.time() - started, 1)
    with open(os.path.join(args.out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)
    _log(f"all done in {summary['elapsed_s']}s -> {args.out}/")


if __name__ == "__main__":
    main()
