#Sebastian Valine 2026
#this script launches each of the nodes in the config file. 
#each node has its own process, with three total threads: main, listen, and gossip.

import json
import subprocess
import sys
import time
import os
import threading
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--config", default="config.json")
parser.add_argument("--split-horizon", dest="split_horizon", choices=["on", "off"], default="on")
parser.add_argument("--seed", type=int, default=None)
cli = parser.parse_args()

#load in config
with open(cli.config) as f:
    config = json.load(f)

#shared flags forwarded to every node process
node_flags = ["--config", cli.config, "--split-horizon", cli.split_horizon]
if cli.seed is not None:
    node_flags += ["--seed", str(cli.seed)]

#create the logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)
processes = {}
log_files = {}
used_ports = {info["port"] for info in config["nodes"].values()}


def start_node(node_id, extra_args=None):
    log = open(f"logs/{node_id}.log", "w")
    log_files[node_id] = log
    cmd = [sys.executable, "node.py", node_id, *node_flags]
    if extra_args:
        cmd.extend(extra_args)
    p = subprocess.Popen(cmd, stdout=log, stderr=log)
    processes[node_id] = p
    print(f"started node {node_id}")


def join_node(node_id, port, neighbors):
    if node_id in processes and processes[node_id].poll() is None:
        print(f"node {node_id} already running")
        return
    if port in used_ports:
        print(f"port {port} already in use")
        return
    used_ports.add(port)
    start_node(node_id, ["--port", str(port), "--neighbors", *neighbors])


def leave_node(node_id):
    if node_id not in processes:
        print(f"node {node_id} not running")
        return
    if processes[node_id].poll() is not None:
        print(f"node {node_id} not running")
        del processes[node_id]
        return
    processes[node_id].terminate()
    print(f"leaving node {node_id}")


def command_loop():
    for line in sys.stdin:
        parts = line.strip().split()
        if not parts:
            continue
        if parts[0] == "join" and len(parts) >= 4:
            join_node(parts[1], int(parts[2]), parts[3:])
        elif parts[0] == "leave" and len(parts) == 2:
            leave_node(parts[1])
        else:
            print("commands: join <id> <port> <neighbor>..., leave <id>")


#start each node in a new process
for node_id in config["nodes"]:
    start_node(node_id)
    time.sleep(0.1)

print(f"split-horizon: {cli.split_horizon}")
print("commands: join <id> <port> <neighbor>..., leave <id>")
threading.Thread(target=command_loop, daemon=True).start()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("shutting down")
    for p in processes.values():
        p.terminate()
