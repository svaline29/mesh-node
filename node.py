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

#import the config file and load it into a dictionary
with open("config.json") as f:
    config = json.load(f)

#get the node id from the command line arguments
node_id = sys.argv[1]

#get nodes, corresponding port, and all neighbor ids from the loaded config
nodes = config["nodes"]
port = nodes[node_id]["port"]
neighbor_ids = nodes[node_id]["neighbors"]


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
lock = threading.Lock()


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
def gossip():
    while True: #gossip every 2 seconds
        time.sleep(2)
        with lock: #locked copy
            table_copy = copy.deepcopy(routing_table) 
        
        payload = json.dumps({ #create the payload to send to the other nodes
            "type": "gossip",
            "from": node_id,
            "table": table_copy
        }).encode()
        
        for neighbor_id in neighbor_ids: #send to all neighbors
            neighbor_port = nodes[neighbor_id]["port"] #get the port of the neighbor
            sock.sendto(payload, ("localhost", neighbor_port)) #send the payload to the neighbor

#listens for messages from other nodes
def listen():
    while True: #listen for messages forever
        data, addr = sock.recvfrom(4096)
        message = json.loads(data.decode()) #decode the message
        
        if message["type"] == "gossip": #if the message is a gossip message
            update_routing_table(message["from"], message["table"]) #update the routing table with the received table


#start the listen and gossip threads. 
threading.Thread(target=listen, daemon=True).start()
threading.Thread(target=gossip, daemon=True).start()


while True: #main thread to print the routing table every second
    time.sleep(1)
    with lock: #locked print
        print(f"[{node_id}] routing table: {routing_table}", flush=True)