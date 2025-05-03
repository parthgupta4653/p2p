# Tracker-side implementation for a simle P2P file sharing system
# This code handles peer connections, seed management, and communication between peers.

import socket
import threading
import time
import json
import select
from colorama import Fore, Style, init

# Initialize colorama
init(autoreset=True)

# Color formats for different message types
INFO = Fore.CYAN
SUCCESS = Fore.GREEN
WARNING = Fore.YELLOW
ERROR = Fore.RED
HIGHLIGHT = Fore.MAGENTA
STATUS = Fore.BLUE
RESET = Style.RESET_ALL

# Maximum wait time for peer activity before timeout (in seconds)
CHECK_PEER_TIMEOUT = 300

# Limit on simultaneous peer connections
MAX_PEER_CONNECTIONS = 20

# Represents a peer connected to the tracker
class Peer: 
    def __init__(self, id, seeds, sock):
        self.id = f"{id}"          # Peer identifier: "IP:Port"
        self.seeds = seeds         # List of file seed hashes
        self.sock = sock           # Peer socket connection

# The tracker coordinates peers and seed availability
class Tracker:
    def __init__(self):
        self.host = ""             # Bind to all available interfaces
        self.port = 10000          # Tracker's port
        self.seeds = {}            # Map: seed hash -> list of peers
        self.connections = {}      # Map: peer ID -> Peer object

        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.bind((self.host, self.port))
        self.s.listen(MAX_PEER_CONNECTIONS)

        print(f"{SUCCESS}Tracker started on {HIGHLIGHT}{self.host}:{self.port}{RESET}")
        print(f"{INFO}Listening for incoming connections...{RESET}")
        print(f"{INFO}Max Peer Connections: {HIGHLIGHT}{MAX_PEER_CONNECTIONS}{RESET}\n")

    # Remove a peer from tracker records and clean up its entries
    def kick_peer(self, peer):
        print(f"{STATUS}[Tracker] {WARNING}Disconnecting and removing peer {HIGHLIGHT}{peer.id}{RESET}")
        peer.sock.close()
        del self.connections[peer.id]

        for seed in peer.seeds:
            self.seeds[seed].remove(peer)
            if not self.seeds[seed]:  # Remove seed if no peers left
                del self.seeds[seed]

        print(f"{SUCCESS}Peer {HIGHLIGHT}{peer.id}{SUCCESS} removed from tracker records{RESET}")

    # Clean up all peer sockets and shut down tracker socket
    def __del__(self):
        print(f"{STATUS}Cleaning up all sockets...{RESET}")
        for peer in self.connections.values():
            peer.sock.close()
        self.s.close()
        print(f"{SUCCESS}All sockets closed{RESET}")
        print(f"{SUCCESS}Tracker Destroyed{RESET}")
    
    # Send current peer list for each seed to the requesting peer
    def send_update(self, peer):
        print(f"{STATUS}[Tracker] {INFO}Preparing update for peer {HIGHLIGHT}{peer.id}{RESET}")
        sock_peer = peer.sock
        sock_peer.setblocking(True)

        # Build dictionary: seed -> list of peer IDs (excluding self)
        payload = { seed: [p.id for p in peers if p.id != peer.id]
                    for seed, peers in self.seeds.items() }

        message = json.dumps(payload).encode('utf8')
        sock_peer.sendall(message)
        print(f"{STATUS}[Tracker] {SUCCESS}Update sent to peer {HIGHLIGHT}{peer.id}{RESET}")
        time.sleep(1)

    # Handle interaction with a connected peer
    def recv_msg(self, sock_peer, peer_addr):
        sock_peer.setblocking(True)
        sock_peer.sendall("Send Port".encode())
        sock_peer.settimeout(2.0)

        # Expecting peer response: "<port>&<seed_list_json>"
        peer_port, seeds = sock_peer.recv(1024).decode().split("&")
        peer_port = int(peer_port)
        seeds = json.loads(seeds)
        peer_ip = peer_addr[0]
        peer_id = f"{peer_ip}:{peer_port}"

        if peer_id in self.connections:
            print(f"{WARNING}Peer {HIGHLIGHT}{peer_id}{WARNING} already connected{RESET}")
            return

        peer = Peer(peer_id, seeds, sock_peer)
        self.connections[peer.id] = peer

        for seed in seeds:
            if seed not in self.seeds:
                self.seeds[seed] = []
            self.seeds[seed].append(peer)

        print(f"{SUCCESS}Peer {HIGHLIGHT}{peer.id}{SUCCESS} connected with seeds: {HIGHLIGHT}{seeds}{RESET}")
        sock_peer.sendall("Connected".encode())

        while True:
            # Wait for data or timeout
            flag, _, _ = select.select([sock_peer], [], [], CHECK_PEER_TIMEOUT)
            if not flag:
                print(f"{WARNING}Peer {HIGHLIGHT}{peer.id}{WARNING} timed out{RESET}")
                break

            msg = sock_peer.recv(1024).decode()
            print(f"{INFO}Received message from peer {HIGHLIGHT}{peer.id}{INFO}: {msg}{RESET}")

            if msg == "exit":
                break
            elif msg == "Send Update":
                self.send_update(peer)

        self.kick_peer(peer)
        
    # Accept new incoming peer connections in a loop
    def accept_connections(self):
        while True:
            sock_peer, peer_addr = self.s.accept()
            print(f"{INFO}New connection from {HIGHLIGHT}{peer_addr}{RESET}")
            
            # A new thread for each peer connection
            self.recv_msg_thread = threading.Thread(target=self.recv_msg, args=(sock_peer, peer_addr))
            self.recv_msg_thread.start()
    
    # Launch the tracker service
    def run(self):
        
        # Start the accept connections thread
        self.accept_thread = threading.Thread(target=self.accept_connections)
        self.accept_thread.start()
        self.accept_thread.join()
        

# Create and start the tracker
tracker = Tracker()
print(f"{HIGHLIGHT}Tracker Instance has been created{RESET}")
print(f"{INFO}Starting Tracker...{RESET}")
print(f"{SUCCESS}Tracker is running...{RESET}\n")

tracker.run()