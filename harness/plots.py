"""Matplotlib rendering of experiment results (headless ``Agg`` backend).

Each function consumes the dict returned by the matching driver in
:mod:`harness.experiments` and writes a PNG. The headline figure is
:func:`plot_impact_vs_detectability`.
"""

import collections

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CURVE_STYLE = {
    "plausibility": {"color": "#1b9e77", "marker": "o", "label": "plausibility (hard bound)"},
    "cross_source": {"color": "#7570b3", "marker": "s", "label": "cross-source (statistical)"},
    "temporal":     {"color": "#d95f02", "marker": "^", "label": "temporal (flapping)"},
    "ensemble":     {"color": "#111111", "marker": "D", "label": "ensemble"},
}
ORDER = ["plausibility", "cross_source", "temporal", "ensemble"]


def _by_curve(rows):
    out = collections.defaultdict(list)
    for r in rows:
        out[r["curve"]].append(r)
    return out


def plot_impact_vs_detectability(result, path):
    """HEADLINE: x = steady-state impact, y = detection rate at fixed FPR.

    One curve per detector plus the ensemble. Points are ordered by attack
    intensity; the lower-left is the small-lie/low-impact regime and the
    upper-right is the gross-lie regime. The frontier shows the fundamental
    tension: to raise impact the attacker must lie harder, which makes it more
    detectable.
    """
    by = _by_curve(result["frontier"])
    fig, ax = plt.subplots(figsize=(8, 6))

    for curve in ORDER:
        rows = sorted(by.get(curve, []), key=lambda r: r["intensity"])
        if not rows:
            continue
        xs = [r["mean_impact"] for r in rows]
        ys = [r["detection_rate"] for r in rows]
        xerr = [r["impact_se"] for r in rows]
        yerr = [r["detection_se"] for r in rows]
        st = CURVE_STYLE[curve]
        ax.errorbar(xs, ys, xerr=xerr, yerr=yerr, fmt=st["marker"] + "-",
                    color=st["color"], label=st["label"], capsize=3,
                    markersize=6, linewidth=1.8, alpha=0.9)

    # annotate the ensemble curve with the intensity at each point
    ens = sorted(by.get("ensemble", []), key=lambda r: r["intensity"])
    for r in ens:
        ax.annotate(f"{r['intensity']:.2f}",
                    (r["mean_impact"], r["detection_rate"]),
                    textcoords="offset points", xytext=(6, -10), fontsize=8,
                    color="#555555")

    max_fpr = result.get("max_fpr", 0.05)
    params = result.get("params", {})
    ax.set_xlabel("Attacker impact  (fraction of honest traffic routed through attacker)")
    ax.set_ylabel(f"Detectability  (detection rate at honest FPR \u2264 {max_fpr:.0%})")
    ax.set_title("Impact vs. detectability frontier \u2014 FALSE_COST intensity sweep\n"
                 f"(n={params.get('n_nodes', '?')} nodes, {params.get('n_trials', '?')} topologies; "
                 "labels = lie intensity)")
    ax.set_ylim(-0.05, 1.05)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right", framealpha=0.95)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_detection_vs_intensity(result, path):
    by = _by_curve(result["frontier"])
    fig, ax = plt.subplots(figsize=(8, 5))
    for curve in ORDER:
        rows = sorted(by.get(curve, []), key=lambda r: r["intensity"])
        if not rows:
            continue
        xs = [r["intensity"] for r in rows]
        ys = [r["detection_rate"] for r in rows]
        yerr = [r["detection_se"] for r in rows]
        st = CURVE_STYLE[curve]
        ax.errorbar(xs, ys, yerr=yerr, fmt=st["marker"] + "-", color=st["color"],
                    label=st["label"], capsize=3, markersize=5)
    ax.set_xlabel("Lie intensity  (FALSE_COST shave fraction)")
    ax.set_ylabel(f"Detection rate at honest FPR \u2264 {result.get('max_fpr', 0.05):.0%}")
    ax.set_title("Per-detector coverage by lie magnitude")
    ax.set_ylim(-0.05, 1.05)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_impact_vs_intensity(result, path):
    rows = sorted(_by_curve(result["frontier"])["ensemble"], key=lambda r: r["intensity"])
    fig, ax = plt.subplots(figsize=(8, 5))
    xs = [r["intensity"] for r in rows]
    ys = [r["mean_impact"] for r in rows]
    yerr = [r["impact_se"] for r in rows]
    ax.errorbar(xs, ys, yerr=yerr, fmt="o-", color="#c0392b", capsize=3)
    ax.set_xlabel("Lie intensity  (FALSE_COST shave fraction)")
    ax.set_ylabel("Impact  (fraction of honest traffic hijacked)")
    ax.set_title("Attacker impact grows with lie intensity")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_collusion_recall(result, path):
    by = _by_curve(result["collusion"])
    fig, ax = plt.subplots(figsize=(8, 5))
    for curve in ORDER:
        rows = sorted(by.get(curve, []), key=lambda r: r["group_size"])
        if not rows:
            continue
        xs = [r["group_size"] for r in rows]
        ys = [r["recall"] for r in rows]
        yerr = [r["recall_se"] for r in rows]
        st = CURVE_STYLE[curve]
        # ensemble usually coincides with the single firing detector; dash it so
        # the underlying detector curve stays visible.
        line = st["marker"] + ("--" if curve == "ensemble" else "-")
        lw = 2.4 if curve == "ensemble" else 1.8
        ax.errorbar(xs, ys, yerr=yerr, fmt=line, color=st["color"],
                    label=st["label"], capsize=3, markersize=6, linewidth=lw, alpha=0.85)
    ax.set_xlabel("Colluding group size")
    ax.set_ylabel(f"Recall on colluders (FPR \u2264 {result.get('max_fpr', 0.05):.0%})")
    ax.set_title("Detection degrades as collusion grows \u2014 the Byzantine threshold")
    ax.set_ylim(-0.05, 1.05)
    sizes = sorted({r["group_size"] for r in result["collusion"]})
    ax.set_xticks(sizes)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_roc(result, path):
    auc_by_curve = {a["curve"]: a["auc"] for a in result["auc"]}
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.plot([0, 1], [0, 1], "--", color="#999999", linewidth=1, label="chance")
    for curve in ORDER:
        pts = result["roc"].get(curve)
        if not pts:
            continue
        xs = [p["fpr"] for p in pts]
        ys = [p["tpr"] for p in pts]
        st = CURVE_STYLE[curve]
        ax.plot(xs, ys, "-", color=st["color"],
                label=f"{st['label']} (AUC={auc_by_curve.get(curve, 0):.2f})", linewidth=1.8)
    intensity = result.get("params", {}).get("intensity", "?")
    ax.set_xlabel("False positive rate")
    ax.set_ylabel("True positive rate")
    ax.set_title(f"Detector ROC at lie intensity = {intensity}")
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_convergence_vs_size(result, path):
    rows = result["convergence"]
    fig, ax = plt.subplots(figsize=(8, 5))
    for sh, color, label, fmt in ((True, "#2980b9", "split horizon + poison reverse", "o-"),
                                  (False, "#e67e22", "naive (no split horizon)", "s--")):
        sub = sorted((r for r in rows if r["split_horizon"] == sh), key=lambda r: r["n_nodes"])
        xs = [r["n_nodes"] for r in sub]
        ys = [r["mean_rounds"] for r in sub]
        yerr = [r["rounds_se"] for r in sub]
        ax.errorbar(xs, ys, yerr=yerr, fmt=fmt, color=color, label=label, capsize=3,
                    linewidth=1.8, markersize=6, alpha=0.85)
    ax.set_xlabel("Network size (nodes)")
    ax.set_ylabel("Gossip rounds to global convergence")
    ax.set_title("Honest convergence time vs network size")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
