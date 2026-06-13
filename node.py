#Sebastian Valine 2026

#this script is a node in the mesh network.
#it listens for messages from other nodes, updates its routing table, and gossips its routing table to the other nodes.

#import the necessary libraries
import socket
import threading
import sys
import json
import time
import random
import signal
import argparse

import routing
import attacks

GOSSIP_INTERVAL = 2
HEARTBEAT_INTERVAL = 1
HEARTBEAT_TIMEOUT = 5

parser = argparse.ArgumentParser()
parser.add_argument("node_id")
parser.add_argument("--config", default="config.json")
parser.add_argument("--port", type=int)
parser.add_argument("--neighbors", nargs="*", default=None)
parser.add_argument("--split-horizon", dest="split_horizon", choices=["on", "off"], default="on",
                    help="split horizon with poison reverse (on) vs naive distance-vector (off)")
parser.add_argument("--seed", type=int, default=None,
                    help="seed node-local randomness for reproducible runs")
args = parser.parse_args()

node_id = args.node_id
join_mode = args.port is not None
split_horizon = args.split_horizon == "on"

if args.seed is not None:
    random.seed(args.seed)

#import the config file and load it into a dictionary
with open(args.config) as f:
    config = json.load(f)

nodes = config["nodes"]

if join_mode:
    port = args.port
    neighbor_ids = list(args.neighbors or [])
    known_nodes = {node_id: port}
    for neighbor in neighbor_ids:
        if neighbor in nodes:
            known_nodes[neighbor] = nodes[neighbor]["port"]
    #joining nodes default to unit link cost unless the config already lists the link
    configured = routing.link_costs_from_config(config, node_id)
    link_costs = {nb: configured.get(nb, 1) for nb in neighbor_ids}
else:
    port = nodes[node_id]["port"]
    link_costs = routing.link_costs_from_config(config, node_id)
    neighbor_ids = list(link_costs.keys())
    known_nodes = {nid: info["port"] for nid, info in nodes.items()}

#creates a socket object on IPv4 (that's AF_INET) and UDP (that's SOCK_DGRAM)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
#binds it to localhost and the correct port number
sock.bind(('localhost', port))

#routing state. The table is *derived* by re-running weighted Bellman-Ford over
#the most recent distance vector advertised by each neighbor, so we cache those
#vectors and recompute on every change instead of merging in place.
neighbor_vectors = {}
routing_table = {}
last_seen = {neighbor: time.time() for neighbor in neighbor_ids}
dead_nodes = set()
gossip_round = 0
last_change_time = time.time()
start_time = time.time()
lock = threading.Lock()

#optional adversarial behavior for this node (None for honest nodes)
attacker = attacks.from_config(config, node_id)
attack_announced = False


def recompute():
    """Rebuild the routing table from cached neighbor vectors and link costs."""
    global last_change_time
    with lock:
        live_links = dict(link_costs)
        vectors = {
            nb: {d: c for d, c in vec.items() if d not in dead_nodes}
            for nb, vec in neighbor_vectors.items()
            if nb in live_links
        }
    new_table = routing.compute_table(node_id, live_links, vectors)
    with lock:
        changed = new_table != routing_table
        if changed:
            routing_table.clear()
            routing_table.update(new_table)
            last_change_time = time.time()
    return changed


def get_neighbors():
    with lock:
        return list(neighbor_ids)


def send_to(neighbor_id, message):
    with lock:
        neighbor_port = known_nodes.get(neighbor_id)
    if neighbor_port is None:
        return
    payload = json.dumps(message).encode()
    sock.sendto(payload, ("localhost", neighbor_port))


def touch_last_seen(sender):
    with lock:
        if sender in neighbor_ids:
            last_seen[sender] = time.time()


def add_neighbor(neighbor_id, neighbor_port):
    with lock:
        if neighbor_id in dead_nodes:
            dead_nodes.discard(neighbor_id)
        known_nodes[neighbor_id] = neighbor_port
        is_new = neighbor_id not in neighbor_ids
        if is_new:
            neighbor_ids.append(neighbor_id)
            configured = routing.link_costs_from_config(config, node_id)
            link_costs[neighbor_id] = configured.get(neighbor_id, 1)
            last_seen[neighbor_id] = time.time()
    if is_new:
        recompute()


def absorb_dead_nodes(reported):
    new_dead = False
    with lock:
        for dead_id in reported:
            if dead_id not in dead_nodes:
                dead_nodes.add(dead_id)
                new_dead = True
    if new_dead:
        recompute()


def handle_gossip(message):
    absorb_dead_nodes(message.get("dead_nodes", []))
    sender = message["from"]
    with lock:
        neighbor_vectors[sender] = dict(message["table"])
    recompute()


def handle_heartbeat(message):
    pass


def handle_withdraw(message):
    mark_neighbor_dead(message["from"])


def handle_status_request(message):
    """Reply to the convergence observer with our current state."""
    reply_port = message.get("reply_port")
    if reply_port is None:
        return
    with lock:
        snapshot = {
            "type": "status",
            "from": node_id,
            "table": {d: info["cost"] for d, info in routing_table.items()},
            "last_change": last_change_time,
            "round": gossip_round,
            "neighbors": list(neighbor_ids),
        }
    payload = json.dumps(snapshot).encode()
    sock.sendto(payload, ("localhost", reply_port))


def handle_hello(message):
    sender = message["from"]
    sender_port = message["port"]
    sender_neighbors = message.get("neighbors", [])

    with lock:
        we_know_them = sender in neighbor_ids
    they_know_us = node_id in sender_neighbors

    if we_know_them or they_know_us:
        add_neighbor(sender, sender_port)
        reply = {
            "type": "hello",
            "from": node_id,
            "port": port,
            "neighbors": get_neighbors(),
        }
        send_to(sender, reply)


def handle_message(message):
    msg_type = message["type"]

    if msg_type == "hello":
        handle_hello(message)
        return
    if msg_type == "status_request":
        handle_status_request(message)
        return

    sender = message["from"]
    with lock:
        if sender not in neighbor_ids:
            return
    touch_last_seen(sender)
    if msg_type == "gossip":
        handle_gossip(message)
    elif msg_type == "heartbeat":
        handle_heartbeat(message)
    elif msg_type == "withdraw":
        handle_withdraw(message)


def mark_neighbor_dead(neighbor_id):
    with lock:
        if neighbor_id not in neighbor_ids:
            return
        neighbor_ids.remove(neighbor_id)
        link_costs.pop(neighbor_id, None)
        neighbor_vectors.pop(neighbor_id, None)
        last_seen.pop(neighbor_id, None)
        dead_nodes.add(neighbor_id)
    print(f"[{node_id}] NEIGHBOR_DOWN {neighbor_id}", flush=True)
    recompute()


def monitor_neighbors():
    while True:
        time.sleep(HEARTBEAT_INTERVAL)
        now = time.time()
        for neighbor_id in get_neighbors():
            with lock:
                seen = last_seen.get(neighbor_id, 0)
            if now - seen > HEARTBEAT_TIMEOUT:
                mark_neighbor_dead(neighbor_id)


#gossips the routing table to the other nodes
def heartbeat():
    while True:
        time.sleep(HEARTBEAT_INTERVAL)
        message = {"type": "heartbeat", "from": node_id}
        for neighbor_id in get_neighbors():
            send_to(neighbor_id, message)


def gossip():
    global gossip_round, attack_announced
    while True: #gossip every 2 seconds
        time.sleep(GOSSIP_INTERVAL)
        with lock:
            table_copy = {d: dict(info) for d, info in routing_table.items()}
            dead_copy = list(dead_nodes)
            gossip_round += 1
            this_round = gossip_round

        if attacker and attacker.active(this_round) and not attack_announced:
            print(f"[{node_id}] ATTACK_ACTIVE round={this_round}: {attacker.describe()}", flush=True)
            attack_announced = True

        #build a per-recipient advertisement so split horizon / poison reverse
        #can suppress routes learned from that very neighbor
        for neighbor_id in get_neighbors():
            advertisement = routing.build_advertisement(
                table_copy, neighbor_id,
                split_horizon=split_horizon, poison_reverse=split_horizon,
            )
            #adversarial nodes rewrite their advertisement per recipient
            if attacker:
                ctx = attacks.AttackContext(
                    node_id=node_id, recipient=neighbor_id, round=this_round,
                    elapsed=time.time() - start_time, honest_table=table_copy,
                )
                advertisement = attacker.transform(advertisement, ctx)
            message = {
                "type": "gossip",
                "from": node_id,
                "table": advertisement,
                "dead_nodes": dead_copy,
            }
            send_to(neighbor_id, message)


#listens for messages from other nodes
def listen():
    while True: #listen for messages forever
        data, addr = sock.recvfrom(8192)
        message = json.loads(data.decode()) #decode the message
        handle_message(message)


def send_bootstrap_hello():
    message = {"type": "hello", "from": node_id, "port": port, "neighbors": get_neighbors()}
    for neighbor_id in get_neighbors():
        send_to(neighbor_id, message)


def on_sigterm(signum, frame):
    message = {"type": "withdraw", "from": node_id}
    for neighbor_id in get_neighbors():
        send_to(neighbor_id, message)
    sys.exit(0)


signal.signal(signal.SIGTERM, on_sigterm)

#seed the table with the zero-cost self route and direct links
recompute()

#start the listen, gossip, heartbeat, and monitor threads.
threading.Thread(target=listen, daemon=True).start()
threading.Thread(target=gossip, daemon=True).start()
threading.Thread(target=heartbeat, daemon=True).start()
threading.Thread(target=monitor_neighbors, daemon=True).start()

if join_mode:
    send_bootstrap_hello()


while True: #main thread to print the routing table every second
    time.sleep(1)
    with lock: #locked print
        print(f"[{node_id}] routing table: {routing_table}", flush=True)
