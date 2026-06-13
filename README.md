# mesh-node

A simulated mesh network using Python processes as nodes, communicating over UDP.

Each node implements distance vector routing with a gossip protocol for topology discovery. Nodes only know their direct neighbors at startup and discover the full network topology through periodic gossip exchanges.

## How it works

Each node runs as an independent Python process with five concurrent threads. The listener receives incoming UDP packets and dispatches by message type. The gossip sender broadcasts its routing table to direct neighbors every 2 seconds. The heartbeat sender sends liveness pings every 1 second. The monitor thread checks for neighbor timeouts every 1 second. The main thread logs routing table state every second.

When a node receives a neighbor's routing table via gossip, it runs Bellman-Ford to update its own table. Full topology convergence occurs within a few gossip rounds.

Nodes detect failed neighbors via heartbeat timeout (5 seconds). When a neighbor dies or sends a withdraw message, the node purges routes through that neighbor and propagates the failure via gossip. New nodes join at runtime by sending a hello message to bootstrap neighbors.

## Topology

The initial topology is stored in `config.json` and used to launch the mesh. It can be edited before starting the launcher. The current topology is:

```
A - B - C - F - G

    |           |
    D - E       H - I

                    |
                    J
```

After launch, the topology can change at runtime via join and leave commands.

## How to run

```bash
python3 launcher.py
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
| `gossip` | Routing table + `dead_nodes` list |
| `heartbeat` | Neighbor liveness ping |
| `hello` | Node join; carries `port` and `neighbors` |
| `withdraw` | Graceful leave notification |

## Manual test checklist

| Scenario | Command | Expected |
|----------|---------|----------|
| Baseline | `python3 launcher.py` | All 10 nodes converge (~6s) |
| Crash | `kill -9` a node process | Direct neighbors log `NEIGHBOR_DOWN` within ~5s |
| Graceful leave | `leave E` in launcher | Neighbors detect within ~1s |
| Join | `join K 5011 J` in launcher | K appears in upstream routing tables within ~10s |

## Next steps

- [x] Distance vector routing
- [x] Gossip-based topology discovery
- [x] Dynamic topology (node join/leave, heartbeats and heartbeat failure)
- [ ] Cost/routing calculations (best route, fewest hops)
- [ ] Adversarial node simulation (false cost/topology advertisement)
- [ ] Cross-source gossip verification and anomaly detection
- [ ] Detection accuracy benchmarking

Also interesting will be changing costs from a universal 1 per hop and doing best route calculations on a dynamically changing routing table.
