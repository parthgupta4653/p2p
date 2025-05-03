# Tracker-side implementation for a simple P2P file sharing system
# This code handles peer connections, seed management, and communication between peers.

import socket
import threading
import time
import json
import select
from colorama import Fore, Style, init
from cryptography.fernet import Fernet

MASTER_KEY = b"hLNpt1Oc7DpFtmwJgeAq_wK7zR77JZyGyVcjRJGrYU0="  
master_cipher = Fernet(MASTER_KEY)

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

# Timeout for recv requests (in seconds)
RECV_TIMEOUT = 2  

# Limit on simultaneous peer connections
MAX_PEER_CONNECTIONS = 20

# Represents a peer connected to the tracker
class Peer:
    def __init__(self, id, seeds, sock):
        self.id = f"{id}"          # Peer identifier: "IP:Port"
        self.seeds = seeds         # List of file seed hashes
        self.sock = sock           # Peer socket connection
        self.peer_encryption_key = None  # Peer encryption key (if any)

# The tracker coordinates peers and seed availability
class Tracker:
    def __init__(self):
        self.host = ""             # Bind to all available interfaces
        self.port = 10000          # Tracker's port
        self.seeds = {}            # Map: seed hash -> list of peers
        self.connections = {}      # Map: peer ID -> Peer object
        self.on = True           # Tracker status flag
        self.peer_encryption_key = {}

        try:
            self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.s.bind((self.host, self.port))
            self.s.listen(MAX_PEER_CONNECTIONS)
        except socket.error as e:
            print(f"{ERROR}Error creating tracker socket: {e}{RESET}")
            exit(1)

        print(f"{SUCCESS}Tracker started on {HIGHLIGHT}{self.host}:{self.port}{RESET}")
        print(f"{INFO}Listening for incoming connections...{RESET}")
        print(f"{INFO}Max Peer Connections: {HIGHLIGHT}{MAX_PEER_CONNECTIONS}{RESET}\n")

    # Remove a peer from tracker records and clean up its entries
    def kick_peer(self, peer):
        print(f"{STATUS}[Tracker] {WARNING}Disconnecting and removing peer {HIGHLIGHT}{peer.id}{RESET}")
        
        try:
            peer.sock.close()
        except Exception as e:
            print(f"{ERROR}Error closing peer socket: {e}{RESET}")
        
        if peer.id in self.connections:
            del self.connections[peer.id]

        for seed in peer.seeds:
            if seed not in self.seeds: # Skip if seed not found
                continue
            if peer in self.seeds[seed]: # Remove peer from seed list if exists
                self.seeds[seed].remove(peer) 
            if not self.seeds[seed]:  # Remove seed if no peers left
                del self.seeds[seed]

        print(f"{SUCCESS}Peer {HIGHLIGHT}{peer.id}{SUCCESS} removed from tracker records{RESET}")

    def generate_encryption_key_for_each_seed(self, seed):
        # Generate a unique encryption key for each seed
        if seed not in self.peer_encryption_key:
            key = Fernet.generate_key()
            self.peer_encryption_key[seed] = key
            print(f"{SUCCESS}Generated encryption key for seed {HIGHLIGHT}{seed}{SUCCESS}: {key.decode()}{RESET}")
        return self.peer_encryption_key[seed]
    
    # Clean up all peer sockets and shut down tracker socket
    def __del__(self):
        print(f"{STATUS}Cleaning up all sockets...{RESET}")
        try:
            for peer in self.connections.values():
                peer.sock.close()
            self.s.close()
        except Exception as e:
            print(f"{ERROR}Error closing sockets during cleanup: {e}{RESET}")
            
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

        for seed in payload:
            # Generate encryption key for each seed
            key = self.generate_encryption_key_for_each_seed(seed)
            payload[seed].append(key.decode())  # Append the encryption key to the list
        
        message = json.dumps(payload).encode('utf8')
        token = master_cipher.encrypt(message)  # Encrypt the message
        print(message)
        print(token)
        try:
            sock_peer.sendall(token)
        except Exception as e:
            print(f"{ERROR}Error sending update to peer {HIGHLIGHT}{peer.id}{ERROR}: {e}{RESET}")
            self.kick_peer(peer)
            return
        
        print(f"{STATUS}[Tracker] {SUCCESS}Update sent to peer {HIGHLIGHT}{peer.id}{RESET}")
        time.sleep(1)

    # Handle interaction with a connected peer
    def recv_msg(self, sock_peer, peer_addr):
        try:
            sock_peer.setblocking(True)
            sock_peer.sendall("Send Port".encode())

            # Wait for initial peer response with timeout
            ready, _, _ = select.select([sock_peer], [], [], RECV_TIMEOUT)  
            if not ready:  
                print(f"{ERROR}[Tracker] Peer {HIGHLIGHT}{peer_addr}{ERROR} initial response timed out{RESET}")  
                sock_peer.close()  
                return  

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
            
        except Exception as e:
            print(f"{ERROR}Error receiving message from peer {HIGHLIGHT}{peer_addr}{ERROR}: {e}{RESET}")
            self.kick_peer(peer)
            return

        while True:
            # Wait for data or timeout
            try:
                flag, _, _ = select.select([sock_peer], [], [], CHECK_PEER_TIMEOUT)
                if not flag:
                    print(f"{WARNING}Peer {HIGHLIGHT}{peer.id}{WARNING} timed out{RESET}")
                    break

                msg = sock_peer.recv(1024).decode()
            except Exception as e:
                print(f"{ERROR}Error receiving message from peer {HIGHLIGHT}{peer.id}{ERROR}: {e}{RESET}")
                break
                
            print(f"{INFO}Received message from peer {HIGHLIGHT}{peer.id}{INFO}: {msg}{RESET}")

            if msg == "exit" or msg == "":
                break
            elif msg == "Send Update":
                self.send_update(peer)

        self.kick_peer(peer)
        
    # Accept new incoming peer connections in a loop
    def accept_connections(self):
        while self.on:
            readable, _, exceptional = select.select([self.s], [], [self.s], 5.0)
            if exceptional:
                print(f"{ERROR}Tracker socket error{RESET}")
                break
            if not readable:
                continue
            sock_peer, peer_addr = self.s.accept()
            print(f"{INFO}New connection from {HIGHLIGHT}{peer_addr}{RESET}")
            
            # A new thread for each peer connection
            self.recv_msg_thread = threading.Thread(target=self.recv_msg, args=(sock_peer, peer_addr), daemon=True)
            self.recv_msg_thread.start()
    
    # Launch the tracker service
    def run(self):
        # Start the accept connections thread
        self.accept_thread = threading.Thread(target=self.accept_connections, daemon=True)
        self.accept_thread.start()
        
        try:
            while True:
                time.sleep(1) # Keep the main thread alive
        except KeyboardInterrupt:
            # Gracefully handle keyboard interrupt
            print(f"{ERROR}Tracker interrupted by user{RESET}")
            self.on = False
        except Exception as e: #Print any other exceptions
            print(f"{ERROR}Error starting tracker: {e}{RESET}")
            self.on = False
            
        self.accept_thread.join() #Waits for the accept thread to finish
        print(f"{SUCCESS}Tracker has stopped accepting new connections{RESET}")
        
                
# Create and start the tracker
tracker = Tracker()
print(f"{HIGHLIGHT}Tracker Instance has been created{RESET}")
print(f"{INFO}Starting Tracker...{RESET}")
print(f"{SUCCESS}Tracker is running...{RESET}\n")

tracker.run()
