#Sebastian Valine 2026

"""Convergence observer for the live UDP mesh.

The observer is a passive monitor: it knows the ground-truth topology from the
config, periodically asks every node for its current routing table via a
``status_request`` message, and reports when the network has globally converged.

Convergence is defined as: every node's distance vector equals the analytically
computed least-cost paths AND no node has changed its table within one full
gossip round (so we know it is stable, not merely passing through the right
state). The observer reports the wall-clock time and the gossip-round count at
which this first holds.

The decision logic (``expected_vectors``, ``tables_match_expected``,
``evaluate_convergence``) is pure and unit tested; only the polling loop touches
sockets.
"""

import argparse
import json
import socket
import time

import routing

GOSSIP_INTERVAL = 2


def expected_vectors(config, default_cost=1):
    """Ground-truth least-cost distance vector for every node, ``{node: {dest: cost}}``."""
    adjacency = routing.adjacency_from_links(config.get("links", []), default_cost)
    return routing.all_pairs_shortest(adjacency)


def tables_match_expected(reported_tables, expected):
    """True iff every expected node reported a vector equal to ground truth.

    ``reported_tables`` is ``{node: {dest: cost}}``. A node is required to be
    present and to match its expected vector exactly.
    """
    for node, expected_vec in expected.items():
        reported = reported_tables.get(node)
        if reported is None:
            return False
        if reported != expected_vec:
            return False
    return True


def evaluate_convergence(reported, expected, now, gossip_interval=GOSSIP_INTERVAL):
    """Pure convergence decision.

    Args:
        reported: ``{node: {"table": {dest: cost}, "last_change": epoch}}``.
        expected: ground-truth vectors from :func:`expected_vectors`.
        now: current epoch seconds.
        gossip_interval: seconds in one gossip round.

    Returns:
        ``(converged: bool, reason: str)``.
    """
    missing = [n for n in expected if n not in reported]
    if missing:
        return False, f"waiting on {sorted(missing)}"

    tables = {n: r["table"] for n, r in reported.items()}
    if not tables_match_expected(tables, expected):
        return False, "tables not yet globally consistent"

    unstable = [
        n for n, r in reported.items()
        if now - r.get("last_change", now) < gossip_interval
    ]
    if unstable:
        return False, f"recently changed: {sorted(unstable)}"

    return True, "converged"


def poll_once(sock, nodes, reply_port, timeout=0.4):
    """Send a status request to every node and gather replies for ``timeout`` seconds."""
    request = json.dumps({"type": "status_request", "reply_port": reply_port}).encode()
    for info in nodes.values():
        try:
            sock.sendto(request, ("localhost", info["port"]))
        except OSError:
            pass

    replies = {}
    deadline = time.time() + timeout
    sock.settimeout(timeout)
    while time.time() < deadline:
        try:
            data, _ = sock.recvfrom(8192)
        except socket.timeout:
            break
        except OSError:
            break
        msg = json.loads(data.decode())
        if msg.get("type") == "status":
            replies[msg["from"]] = {
                "table": msg["table"],
                "last_change": msg["last_change"],
                "round": msg.get("round", 0),
            }
    return replies


def watch(config, timeout=60.0, interval=0.5, as_json=False):
    """Poll the live mesh until convergence or ``timeout`` seconds elapse."""
    expected = expected_vectors(config)
    nodes = config["nodes"]

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("localhost", 0))
    reply_port = sock.getsockname()[1]

    start = time.time()
    deadline = start + timeout
    while time.time() < deadline:
        now = time.time()
        replies = poll_once(sock, nodes, reply_port)
        converged, reason = evaluate_convergence(replies, expected, now)
        if converged:
            elapsed = now - start
            rounds = max((r["round"] for r in replies.values()), default=0)
            result = {
                "converged": True,
                "wall_clock_seconds": round(elapsed, 3),
                "gossip_rounds": rounds,
                "nodes": len(expected),
            }
            sock.close()
            return _report(result, as_json)
        time.sleep(interval)

    sock.close()
    return _report({"converged": False, "wall_clock_seconds": round(timeout, 3),
                    "reason": reason, "nodes": len(expected)}, as_json)


def _report(result, as_json):
    if as_json:
        print(json.dumps(result))
    elif result["converged"]:
        print(f"CONVERGED in {result['wall_clock_seconds']}s "
              f"after {result['gossip_rounds']} gossip rounds "
              f"({result['nodes']} nodes)")
    else:
        print(f"NOT CONVERGED within {result['wall_clock_seconds']}s "
              f"({result['nodes']} nodes): {result.get('reason')}")
    return result


def main():
    parser = argparse.ArgumentParser(description="Mesh convergence observer")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--json", action="store_true")
    cli = parser.parse_args()

    with open(cli.config) as f:
        config = json.load(f)
    watch(config, timeout=cli.timeout, interval=cli.interval, as_json=cli.json)


if __name__ == "__main__":
    main()
