# mesh-node
Python process network using mesh network concepts for message passing and topology sharing.

This is a simple mesh network using python processes as nodes. 

It implements a basic distance vector routing protocol. Nodes store and update a cost map of costs to send messages to other nodes in their network. Info is stored in a dictionary of dictionaries, with a key of other nodes and value of a dictionary storing next node and cost.

The network topology is as follows:

A - B - C - F - G

    |           |
    D - E       H - I
    
                    |
                    J

Overall topology is stored in dictionary format, though nodes only know about their direct neighbors at startup.

Nodes discover topologies of non-adjacent neighbors through a gossip protocol.
