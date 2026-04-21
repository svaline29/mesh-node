#Sebastian Valine 2026
#this script launches each of the nodes in the config file. 
#each node has its own process, with three total threads: main, listen, and gossip.

import json
import subprocess
import sys
import time
import os

#load in config
with open("config.json") as f:
    config = json.load(f)

#create the logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)
#create a list to store the processes
processes = []


#start each node in a new process
for node_id in config["nodes"]:
    log = open(f"logs/{node_id}.log", "w") #create a log file for the node
    p = subprocess.Popen(
        [sys.executable, "node.py", node_id], #run the node.py script with the node id
        stdout=log, #redirect the stdout to the log file
        stderr=log #redirect the stderr to the log file
    )
    processes.append(p) #add the process to the list
    print(f"started node {node_id}") #print that the node started
    time.sleep(0.1) #wait 0.1 seconds before starting the next node

try:
    while True: #main thread to keep the program running
        time.sleep(1) #wait 1 second before checking again
except KeyboardInterrupt:
    print("shutting down") #print that the program is shutting down
    for p in processes: #terminate all the processes
        p.terminate()