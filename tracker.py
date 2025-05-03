import socket
import threading
import time
import json
import select

# TIme (in seconds) to wait for a peer before timing out
CHECK_PEER_TIMEOUT = 300
MAX_PEER_CONNECTIONS = 20

# Class For Peer
class Peer: 
    def __init__(self, id, seeds,sock):
        
        # unique id for each peer: (ip_address:port)
        self.id = f"{id}"
        
        # list of the files seeds this peer has
        self.seeds = seeds
        
        # this peer's socket object
        self.sock = sock

# Class For Tracker
class Tracker:
    def __init__(self):
        
        # binds tracker to given host, currently empty signify binds to all available network interfaces
        self.host = ""
        
        # tracker port 
        self.port = 10000
        
        # Seeds Dictionary: Mapping seed hash -> list of Peer that have this seed hash
        # It store the data of seeds and their respective Peers
        self.seeds = {}
        
        # Peer Dictionary: Mapping peer id -> Peer Instance
        # It store the details of current connected Peers
        self.connections = {}
        
        # Create Tracker Socket
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.bind((self.host, self.port))
        
        # Start Listening for incoming connections
        # The maximum number of queued connections is set to MAX_PEER_CONNECTIONS
        self.s.listen(MAX_PEER_CONNECTIONS)
        
        print(f"Tracker started on {self.host}:{self.port}")
        print(f"Listening for incoming connections...")
        print(f"Max Peer Connections: {MAX_PEER_CONNECTIONS}")
        print(f"\n")

    # function to disconnect and remove a peer from all tracker records
    def kick_peer(self, peer):
        
        print(f"[Tracker] Disconnecting and removing peer {peer.id}")
        
        # close the peer's socket
        peer.sock.close()
        
        # remove from active connections
        del self.connections[peer.id]
        
        # for each seed in the peer's seeds list, remove the peer from the seeds dictionary
        for seed in peer.seeds:
            # Remove the peer from the list of peers for that seed
            self.seeds[seed].remove(peer)
            
            # If no peers are left for that seed, remove the seed from the seeds dictionary
            if not self.seeds[seed]:
                del self.seeds[seed]
                
        print(f"Peer {peer.id} removed from tracker records")

    # function to clean up all sockets when tracker is destroyed
    def __del__(self):
        
        print("Cleaning up all sockets...")
        
        # close the socket of each peer in the connections dictionary
        for peer in self.connections.values():
            peer.sock.close()
            
        # close the Tracker socket    
        self.s.close()
        
        print("All sockets closed")
        print("Tracker Destroyed")
    
    # function to send the current peer list for each seed to the requesting peer
    def send_update(self, peer):
        
        print(f"[Tracker] Preparing update for peer {peer.id}")
        
        # Sock object of the peer to send the update
        sock_peer = peer.sock
        
        # Set the socket to blocking mode
        # This means that the socket will block the program until it can send data
        sock_peer.setblocking(True)
        
        # Build payload: seed -> list of peer IDs
        # This creates a dictionary where the keys are the seeds and the values are lists of peer IDs
        payload = { seed: [p.id for p in peers] 
                    for seed, peers in self.seeds.items() }
        
        # Remove your own peer ID from the payload
        for item in payload.values():
            if(peer.id in item):
                item.remove(peer.id)
        
        # Convert the payload to JSON format
        message = json.dumps(payload).encode('utf8')
        
        # Send the payload to the peer
        sock_peer.sendall(message)
        
        print(f"[Tracker] Update sent to peer {peer.id}")
        
        # Wait for the peer to acknowledge the update
        time.sleep(1)                 
                    
    # function to receive messages from the peer
    # This function is called when a new peer connects to the tracker
    def recv_msg(self, sock_peer, peer_addr):   
        
        # Set the socket to non-blocking mode
        # This means that the socket will not block the program if it cannot send or receive data immediately
        sock_peer.setblocking(True)
        
        # Send a message to the peer to request the port number and seeds
        sock_peer.sendall("Send Port".encode())
        
        # Wait for the peer to respond with its port number and seeds
        sock_peer.settimeout(2.0)
        
        # Receive the peer's response
        peer_port,seeds = sock_peer.recv(1024).decode().split("&")
        peer_port = int(peer_port)
        
        # JSON decode the seeds string to a list of seeds
        seeds = json.loads(seeds)
        peer_ip = peer_addr[0]
        
        # Check if the peer is already connected
        if f"{peer_ip}:{peer_port}" in self.connections.keys():
            print(f"Peer {peer_ip}:{peer_port} already connected")
            return
        
        # Create a new Peer instance
        peer = Peer(f"{peer_ip}:{peer_port}",seeds,sock_peer)
        
        # Add the peer to the connections dictionary
        self.connections[peer.id] = peer
        
        # For each seed in the peer's seeds list, add the peer to the seeds dictionary
        for seed in seeds:
            
            # If the seed is not already in the seeds dictionary, create a new list for it
            if seed not in self.seeds:
                self.seeds[seed] = []
                
            # Add the peer to the list of peers for that seed
            self.seeds[seed].append(peer)
        print(f"Peer {peer.id} connected with seeds: {seeds}")
        
        # Send a message to the peer to confirm the connection
        sock_peer.sendall("Connected".encode())
        
        # Wait for the peer to send a message
        while True:
            
            # Block for up to CHECK_PEER_TIMEOUT seconds waiting for sock_peer to have data ready to read
            flag, _, _ = select.select([sock_peer], [], [], CHECK_PEER_TIMEOUT)
            
            # If the peer times out, break the loop and remove the peer from the tracker
            if(not flag):
                print(f"Peer {peer.id} timed out")
                break
            
            # If the peer sends a message, receive it and print it
            msg = sock_peer.recv(1024).decode()
            
            print(f"Received message from peer {peer.id}: {msg}")
            
            # If the message is "exit", break the loop and remove the peer from the tracker
            if msg == "exit":
                break
            
            # If the message is "Send Update", send the update to the peer
            elif msg == "Send Update":
                self.send_update(peer)
                
        # Disconnect the peer and remove it from the tracker
        self.kick_peer(peer)
        
    # function to accept incoming connections from peers
    def accept_connections(self):
        
        # This function runs in a separate thread to accept incoming connections from peers
        while True:
            
            # Accept a new connection from a peer
            sock_peer, peer_addr = self.s.accept()
            
            # Threading to handle the peer connection
            # This creates a new thread for each peer that connects to the tracker
            print(f"New connection from {peer_addr}")
            self.recv_msg_thread = threading.Thread(target=self.recv_msg, args=(sock_peer, peer_addr))
            
            # Start the thread to handle the peer connection
            self.recv_msg_thread.start()
    
    # function to run the tracker
    def run(self):
        
        # Start the accept_connections function in a separate thread
        self.accept_thread = threading.Thread(target=self.accept_connections)
        
        # Start the thread to accept incoming connections
        self.accept_thread.start()
        
        # Wait for the accept thread to finish
        self.accept_thread.join()
        

# Create a Tracker instance and start it
tracker = Tracker()

print("Tracker Instance has been created")
print("Starting Tracker...")
print("\n")
print("Tracker is running...")
print("\n")

# Run the tracker
tracker.run()