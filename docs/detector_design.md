# Detector design note (Phase 3)

This note specifies the anomaly detectors **before** any of them are
implemented. Please review; I will not write detection code until this is
approved.

## What every detector is and is not allowed to see

A detector is a **pure function of the data an honest node already has at
runtime**, namely:

- `link_costs`: the **observer's own** trusted link cost to each of its direct
  neighbors (this is local ground truth — the node configured these itself).
- `history`: for each direct neighbor `n`, the time-series of distance vectors
  `adv_n^(t) = {dest: cost}` that `n` has gossiped to the observer, across gossip
  rounds `t`.

Detectors **must not** reference, import, or branch on: the `attackers` config,
any specific node ID, collusion groups, or which attack mode is active. They
receive only `(link_costs, history)` and the set of destinations seen. The same
inputs are available in the live node (`neighbor_vectors` + `link_costs`) and in
the offline harness, so identical code runs in both.

### Vantage point and attribution (why we score direct neighbors)

An adversary manipulates **its own outgoing advertisement**. Therefore the
inconsistency always appears in the vector attributed to the adversary itself,
and is observed by the adversary's **honest direct neighbors**. So each detector,
running at observer `H`, produces a suspicion score over `H`'s direct neighbors
(the only sources `H` can name). The harness then aggregates per-observer scores
into a **global per-node score** (default: mean over the honest observers that
neighbor that node; `max` is the "flagged by anyone" alternative).

Consequence to state honestly: a node can only be detected if it has **at least
one honest neighbor**. A node all of whose neighbors are itself/colluders is
unobservable by construction.

### Notation

- `link(n)` = observer's trusted link cost to neighbor `n`.
- `adv_n(D)` = cost neighbor `n` currently advertises to destination `D`.
- `P_n(D) = link(n) + adv_n(D)` = cost the observer would pay to reach `D` via `n`.

---

## Detector 1 — Plausibility bounds (hard, geometric)

**(a) Invariant.** In an honest network, advertised costs equal true shortest-path
distances, which obey the triangle inequality. Anchoring on the observer's own
trusted links, for any two neighbors `n, m` and any destination `D`:

```
adv_n(D) >= adv_m(D) - d(n, m) >= adv_m(D) - (link(n) + link(m))
```

The last step replaces the unknown `d(n,m)` with the sound upper bound
`link(n)+link(m)` (the detour through the observer). An honest node **never**
violates this, so it is a hard bound with no static false positives.

**(b) Suspicion score.** For neighbor `n`, define the greatest lower bound on what
`n` could honestly advertise to `D`:

```
B_n(D) = max over m != n of ( adv_m(D) - link(n) - link(m) )

plausibility(n) = mean over D of  max(0, B_n(D) - adv_n(D))
```

i.e. the average provable "deficit" by which `n` undercuts geometry. One-sided
on purpose: it targets nodes that advertise **implausibly low** costs (the
traffic-attracting / blackhole direction).

**(c) Should / should not catch.**
- *Should:* `FALSE_COST` and `COLLUSION` lies that dip below the geometric bound
  **while at least one honest neighbor still advertises the true higher cost to
  that destination**; `FALSE_TOPOLOGY` only when the phantom destination is also
  advertised honestly by someone else.
- *Should not:* `FLAPPING` (instantaneous values are often individually within
  bounds), `SELECTIVE` toward non-victims (the observer correctly sees honesty),
  phantom destinations that **no** honest neighbor advertises (no reference `m`).

**(d) Expected failure mode — and the experiment it motivates.** The bound is
loose (`link(n)+link(m)` overestimates `d(n,m)`), so a lie smaller than the slack
slips under it. This is **not a flaw to apologize for — it is the reason
Detector 2 exists**, and we measure it rather than assert it:

- The plausibility detector catches **gross** lies at **zero static
  false-positive rate** (it is a sound bound).
- Its **miss-rate as a function of lie magnitude** is the lower edge of the
  impact-vs-detectability frontier: below the geometric slack, only the
  statistical detector can catch the lie, and only at some false-positive cost.

**Harness requirement (Phase 4):** sweep lie magnitude (e.g. advertise a target
at true_cost − δ for a range of δ) and plot **per-detector** detection vs δ, so
the handoff is explicit: "hard bound covers δ above the slack at 0 FP; the
statistical detector extends coverage to small δ at some FP." The harness must
therefore be able to score and report each detector **in isolation**, not only
the ensemble.

It is also defeated by **collusion**: if the reference-maximizing neighbor `m` is
itself an accomplice lying low, `B_n(D)` collapses and the violation disappears.
Requires ≥2 neighbors sharing a destination.

---

## Detector 2 — Cross-source consistency (soft, statistical)

**(a) Invariant.** Neighbors that are all adjacent to the observer have comparable
access to the rest of the network, so the path costs `P_n(D)` should **cluster**;
no single source should be a persistent, large, unilateral low-outlier across
many destinations. (Soft consensus, in contrast to Detector 1's hard bound.)

**(b) Suspicion score.** The reference distribution for scoring `n` is computed
**with `n` removed** — a leave-one-out (LOO) median:

```
consensus_{-n}(D) = median over m != n of P_m(D)     # n excluded from its own baseline

cross_source(n) = mean over D of  max(0, consensus_{-n}(D) - P_n(D))
```

plus an *uncorroborated-destination* term: any `D` advertised by `n` alone (no
other neighbor offers `D`) contributes `adv_n(D)`-weighted suspicion, since there
is no second source to corroborate it. Lying low across many destinations (a
blackhole) yields a large, broad score.

*Why LOO, and why median (the interview answer).* The reference distribution
must be robust to the attacker influencing it. If the node under evaluation were
included in its own baseline, a single aggressive liar would drag the baseline
toward itself and partially mask its own deviation — the bug that makes detection
look better or worse than reality. Excluding `n` (LOO) denies the attacker any
vote in its own reference. Using the **median** (rather than the mean) over the
remaining witnesses adds a second layer: it tolerates up to ~50% of the *other*
witnesses being corrupt before the reference itself is compromised, which is also
exactly why collusion (a corrupt majority of witnesses) is the documented
breaking point. A trimmed mean is an acceptable equivalent. **This LOO-median is a
correctness requirement of the implementation, not just prose: a unit test will
assert that a lone liar cannot lower its own reference (i.e. scoring with vs.
without LOO differs, and the LOO score is the larger/correct one).**

**(c) Should / should not catch.**
- *Should:* `FALSE_COST` / blackhole (the canonical low-outlier), `FALSE_TOPOLOGY`
  (phantom destinations are uncorroborated), `SELECTIVE` **when the observer is a
  victim and has another honest neighbor** to compare against.
- *Should not — by design:* `COLLUSION`. When ≥2 of the compared sources collude
  and agree, they *become* (or shift) the consensus, so the low-outlier signal
  vanishes. This is precisely the detector we expect collusion to defeat, and the
  harness will quantify the degradation across group size 1→2→3.

**(d) Expected failure mode.** Collusion (fabricated consensus); needs ≥3 sources
for a meaningful leave-one-out median (with 2 neighbors there is no majority);
soft threshold can false-positive when honest topology genuinely gives one
neighbor much cheaper access (legitimate asymmetry).

---

## Detector 3 — Temporal stability (dynamics)

**(a) Invariant.** With bounded network churn, honest advertised costs are
piecewise-constant: a value changes only when the topology changes and then
re-settles. A node should not induce far more / more violent changes than the
observed network-wide churn justifies.

**(b) Suspicion score.** Over a sliding window of the last `W` rounds, count
**direction reversals** of `adv_n(D)` (up-then-down or down-then-up), which
distinguish oscillation from a one-time step:

```
baseline(D) = median over m of reversals_m(D, W)

temporal(n) = mean over D of  max(0, reversals_n(D, W) - baseline(D))
```

Subtracting the per-destination baseline prevents genuine churn that affects
everyone from implicating a single node. A period-`p` flapper produces ≈ `W/p`
reversals, far above baseline.

**(c) Should / should not catch.**
- *Should:* `FLAPPING` (its whole purpose).
- *Should not:* static `FALSE_COST`, `FALSE_TOPOLOGY`, `SELECTIVE`, or
  `COLLUSION` (a constant lie has zero reversals → invisible here, correctly left
  to Detectors 1/2); a one-time legitimate convergence/join/leave transient (a
  single step, not an oscillation).

**(d) Expected failure mode.** A slow flapper whose period is comparable to
legitimate churn hides in the baseline; a constant-value liar is invisible; high
genuine churn raises the baseline and masks flapping. `W` is a tradeoff: too
short misses slow flaps, too long increases detection latency.

---

## Ensemble

Each detector is normalized across the candidate nodes in a run (z-score or
min-max) and combined:

```
suspicion(n) = w1 * plausibility_norm(n)
             + w2 * cross_source_norm(n)
             + w3 * temporal_norm(n)
```

Default weights equal; tunable. The three component scores are also reported
individually so the harness can measure each detector's marginal contribution.
Output is a **continuous score** (never a binary), so the harness can sweep a
threshold and produce ROC / precision–recall curves. Global per-node suspicion is
the aggregate of `suspicion(n)` over the honest observers that neighbor `n`.

## Coverage closure (the clean claim)

The division of labor is designed to leave exactly one documented gap:

- **Cost-lowering lies** (`FALSE_COST`, the cost-lowering part of `SELECTIVE`):
  gross → Detector 1; subtle → Detector 2 (with nonzero score down to arbitrarily
  small δ, detectability set by threshold per the magnitude sweep above).
- **Phantom destinations/links** (`FALSE_TOPOLOGY`): uncorroborated-destination
  term in Detector 2.
- **Oscillation** (`FLAPPING`): Detector 3.
- **Selective lies**: caught by whichever of 1/2 applies, *provided the observer
  is a victim and has another honest neighbor* — otherwise the lie isn't visible
  to that observer at all (correct: there is nothing to detect locally).

Checking for an attack that falls between all three — a lie that is
simultaneously **constant** (evades Detector 3), **geometrically legal** (evades
Detector 1's bound), **and well-corroborated** (evades Detector 2's consensus):
to be well-corroborated the lie must agree with the LOO consensus of the *other*
witnesses, which requires those other witnesses to back it — i.e. **collusion**.
A *single* liar cannot simultaneously deviate enough to perturb routing and match
a consensus computed with itself excluded; any routing-perturbing deviation
yields a positive cross-source score.

**Claim we will defend:** *every non-colluding lie that perturbs routing produces
a positive score in at least one detector; the only undetected attack classes are
(i) collusion — a corrupt majority of a victim's witnesses — and (ii) a liar with
no honest neighbor to observe it.* Both are structural Byzantine limits, stated
deliberately, not accidents. The harness will verify (i) by showing cross-source
recall collapsing as collusion grows 1→2→3.

## Parameters and the no-test-set-tuning guarantee

To avoid re-introducing hardcoding "through the back door," the detectors have
**no free parameters fit to the attack scenarios**:

- The only knob that trades true- vs false-positives is the **global suspicion
  threshold**, and it is never fixed — the ROC/PR analysis **sweeps** it.
- The few **structural** constants (temporal window `W`, median/trim choice,
  equal ensemble weights) are set from protocol/first-principles reasoning
  (e.g. `W` from gossip-round dynamics), **not** optimized against the attack
  set. Ensemble **weights are fixed and equal**; they are a presentation choice,
  not a tuned parameter.
- The ROC analysis reports **each detector's score separately**; the ensemble is
  combined only for a single headline number. So the combination cannot launder a
  tuned-to-the-test-set parameter.

Interview answer to "did you tune this to your own test cases?": *the detectors
have no parameters fit to the attacks; the only swept knob is the decision
threshold, and each detector is also reported standalone.*

## Implementation plan (after approval)

```
detectors/
  __init__.py        # ensemble + normalization + global aggregation
  base.py            # Observation = (link_costs, history); Detector interface
  plausibility.py
  cross_source.py
  temporal.py
tests/test_detectors.py   # synthetic vectors with planted lies per the (c) rows above
```

Detectors will be pure and import nothing from `attacks/` or any config.
