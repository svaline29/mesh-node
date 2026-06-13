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


def handle_gossip(message):
    update_routing_table(message["from"], message["table"])


def handle_heartbeat(message):
    pass


def handle_message(message):
    touch_last_seen(message["from"])
    if message["type"] == "gossip":
        handle_gossip(message)
    elif message["type"] == "heartbeat":
        handle_heartbeat(message)


#updates the routing table with the received table from a neighbor
def update_routing_table(neighbor_id, received_table):
    updated = False
    with lock: #locked copy
        table_copy = copy.deepcopy(routing_table)
    
    #update the routing table with the received table
    for dest, info in received_table.items():
        if dest == node_id: #skip self
            continue
        new_cost = 1 + info["cost"] #add 1 to the cost of the received table
        if dest not in table_copy or new_cost < table_copy[dest]["cost"]: #if the destination is not in the table or the new cost is less than the current cost
            table_copy[dest] = {"cost": new_cost, "next_hop": neighbor_id} #update the routing table with the new cost and next hop
            updated = True #set updated to true to indicate that the routing table was updated
    
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
        
        message = {
            "type": "gossip",
            "from": node_id,
            "table": table_copy
        }
        
        for neighbor_id in get_neighbors():
            send_to(neighbor_id, message)

#listens for messages from other nodes
def listen():
    while True: #listen for messages forever
        data, addr = sock.recvfrom(4096)
        message = json.loads(data.decode()) #decode the message
        handle_message(message)


#start the listen, gossip, and heartbeat threads. 
threading.Thread(target=listen, daemon=True).start()
threading.Thread(target=gossip, daemon=True).start()
threading.Thread(target=heartbeat, daemon=True).start()


while True: #main thread to print the routing table every second
    time.sleep(1)
    with lock: #locked print
        print(f"[{node_id}] routing table: {routing_table}", flush=True)
