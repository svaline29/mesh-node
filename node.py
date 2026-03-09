import socket
import threading
import sys
import json

PORT_MAP = {
    "A": 5001,
    "B": 5002,
    "C": 5003,
    "D": 5004,
    "E": 5005,
    "F": 5006,
    "E": 5007,
    "G": 5008,
    "H": 5009,
    "I": 5010,
    "J": 5011,
    "K": 5012
}

node_id = sys.argv[1]
port = PORT_MAP[node_id]


#creates a socket object on IPv4 (that's AF_INET) and UDP (that's SOCK_DGRAM)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) 
#binds it to localhost and the correct port number
sock.bind(('localhost', port))


#creates a dictionary of neighbors from all the other ports in the port map
neighbors_dict = {k : v for k,v in PORT_MAP.items() if k != node_id} 


def listen():
    #forever:
    while True:
        data, addr = sock.recvfrom(1024) #sit and listen for a message. max size of 1024 bytes
        message = json.loads(data.decode()) #convert the data to a string and then a json message 

        print(f"[{node_id} received: {message}]") #print out what node got what message using f string

        if message["to"] == node_id: #if the message is for this node
            print(f"[{node_id}] message for me: {message['msg']}") #print it
        else:
            message["ttl"] -= 1 #decrease the time to live
            if message["ttl"] > 0: #if its not expired
                forward(message) #forward it

    
def forward(message):
    came_from = message["via"]
    message["via"] = node_id
    data = json.dumps(message).encode() #change message into a json into a string
    for neighbor_id, neighbor_port in neighbors_dict.items(): #for each neighbor key value pair (name, port)
        if neighbor_id != came_from:
            sock.sendto(data, ("localhost", neighbor_port)) #send them the encoded message
            print(f"[{node_id}] forwarded to {neighbor_id}") #print that you did it




t = threading.Thread(target=listen) # define a new thread that will run the listen function
t.daemon = True #set it to kill on program stop
t.start() #start the thread


#main process loop 
while True:
    dest = input("send to: ") #take input
    msg = input("message: ")
    packet = {"from": node_id, "to": dest, "via": node_id, "ttl": 5, "msg": msg} #define the packet 
    forward(packet) #send it to neighbors