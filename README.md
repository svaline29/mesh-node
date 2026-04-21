# mesh-node

A simulated mesh network using Python processes as nodes, communicating over UDP.

Each node implements distance vector routing with a gossip protocol for topology discovery. Nodes only know their direct neighbors at startup and discover the full network topology through periodic gossip exchanges.

## How it works

Each node runs as an independent Python process with three concurrent threads. The listener receives incoming UDP packets. The gossip sender broadcasts its routing table to direct neighbors every 2 seconds. The main thread logs routing table state every second.

When a node receives a neighbor's routing table via gossip, it runs Bellman-Ford to update its own table. Full topology convergence occurs within a few gossip rounds.

## Topology
The topology as current configured is stored in config.json. This can be edited and the program will run using the updated version, the one I have right now is this:
```
A - B - C - F - G

    |           |
    D - E       H - I

                    |
                    J
```

## How to run

python3 launcher.py

Logs can be found in the log folder generated after the first run. To watch a single node's routing table converge over time, use tail -f logs/A.log.

## Next steps

The next thing I will be adding is dynamic changes and updates to the topology during runtime. Right now the config file is just loaded in at the beginning: I want to be able to handle nodes joining and leaving while the processes are running. 

Also interesting will be changing costs from a universal 1 per hop and doing best route calculations on a dynamically changing routing table. 

- [x] Distance vector routing
- [x] Gossip-based topology discovery
- [ ] Dynamic topology (node join/leave, heartbeats and heartbeat failure)
- [ ] Cost/routing calculations (best route, fewest hops)
- [ ] Adversarial node simulation (false cost/topology advertisement)
- [ ] Cross-source gossip verification and anomaly detection
- [ ] Detection accuracy benchmarking
