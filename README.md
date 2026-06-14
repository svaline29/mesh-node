# mesh-node

A simulated mesh network using Python processes as nodes, communicating over UDP.

Each node implements weighted distance-vector routing with a gossip protocol for topology discovery. Nodes only know their direct neighbors (and per-link costs) at startup and discover the full network topology through periodic gossip exchanges.

## How it works

Each node runs as an independent Python process with five concurrent threads. The listener receives incoming UDP packets and dispatches by message type. The gossip sender broadcasts a per-neighbor advertisement of its routing table every 2 seconds. The heartbeat sender sends liveness pings every 1 second. The monitor thread checks for neighbor timeouts every 1 second. The main thread logs routing table state every second.

The routing math lives in `routing.py`, a pure, transport-free module (no sockets or threads) so it can be unit tested and reused by the offline benchmarking harness. Each node caches the most recent distance vector advertised by every neighbor and recomputes its whole table with weighted Bellman-Ford (`link_cost + advertised_cost`) on every change, producing **least-cost** paths rather than fewest-hops. Full topology convergence occurs within a few gossip rounds.

### Split horizon with poison reverse

Naive distance-vector routing suffers from count-to-infinity: when a route disappears, two nodes can bounce an ever-increasing cost back and forth through each other. The `--split-horizon` flag (default `on`) addresses this: when building the advertisement for a given neighbor, any destination whose next hop *is that neighbor* is advertised as unreachable (`INF`, poison reverse) instead of being echoed back. Run with `--split-horizon off` to reproduce the naive behavior for comparison.

### Convergence detection

`observer.py` is a passive monitor that knows the ground-truth topology from the config. It periodically asks every node for its current routing table (a `status_request` message) and reports the wall-clock time and gossip-round count at which the network first becomes **globally consistent** — every node's distance vector equals the analytically computed least-cost paths *and* no node has changed within one full gossip round.

```bash
python3 observer.py --config config.json --json
# -> {"converged": true, "wall_clock_seconds": 10.9, "gossip_rounds": 7, "nodes": 10}
```

Live UDP convergence timing is inherently noisy (OS scheduling, thread timing); it is reported as a measured datapoint. Fully seed-reproducible convergence counts come from the deterministic offline harness (see [Benchmarking harness](#benchmarking-harness)).

Nodes detect failed neighbors via heartbeat timeout (5 seconds). When a neighbor dies or sends a withdraw message, the node purges routes through that neighbor and propagates the failure via gossip. New nodes join at runtime by sending a hello message to bootstrap neighbors.

## Topology

The initial topology is stored in `config.json`: a map of `nodes` (each with a `port`) and an undirected, weighted `links` list. Costs are specified once per link, so the two endpoints can never disagree on a cost.

```json
{
  "nodes": { "A": {"port": 5001}, "B": {"port": 5002} },
  "links": [ {"a": "A", "b": "B", "cost": 2} ]
}
```

Each node derives its own neighbors and link costs by filtering the links incident to it. A missing `cost` defaults to 1 (so old uniform-cost configs still work). The default topology is a weighted tree (A–B–C–F–G with D/E and H/I/J branches); `examples/weighted_cycle.json` is a small cyclic topology where the least-cost path differs from the fewest-hops path, useful for demonstrating weighted routing and split horizon.

After launch, the topology can change at runtime via join and leave commands.

## How to run

```bash
python3 launcher.py                          # default config, split horizon on
python3 launcher.py --split-horizon off      # naive distance-vector (for comparison)
python3 launcher.py --config examples/weighted_cycle.json --seed 1
```

Logs are written to the `logs/` folder. To watch a single node's routing table converge over time:

```bash
tail -f logs/A.log
```

### Runtime commands

While the launcher is running, type commands at its prompt:

```
join K 5011 J        # spawn node K on port 5011, connected to neighbor J
leave E              # gracefully shut down node E
```

Bootstrap neighbors must already be running. Their ports are resolved from `config.json`.

### Join a node manually

```bash
python3 node.py K --port 5011 --neighbors J
```

## Protocol

All messages are JSON over UDP.

| Type | Purpose |
|------|---------|
| `gossip` | Per-neighbor distance-vector advertisement + `dead_nodes` list |
| `heartbeat` | Neighbor liveness ping |
| `hello` | Node join; carries `port` and `neighbors` |
| `withdraw` | Graceful leave notification |
| `status_request` | Observer asks a node for its current table; carries `reply_port` |
| `status` | A node's reply to the observer (table, last-change time, gossip round) |

## Adversarial nodes

Any node can be made malicious from the config via an `attackers` block. Attack
behaviors live in `attacks/`, a transport-free package: each attack is a pure
`{dest: cost}` → `{dest: cost}` transform applied to a node's outgoing
advertisement, so they are unit-testable and reused unchanged by the harness.
Modes are **composable** (applied in order) and gated by a `start_round` so runs
stay reproducible.

| Mode | Effect |
|------|--------|
| `FALSE_COST` | Advertise an artificially low `cost` to `targets` (or all destinations) — route hijack / blackhole. |
| `FALSE_TOPOLOGY` | Inject `fake` destinations/links (`{dest: cost}`) that don't exist. |
| `FLAPPING` | Alternate advertised cost between `low`/`high` every `period` gossip rounds — induces instability. |
| `SELECTIVE` | Apply `inner` attacks only toward `victims`; advertise honestly to everyone else (hardest to detect). |
| `COLLUSION` | A `group` of nodes tell the identical coordinated lie and vouch for each other (`vouch_cost`), fabricating a consensus that defeats cross-source consistency. |

```json
"attackers": {
  "F": {
    "start_round": 3,
    "modes": [
      {"type": "FALSE_COST", "targets": ["A", "E", "J"], "cost": 0}
    ]
  }
}
```

```bash
python3 launcher.py --config examples/attack_false_cost.json --seed 1
# After round 3, neighbor C's table shows J at cost 1 via F (honest cost is 7).
```

See `examples/attack_false_cost.json`, `examples/attack_flapping.json`, and
`examples/attack_selective.json`.

### Collusion and the Byzantine threshold

A single liar is an outlier and cross-source consistency can flag it. Colluding
nodes corroborate one another's false advertisements, so honest observers see a
fabricated consensus instead. `examples/attack_collusion_{1,2,3}.json` are
matched scenarios (the same lie, told by groups of size 1, 2, and 3) so the
benchmarking harness can measure exactly how detection degrades as the colluding
group grows — i.e. characterize the Byzantine threshold honestly rather than
claiming robustness the system doesn't have. `attacks.malicious_nodes()` and
`attacks.colluding_groups()` expose the ground truth for scoring.

## Detection

Anomaly detectors live in `detectors/`, a transport-free package. Each detector
runs from the vantage of an honest node and sees **only what that node sees at
runtime**: its own trusted link costs and the history of distance vectors its
direct neighbors have gossiped. They reference no attacker config, no node IDs,
and no attack modes; the full design rationale is in
[`docs/detector_design.md`](docs/detector_design.md).

Because an adversary manipulates its own outgoing advertisement, the
inconsistency surfaces in the vector attributed to it and is seen by its honest
neighbors, so each detector scores the observer's direct neighbors and the
harness aggregates into global per-node scores.

| Detector | Invariant it relies on | Catches | Documented limit |
|----------|------------------------|---------|------------------|
| `plausibility` | triangle inequality on the observer's trusted links (hard bound, no static false positives) | gross low-cost lies | misses lies below the geometric slack |
| `cross_source` | path costs via comparable neighbors should cluster; uses a **leave-one-out median** so an attacker can't bias its own baseline | blackholes / subtle low-cost lies, selective lies | **collusion** (a corrupt majority fabricates the consensus) |
| `temporal` | honest costs are piecewise-constant; change rate ≤ churn baseline | flapping | constant lies (left to the others) |

Each emits a **continuous** score (never a binary); the ensemble is a fixed,
**equal-weight** combination used only for a headline number. No weight or
constant is fit to the attack scenarios — the only swept knob is the decision
threshold, and each detector is also reported standalone (for ROC analysis in the
harness). The clean claim, with its three structural limits (collusion, no-honest-
neighbor, pure phantom pendants), is stated and unit-tested per the design note.

## Benchmarking harness

The harness (`harness/`) is a deterministic, seed-reproducible, round-based
simulation that reuses the **exact** `routing`, `attacks`, and `detectors`
modules from the live system — no UDP, no threads — so it measures the identical
logic that runs over the wire. It runs trials with known ground truth and emits
CSVs and matplotlib figures.

```bash
pip install -r requirements.txt
python3 -m harness.run                  # full run -> results/
python3 -m harness.run --quick          # fast, smaller run for iteration
python3 -m harness.run --only frontier  # just the headline experiment
```

### Headline figure: the impact-vs-detectability frontier

The `FALSE_COST` attacker is parameterized by **lie intensity** — a shave
fraction from 0 (honest) to 1 (a zero-cost blackhole) applied to its true cost.
For each intensity, across many random topologies, the harness measures two
things and plots one against the other (`results/impact_vs_detectability.png`):

- **Impact** (x-axis): the fraction of honest source→destination demand whose
  converged route passes through the attacker — the traffic it attracts/hijacks.
- **Detectability** (y-axis): the probability the attacker is flagged at a
  decision threshold pinned to a honest false-positive rate ≤ 5%.

The frontier makes the core tension explicit: **to raise impact the attacker must
lie harder, and lying harder makes it more detectable.** The curve is shown per
detector plus the ensemble, exposing the gross→subtle handoff — the hard
geometric bound (`plausibility`) fires at zero false-positive cost once the lie
clears its slack, while the statistical detector (`cross_source`) extends
coverage and provides an independent signal. The smallest lies sit in the
lower-left (low impact, evade both); the gross lies sit in the upper-right.

### Measurement conventions (and why)

- **Warmup, then attack.** Each trial first runs the honest network to
  convergence; the attack activates at `onset = honest_converged + 1`.
- **Impact is measured at the post-attack steady state** — the eventual hijacked
  traffic share.
- **Detectability is measured at attack onset** — the round the lie first
  appears, before false routes propagate. This is deliberate and important: a
  distance-vector lie *propagates*, and by full convergence the poison has
  homogenized the neighborhood, so the attacker is no longer a local outlier and
  honest relayers carrying the poison look just as anomalous. Onset is the moment
  of maximal cross-source contrast and the lowest-latency detection point — the
  honest place to ask "can this be caught?". (`test_gross_lie_homogenizes_by_convergence`
  pins this regime down.)
- **Thresholds are calibrated on honest scores only** — a per-detector threshold
  holding honest FPR ≤ 5%, reused unchanged across every intensity. No detector
  constant is fit to the attacks; the threshold is the single swept knob. Each
  detector is also reported standalone (ROC), and the ensemble is recombined from
  raw per-detector scores using honest-only scales, so the combination is a
  presentation choice rather than a tuned-to-the-test-set parameter.

### Other experiments

- **Collusion sweep** (`results/collusion_recall.png`). Colluders tell the
  identical *plausible* undercut (sized to stay above the geometric bound, so the
  hard detector cannot rescue it) to a shared target, corrupting the leave-one-out
  median of a common honest observer. Recall on the colluders collapses as the
  group reaches a local majority (≈ 1.0 → 1.0 → 0.4 for sizes 1/2/3), quantifying
  the Byzantine threshold honestly: cross-source consistency is a majority
  argument and collusion is its documented limit.
- **ROC by detector** (`results/roc.png`). Per-detector and ensemble ROC at a
  representative intensity, with AUC. `temporal` sits at chance for a constant
  lie (correct — it is the flapping detector).
- **Honest convergence vs network size** (`results/convergence_vs_size.png`).
  Gossip rounds to global convergence as the network grows, split horizon on vs
  off. The two coincide for cold-start convergence — split horizon's benefit is
  preventing count-to-infinity on topology *changes*, not speeding up initial
  convergence.

All figures have matching CSVs (`frontier.csv`, `collusion.csv`, `roc.csv`,
`roc_auc.csv`, `convergence.csv`) and a `summary.json` recording the config,
calibrated thresholds, and timings. Everything is driven by a single `--seed`.

## Manual test checklist

| Scenario | Command | Expected |
|----------|---------|----------|
| Baseline | `python3 launcher.py` | All 10 nodes converge (~6s) |
| Crash | `kill -9` a node process | Direct neighbors log `NEIGHBOR_DOWN` within ~5s |
| Graceful leave | `leave E` in launcher | Neighbors detect within ~1s |
| Join | `join K 5011 J` in launcher | K appears in upstream routing tables within ~10s |

## Tests

```bash
pip install -r requirements.txt
python3 -m pytest -q
```

Covers weighted Bellman-Ford (least-cost vs. fewest-hops), split-horizon / poison-reverse advertisement construction, all-pairs shortest paths, multi-round distance-vector convergence, the observer's convergence-detection logic, every attack mode (including composition and start-round gating), every detector (planted lies, leave-one-out reference, collusion collapse, and the documented structural limits), and the harness itself (the simulator reproduces Bellman-Ford shortest paths in the honest case; impact tracing, ROC, AUC, and the fixed-FPR operating point are checked on hand-computed inputs; the onset-vs-steady-state detectability regime is pinned down).

## Design decisions and tradeoffs

- **Pure routing core (`routing.py`).** The routing math is separated from the UDP/threading machinery so it can be unit tested and reused unchanged by the offline harness. The live node is a thin transport shell around it.
- **Recompute over incremental merge.** Each node recomputes its whole table from cached neighbor vectors every round instead of merging updates in place. This is slightly more work per round but is provably correct for weighted least-cost paths (the previous in-place merge pinned direct neighbors at cost 1 and could miss cheaper indirect routes).
- **Weighted links live in the config, costed once.** An undirected `links` list prevents the two endpoints of a link from disagreeing on cost, which a per-node neighbor map would allow.
- **`INF` is a large integer, not `float('inf')`.** Poison-reverse advertisements stay valid JSON over the wire.
- **Convergence measured two ways.** Live UDP wall-clock (noisy, reported as-is) plus deterministic round counts from the harness (seed-reproducible).
- **Attacks are advertisement transforms, not special node code.** Modeling adversarial behavior as a pure transform on the outgoing vector keeps malice cleanly separated, composable, testable, and identical between the live sim and the harness. The node stays honest; only its advertisement is rewritten per recipient (which is also what makes the `SELECTIVE` attack possible).
- **Attacks are gated and clocked by gossip round, not wall-clock.** `start_round` and `FLAPPING`'s `period` are expressed in gossip rounds so adversarial runs are reproducible.
- **Collusion is modeled explicitly, not hidden.** Cross-source consistency is fundamentally a majority argument and can be overwhelmed by a coordinated minority. Rather than pretend otherwise, the `COLLUSION` mode and matched size-1/2/3 scenarios let the harness quantify where detection breaks down (the Byzantine threshold).
- **Detectors reason from invariants, not signatures.** They see only the data an honest node has at runtime and have no parameters fit to the attacks; the only swept knob is the decision threshold. The cross-source reference is a **leave-one-out median** specifically so the attacker cannot bias its own baseline, and the hard plausibility bound is sound (zero static false positives) by construction. The loose-bound gap is a deliberate, measured handoff to the statistical detector, not a flaw.

## Next steps

- [x] Distance vector routing
- [x] Gossip-based topology discovery
- [x] Dynamic topology (node join/leave, heartbeats and heartbeat failure)
- [x] Weighted per-link costs and least-cost path calculation
- [x] Split horizon with poison reverse (`--split-horizon`)
- [x] Convergence detection (`observer.py`)
- [x] Adversarial node simulation (false cost/topology, flapping, selective, collusion)
- [x] Cross-source gossip verification and anomaly detection (`detectors/`)
- [x] Detection accuracy benchmarking (`harness/`: impact-vs-detectability frontier, collusion sweep, ROC, convergence scaling)
