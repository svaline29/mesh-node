#Sebastian Valine 2026

#this script is a node in the mesh network.
#it listens for messages from other nodes, updates its routing table, and gossips its routing table to the other nodes.

#import the necessary libraries
import socket
import threading
import sys
import json
import time
import copy

GOSSIP_INTERVAL = 2
HEARTBEAT_INTERVAL = 1
HEARTBEAT_TIMEOUT = 5

#import the config file and load it into a dictionary
with open("config.json") as f:
    config = json.load(f)

#get the node id from the command line arguments
node_id = sys.argv[1]

#get nodes, corresponding port, and all neighbor ids from the loaded config
nodes = config["nodes"]
port = nodes[node_id]["port"]
neighbor_ids = list(nodes[node_id]["neighbors"])
known_nodes = {nid: info["port"] for nid, info in nodes.items()}

#creates a socket object on IPv4 (that's AF_INET) and UDP (that's SOCK_DGRAM)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) 
#binds it to localhost and the correct port number
sock.bind(('localhost', port))

#create a routing table for the node using distance vector routing
#all neighbors cost 1, self cost is 0
routing_table = {}
for neighbor in neighbor_ids:
    routing_table[neighbor] = {"cost": 1, "next_hop": neighbor}
routing_table[node_id] = {"cost": 0, "next_hop": node_id}
last_seen = {neighbor: time.time() for neighbor in neighbor_ids}
dead_nodes = set()
lock = threading.Lock()


def get_neighbors():
    with lock:
        return list(neighbor_ids)


def send_to(neighbor_id, message):
    with lock:
        neighbor_port = known_nodes[neighbor_id]
    payload = json.dumps(message).encode()
    sock.sendto(payload, ("localhost", neighbor_port))


def touch_last_seen(sender):
    with lock:
        if sender in neighbor_ids:
            last_seen[sender] = time.time()


def absorb_dead_nodes(reported):
    for dead_id in reported:
        with lock:
            is_new = dead_id not in dead_nodes
            dead_nodes.add(dead_id)
        if is_new:
            purge_routes_via(dead_id)


def handle_gossip(message):
    absorb_dead_nodes(message.get("dead_nodes", []))
    update_routing_table(message["from"], message["table"])


def handle_heartbeat(message):
    pass


def handle_message(message):
    sender = message["from"]
    with lock:
        if sender not in neighbor_ids:
            return
    touch_last_seen(sender)
    if message["type"] == "gossip":
        handle_gossip(message)
    elif message["type"] == "heartbeat":
        handle_heartbeat(message)


def purge_routes_via(dead_id):
    purged = []
    with lock:
        for dest in list(routing_table.keys()):
            if dest == dead_id or routing_table[dest]["next_hop"] == dead_id:
                purged.append(dest)
                del routing_table[dest]
    if purged:
        print(f"[{node_id}] ROUTE_PURGED via {dead_id}: {purged}", flush=True)


def mark_neighbor_dead(neighbor_id):
    with lock:
        if neighbor_id not in neighbor_ids:
            return
        neighbor_ids.remove(neighbor_id)
        last_seen.pop(neighbor_id, None)
        dead_nodes.add(neighbor_id)
    print(f"[{node_id}] NEIGHBOR_DOWN {neighbor_id}", flush=True)
    purge_routes_via(neighbor_id)


def monitor_neighbors():
    while True:
        time.sleep(HEARTBEAT_INTERVAL)
        now = time.time()
        for neighbor_id in get_neighbors():
            with lock:
                seen = last_seen.get(neighbor_id, 0)
            if now - seen > HEARTBEAT_TIMEOUT:
                mark_neighbor_dead(neighbor_id)


#updates the routing table with the received table from a neighbor
def update_routing_table(neighbor_id, received_table):
    updated = False
    with lock: #locked copy
        table_copy = copy.deepcopy(routing_table)
        local_dead = set(dead_nodes)
    
    #update the routing table with the received table
    for dest, info in received_table.items():
        if dest == node_id or dest in local_dead: #skip self and known-dead nodes
            continue
        new_cost = 1 + info["cost"] #add 1 to the cost of the received table
        if dest not in table_copy or new_cost < table_copy[dest]["cost"]: #if the destination is not in the table or the new cost is less than the current cost
            table_copy[dest] = {"cost": new_cost, "next_hop": neighbor_id} #update the routing table with the new cost and next hop
            updated = True #set updated to true to indicate that the routing table was updated

    for dest in list(table_copy.keys()):
        if dest == node_id:
            continue
        if table_copy[dest]["next_hop"] == neighbor_id and dest not in received_table:
            del table_copy[dest]
            updated = True
    
    if updated: #if the routing table was updated
        with lock: #locked update
            routing_table.update(table_copy) #update the routing table with the new table

#gossips the routing table to the other nodes
def heartbeat():
    while True:
        time.sleep(HEARTBEAT_INTERVAL)
        message = {"type": "heartbeat", "from": node_id}
        for neighbor_id in get_neighbors():
            send_to(neighbor_id, message)


def gossip():
    while True: #gossip every 2 seconds
        time.sleep(GOSSIP_INTERVAL)
        with lock: #locked copy
            table_copy = copy.deepcopy(routing_table)
            dead_copy = list(dead_nodes)
        
        message = {
            "type": "gossip",
            "from": node_id,
            "table": table_copy,
            "dead_nodes": dead_copy,
        }
        
        for neighbor_id in get_neighbors():
            send_to(neighbor_id, message)

#listens for messages from other nodes
def listen():
    while True: #listen for messages forever
        data, addr = sock.recvfrom(4096)
        message = json.loads(data.decode()) #decode the message
        handle_message(message)


#start the listen, gossip, heartbeat, and monitor threads. 
threading.Thread(target=listen, daemon=True).start()
threading.Thread(target=gossip, daemon=True).start()
threading.Thread(target=heartbeat, daemon=True).start()
threading.Thread(target=monitor_neighbors, daemon=True).start()


while True: #main thread to print the routing table every second
    time.sleep(1)
    with lock: #locked print
        print(f"[{node_id}] routing table: {routing_table}", flush=True)
