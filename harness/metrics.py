"""Measurement primitives: attacker impact and detection quality.

All functions are pure and unit-tested on hand-checkable cases. Detection uses a
strict-greater decision rule (``score > threshold``) consistently, so the ROC
curve and the fixed-FPR operating point agree.
"""


# --------------------------------------------------------------------------- #
# Attacker impact: how much traffic is routed through the adversary.
# --------------------------------------------------------------------------- #

def trace_path(tables, src, dst, max_hops=None):
    """Follow next-hops from ``src`` toward ``dst`` using the converged tables.

    Returns ``(path, reached)`` where ``path`` is the ordered list of nodes
    visited (including ``src``) and ``reached`` is whether ``dst`` was reached.
    A routing loop or a missing route terminates the trace with ``reached=False``
    (the packet is effectively captured/dropped en route -- which still counts as
    the adversary disrupting that flow if the adversary is on the path).
    """
    if max_hops is None:
        max_hops = len(tables) + 1
    path = [src]
    seen = {src}
    cur = src
    for _ in range(max_hops):
        if cur == dst:
            return path, True
        entry = tables.get(cur, {}).get(dst)
        if entry is None:
            return path, False  # no route
        nxt = entry["next_hop"]
        if nxt == cur:
            return path, (cur == dst)  # self next-hop but not destination -> stuck
        cur = nxt
        if cur in seen:
            path.append(cur)
            return path, False  # loop
        seen.add(cur)
        path.append(cur)
    return path, cur == dst


def passthrough_share(tables, attacker_ids, honest_nodes=None):
    """Fraction of ordered honest src->dst pairs whose route touches an attacker.

    This is the impact axis of the headline frontier: the share of (uniform)
    network demand the adversary attracts/hijacks. An attacker counts as "on the
    path" whether traffic flows cleanly through it or is trapped in an
    attacker-induced loop/blackhole.
    """
    attacker_ids = set(attacker_ids)
    if honest_nodes is None:
        honest_nodes = [n for n in tables if n not in attacker_ids]
    honest_nodes = list(honest_nodes)

    total = 0
    hijacked = 0
    for src in honest_nodes:
        for dst in honest_nodes:
            if src == dst:
                continue
            total += 1
            path, _ = trace_path(tables, src, dst)
            if attacker_ids.intersection(path):
                hijacked += 1
    return hijacked / total if total else 0.0


# --------------------------------------------------------------------------- #
# Detection quality.
# --------------------------------------------------------------------------- #

def roc_curve(score_labels):
    """ROC points from ``[(score, is_attacker_bool), ...]``.

    Returns a list of ``(fpr, tpr, threshold)`` sorted by fpr then tpr, using the
    strict-greater decision rule. Includes the (1,1) and (0,0) endpoints.
    """
    positives = sum(1 for _, lab in score_labels if lab)
    negatives = len(score_labels) - positives
    scores = sorted({s for s, _ in score_labels})
    if not scores:
        return [(0.0, 0.0, 0.0), (1.0, 1.0, 0.0)]

    candidates = [scores[0] - 1.0] + scores  # below-min threshold flags everyone
    points = []
    for tau in candidates:
        tp = sum(1 for s, lab in score_labels if lab and s > tau)
        fp = sum(1 for s, lab in score_labels if (not lab) and s > tau)
        fpr = fp / negatives if negatives else 0.0
        tpr = tp / positives if positives else 0.0
        points.append((fpr, tpr, tau))
    points.append((0.0, 0.0, scores[-1]))
    return sorted(points)


def auc(roc_points):
    """Area under an ROC curve (trapezoidal) from :func:`roc_curve` output."""
    xy = sorted((fpr, tpr) for fpr, tpr, _ in roc_points)
    area = 0.0
    for (x0, y0), (x1, y1) in zip(xy, xy[1:]):
        area += (x1 - x0) * (y0 + y1) / 2.0
    return area


def operating_threshold(honest_scores, max_fpr=0.05):
    """Threshold holding the honest false-positive rate at or below ``max_fpr``.

    Calibrated *only* on honest-node scores (no attack labels), so it introduces
    no train/test leakage: the same threshold is reused across every attack
    intensity. Decision rule is ``score > threshold``.
    """
    scores = sorted(honest_scores)
    n = len(scores)
    if n == 0:
        return 0.0
    allowed = int(max_fpr * n)  # honest scores permitted above the threshold
    idx = max(0, min(n - 1, n - 1 - allowed))
    return scores[idx]


def detection_rate(attacker_scores, threshold):
    """Fraction of attacker scores strictly above ``threshold``."""
    if not attacker_scores:
        return 0.0
    return sum(1 for s in attacker_scores if s > threshold) / len(attacker_scores)


def classification_metrics(node_scores, attacker_ids, threshold):
    """Precision / recall / TPR / FPR for one labeled set at a threshold."""
    attacker_ids = set(attacker_ids)
    flagged = {n for n, s in node_scores.items() if s > threshold}
    honest = set(node_scores) - attacker_ids

    tp = len(flagged & attacker_ids)
    fp = len(flagged & honest)
    fn = len(attacker_ids - flagged)
    tn = len(honest - flagged)

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "tpr": recall,
        "fpr": fpr,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }
