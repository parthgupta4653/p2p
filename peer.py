# Peer-side implementation for a simple P2P file sharing system

# Communicates with a central tracker and other peers

import random
import socket
import threading
import time
import json
import os
import shutil
import select
import sys
from colorama import Fore, Style, init
from cryptography.fernet import Fernet

MASTER_KEY = b"hLNpt1Oc7DpFtmwJgeAq_wK7zR77JZyGyVcjRJGrYU0="  
master_cipher = Fernet(MASTER_KEY)

# Initialize colorama
init(autoreset=True)

# Tracker IP and Port

# Currently set to localhost for testing purposes

tracker_ip = "127.0.0.1"
tracker_port = 10000

# Time interval to fetch peer/seed updates from tracker

UPDATE_TIME = 5

# Timeout for recv requests (in seconds)

RECV_TIMEOUT = 10 

# File transfer chunk size (256 KB)

chunk_size = 256*1024

# Max chunks to request from a peer in one connection

max_chunks_per_connection = 25

# Directory for this peer's files (provided as argument)

dir_name = sys.argv[1]

# Color formats for different message types
INFO = Fore.CYAN
SUCCESS = Fore.GREEN
WARNING = Fore.YELLOW
ERROR = Fore.RED
HIGHLIGHT = Fore.MAGENTA
RESET = Style.RESET_ALL
DEBUG = Fore.BLUE

# Represents a file and its status

class File:
    def __init__(self, seed):
        self.path = os.path.join(dir_name, seed)

        # Open the status file to read the current status of the file
        with open(os.path.join(self.path, "status.txt"), "r") as f:
            file = f.readlines()[0]
            status = json.loads(file)
            
            self.seed = status["seed"]
            self.size = status["size"]
            self.name = status["name"]    
            self.status = status["status"]
            
            self.completed_chunks = set(status["chunks"])
            self.no_of_chunks = self.size // chunk_size + (1 if self.size % chunk_size > 0 else 0)

    # function to update the status of the file and merge the chunks if files are completed
    def update_status_file(self):   
        print(f"{INFO}Updating status for {HIGHLIGHT}{self.seed}{RESET}")
        if(len(self.completed_chunks) == self.no_of_chunks):
            self.status = "completed"
            print(f"{SUCCESS}File {HIGHLIGHT}{self.seed}{SUCCESS} completed{RESET}")
            
            # Merge all chunks into a single file 
            with open(os.path.join(self.path, self.name), "wb") as output_file:
                for i in range(1, self.no_of_chunks + 1):
                    chunk_path = os.path.join(self.path, "chunks", str(i))
                    
                    # Read each chunk and write it to the output file
                    with open(chunk_path, "rb") as chunk_file:
                        output_file.write(chunk_file.read())
        
        # Update the status file with the current status of the file
        with open(os.path.join(self.path, "status.txt"), "w") as f:
            message = {"seed": self.seed, "name":self.name, "size": self.size, "status": self.status, "chunks": list(self.completed_chunks)}
            f.write(json.dumps(message))
            f.write("\n")

# Represents another peer this client is communicating with

class Peer:
    def __init__(self, ip, sock):
        self.ip = None
        self.port = None
        self.id = f"{ip}"
        self.sock = sock

        # List of chunks this peer has requested
        self.requested_chunks = []
        
        # Dictionary of available chunks this peer has
        self.available_chunks = {}

# Represents the main peer (this client)

class me:
    def __init__(self, ip):
        self.ip = ip
        self.port = 0
        self.seeds = {}             # seed -> list of peer IDs
        self.connections = {}       # peer ID -> socket
        self.peer_encryption_key = {} # seed -> encryption key
        self.tracker_sock = None
        self.on = True
        self.files = {}             # seed -> File object
        self.lock = threading.Lock()
        try:
            self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.s.bind(("", 0))
            self.s.listen(20)
        except socket.error as e:
            print(f"{ERROR}Error creating peer socket: {e}{RESET}")
            exit(1)

        # Load seeds from local seeds.txt
        if not os.path.exists(os.path.join(dir_name, "seeds.txt")):
            print(f"{ERROR}Seeds file not found{RESET}")
            exit(1)
        
        # Read the seeds file and populate the seeds dictionary
        with open(os.path.join(dir_name, "seeds.txt"), "r") as f:
            seeds = f.readlines()
            for seed_info in seeds:
                if seed_info:
                    seed_info = seed_info.strip().split(",")
                    self.seeds[seed_info[0]] = []
                    
                    if not os.path.exists(os.path.join(dir_name, seed_info[0])):
                        print(f"{ERROR}Seed directory not found for {seed_info[0]}{RESET}")
                        continue
                    if not os.path.exists(os.path.join(dir_name, seed_info[0], "status.txt")):
                        print(f"{ERROR}Status file not found for {seed_info[0]}{RESET}")
                        continue
                    
                    self.files[seed_info[0]] = File(seed_info[0])

    # Periodically fetch peer list updates from the tracker
    def update_from_tracker(self):
        
        # While the peer is active, keep checking for updates
        while self.on:
            time.sleep(UPDATE_TIME)
            self.tracker_sock.setblocking(True)
            
            # Send a request to the tracker for the current peer list
            
            try:
                self.tracker_sock.sendall("Send Update".encode())
                 # Wait for response with timeout
                ready, _, _ = select.select([self.tracker_sock], [], [], RECV_TIMEOUT)  
                if not ready:                                                                 
                    print(f"{WARNING}Tracker update timed out{RESET}")                     
                    continue                                                                   

                token = self.tracker_sock.recv(1000000000) 
                
                try:
                    plain = master_cipher.decrypt(token)
                except Exception as e:
                    print(f"{ERROR}Error decrypting update from tracker: {e}{RESET}")
                    continue
                    
                message = plain.decode("utf-8")
            except socket.error as e:
                print(f"{ERROR}Error receiving update from tracker: {e}{RESET}")
                continue
            except Exception as e:
                print(f"{ERROR}Error: {e}{RESET}")
                continue
                           
            all_seeds = json.loads(message)
            print(f"{INFO}Received update from tracker: {HIGHLIGHT}{all_seeds}{RESET}") 
            temp_seeds = {}
            
            # Update the seeds dictionary with the new peer list
            for seed in all_seeds:
                if seed in self.seeds.keys():
                    temp_seeds[seed] = all_seeds[seed][:-1]
            for seeds in all_seeds.keys():
                if seed not in self.peer_encryption_key.keys():
                    self.peer_encryption_key[seed] = all_seeds[seed][-1].encode()
            
            # Check if the seeds have changed
            if(temp_seeds != self.seeds):
                print(f"{HIGHLIGHT}New seeds available{RESET}")
                
                self.seeds = temp_seeds
                
        self.tracker_sock.close()
        print(f"{SUCCESS}Tracker connection closed{RESET}")
                
    # Connect to the tracker and register this peer
    def tracker_connection(self, tracker_ip, tracker_port):
        try:
            self.tracker_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tracker_sock.connect((tracker_ip, tracker_port))

            # Wait for initial prompt
            ready, _, _ = select.select([self.tracker_sock], [], [], RECV_TIMEOUT)  
            if not ready:                                                              
                print(f"{ERROR}Tracker connection prompt timed out{RESET}")          
                return                                                                 
            data = self.tracker_sock.recv(1024).decode()                              

            # Send the port number and list of seeds to the tracker
            if(data == "Send Port"):
                message = str(self.s.getsockname()[1]) + "&" + json.dumps(list(self.seeds.keys()))
                self.tracker_sock.sendall(message.encode())
            else:
                print(f"{ERROR}Error in connection{RESET}")
                return

            # Wait for confirmation
            ready, _, _ = select.select([self.tracker_sock], [], [], RECV_TIMEOUT)  
            if not ready:                                                              
                print(f"{ERROR}Tracker confirmation timed out{RESET}")                
                return                                                                 
            data = self.tracker_sock.recv(1024).decode()     
        except socket.error as e:
            print(f"{ERROR}Error connecting to tracker: {e}{RESET}")
            return
        except Exception as e:
            print(f"{ERROR}Error: {e}{RESET}")
            return                         

        # Check if the tracker is connected
        if(data == "Connected"):
            print(f"{SUCCESS}Connected to tracker{RESET}")
            self.update_from_tracker()
        else:
            print(f"{ERROR}Error in connection{RESET}")

    # Handle incoming requests from other peers (upload)
    def recv_msg_peer(self, sock_peer, peer_addr):
    
        # Add the peer to the connections dictionary
        with self.lock:
            self.connections[peer_addr] = sock_peer

        print(f"{INFO}Peer {HIGHLIGHT}{peer_addr}{INFO} connected{RESET}")
        sock_peer.setblocking(True)

        # Receive initial request
        ready, _, _ = select.select([sock_peer], [], [], RECV_TIMEOUT)  
        if not ready:                                                     
            print(f"{ERROR}Peer {HIGHLIGHT}{peer_addr}{ERROR} request timed out{RESET}")  
            sock_peer.close()                                             
            with self.lock:
                del self.connections[peer_addr]
            return  

        req_token = sock_peer.recv(10000000)  

        cipher = None
        used_seed = None

        for seed_key, key in self.peer_encryption_key.items():
            cipher_temp = Fernet(key)
            try:
                plain = cipher_temp.decrypt(req_token)
                cipher = cipher_temp
                used_seed = seed_key
                break
            except Exception as e:
                continue
        else:
            print(f"{ERROR}Error decrypting request from {HIGHLIGHT}{peer_addr}{ERROR}: No valid decryption key found{RESET}")
            sock_peer.close()
            with self.lock:
                del self.connections[peer_addr]
            return

        req = plain.decode()

        print(f"{INFO}Received request from {HIGHLIGHT}{peer_addr}{INFO}: {req}{RESET}")

        # Check if the request is for a chunk list
        if req.startswith("Send chunk list for"):
            # FIXED: Corrected the string parsing - don't use decode() on a string
            seed = req.split(" ")[-1]
            print(f"{INFO}Received request for chunk list for {HIGHLIGHT}{seed}{INFO} from {HIGHLIGHT}{peer_addr}{RESET}")

            cipher = Fernet(self.peer_encryption_key[used_seed])
            if seed not in self.files.keys():
                encrypt_seed_not_available = cipher.encrypt("Seed not available".encode())
                sock_peer.sendall(encrypt_seed_not_available)
                sock_peer.close()
                with self.lock:
                    del self.connections[peer_addr]
                return

            try:
                # Encrypt the chunk list with the peer's encryption key
                encrypt_completed_chunks = cipher.encrypt(json.dumps(list(self.files[seed].completed_chunks)).encode())
                sock_peer.sendall(encrypt_completed_chunks)
            except socket.error as e:
                print(f"{ERROR}Error sending chunk list to {HIGHLIGHT}{peer_addr}{ERROR}: {e}")
                sock_peer.close()
                with self.lock:
                    del self.connections[peer_addr]
                return

            print(f"{SUCCESS}Sent chunk list for {HIGHLIGHT}{seed}{SUCCESS} to {HIGHLIGHT}{peer_addr}{RESET}")

        # Serve requested chunks
        ready, _, _ = select.select([sock_peer], [], [], RECV_TIMEOUT)  
        if not ready:                                                     
            print(f"{ERROR}Peer {HIGHLIGHT}{peer_addr}{ERROR} serve timed out{RESET}")  
            sock_peer.close()                                             
            with self.lock:
                del self.connections[peer_addr]
            return    

        req_token = sock_peer.recv(10000000)  
        try:
            req = cipher.decrypt(req_token)
            req_str = req.decode()
            print(f"{INFO}Received request from {HIGHLIGHT}{peer_addr}{INFO}: {req_str}{RESET}")

            # Loop until the peer disconnects or sends "exit"
            while req_str != "exit":
                if req_str.startswith("Requesting chunk"):
                    # Parse the chunk number and seed from the request
                    parts = req_str.split(" ")
                    chunk = int(parts[2])
                    seed = parts[-1]

                    print(f"{INFO}Received request for chunk {HIGHLIGHT}{chunk}{INFO} for {HIGHLIGHT}{seed}{INFO} from {HIGHLIGHT}{peer_addr}{RESET}")

                    # Read the chunk file and send it
                    chunk_path = os.path.join(self.files[seed].path, "chunks", str(chunk))
                    if os.path.exists(chunk_path):
                        with open(chunk_path, "rb") as f:
                            data = f.read()

                            try:
                                encrypt_data = cipher.encrypt(data)
                                print(f"{DEBUG}Sending encrypted data for chunk {HIGHLIGHT}{chunk}{RESET}")
                                sock_peer.sendall(encrypt_data)
                            except socket.error as e:
                                print(f"{ERROR}Error sending chunk {HIGHLIGHT}{chunk}{ERROR} to {HIGHLIGHT}{peer_addr}{RESET}: {e}")
                                break
                            
                            print(f"{SUCCESS}Sent chunk {HIGHLIGHT}{chunk}{SUCCESS} to {HIGHLIGHT}{peer_addr}{RESET}")
                    else:
                        print(f"{ERROR}Chunk {HIGHLIGHT}{chunk}{ERROR} not found for {HIGHLIGHT}{seed}{RESET}")
                        error_msg = cipher.encrypt(f"Chunk {chunk} not found".encode())
                        sock_peer.sendall(error_msg)
                        break
                    
                ready, _, _ = select.select([sock_peer], [], [], RECV_TIMEOUT)  
                if not ready:                                                     
                    print(f"{ERROR}Peer {HIGHLIGHT}{peer_addr}{ERROR} chunk transfer timed out{RESET}")  
                    break 

                req_token = sock_peer.recv(10000000)  
                req = cipher.decrypt(req_token)
                req_str = req.decode()
                print(f"{INFO}Next request from {HIGHLIGHT}{peer_addr}{INFO}: {req_str}{RESET}")
        except Exception as e:
            print(f"{ERROR}Error processing request from {HIGHLIGHT}{peer_addr}{ERROR}: {e}{RESET}")

        print(f"{INFO}Peer {HIGHLIGHT}{peer_addr}{INFO} disconnected{RESET}")
        with self.lock:
            if peer_addr in self.connections.keys():
                del self.connections[peer_addr]
        sock_peer.close()
        
    # Accept incoming connections from peers (threaded)
    def handle_peer_requests(self):
        while self.on:
            
            readable, _, exceptional = select.select([self.s], [], [self.s], 5.0)
            if exceptional:
                print(f"{ERROR}Tracker socket error{RESET}")
                break
            if not readable:
                continue
            
            sock_peer, peer_addr = self.s.accept()
            print(f"{INFO}New connection from {HIGHLIGHT}{peer_addr}{RESET}")
            self.recv_msg_thread = threading.Thread(target=self.recv_msg_peer, args=(sock_peer, peer_addr))
            self.recv_msg_thread.start()
        self.s.close()
        print(f"{SUCCESS}Peer socket closed{RESET}")

    # Manage downloading chunks from a single peer
    def manage_peer(self, peer_id, seed):
        print(f"{INFO}Managing peer {HIGHLIGHT}{peer_id}{INFO} for seed {HIGHLIGHT}{seed}{RESET}")    # Skip if we already have a connection


        if peer_id in self.connections:
            print(f"{WARNING}Peer {HIGHLIGHT}{peer_id}{WARNING} already connected{RESET}")
            return

        # Split the peer_id "IP:Port" string into ip & port
        ip, port_str = peer_id.split(":")
        port = int(port_str)

        # Connect
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((ip, port))
        except socket.error as e:
            print(f"{ERROR}Error connecting to peer {HIGHLIGHT}{peer_id}{ERROR}: {e}{RESET}")
            return

        self.connections[peer_id] = sock
        sock.setblocking(True)

        # Prepare encryption for this seed
        seed_key = self.peer_encryption_key[seed]
        cipher = Fernet(seed_key)

        # 1) Request the chunk list - FIXED: Using the expected format
        req = f"Send chunk list for {seed}"
        token = cipher.encrypt(req.encode("utf-8"))
        sock.sendall(token)

        # 2) Receive & decrypt the response
        ready, _, _ = select.select([sock], [], [], RECV_TIMEOUT)
        if not ready:
            print(f"{WARNING}Timeout requesting chunk list from {HIGHLIGHT}{peer_id}{WARNING}{RESET}")
            sock.close()
            del self.connections[peer_id]
            return

        token = sock.recv(10_000_000)
        try:
            plain = cipher.decrypt(token)
            available_chunks = json.loads(plain.decode("utf-8"))
        
            if isinstance(available_chunks, str) and available_chunks == "Seed not available":
                print(f"{WARNING}Seed {HIGHLIGHT}{seed}{WARNING} not available from {HIGHLIGHT}{peer_id}{RESET}")
                sock.close()
                del self.connections[peer_id]
                return
            
            print(f"{INFO}Available chunks from peer {HIGHLIGHT}{peer_id}{INFO}: {available_chunks}{RESET}")
            if not available_chunks:
                sock.close()
                del self.connections[peer_id]
                return
        except Exception as e:
            print(f"{ERROR}Error decrypting chunk list from {HIGHLIGHT}{peer_id}{ERROR}: {e}{RESET}")
            sock.close()
            del self.connections[peer_id]
            return

        # 3) Download up to max_chunks_per_connection
        needed_chunks = [chunk for chunk in available_chunks 
                    if chunk not in self.files[seed].completed_chunks]
        chunks_to_download = needed_chunks[:max_chunks_per_connection]
    
        for chunk in chunks_to_download:
            # FIXED: Using the expected request format
            req = f"Requesting chunk {chunk} for {seed}"
            token = cipher.encrypt(req.encode("utf-8"))
            sock.sendall(token)

            ready, _, _ = select.select([sock], [], [], RECV_TIMEOUT)
            if not ready:
                print(f"{ERROR}Chunk {HIGHLIGHT}{chunk}{ERROR} recv timed out from {HIGHLIGHT}{peer_id}{RESET}")
                break

            try:
                token = sock.recv(10_000_000)
                data = cipher.decrypt(token)
            
                # Write chunk to disk
                with open(os.path.join(self.files[seed].path, "chunks", str(chunk)), "wb") as f:
                    f.write(data)
                self.files[seed].completed_chunks.add(chunk)
                self.files[seed].update_status_file()
                print(f"{SUCCESS}Received chunk {HIGHLIGHT}{chunk}{SUCCESS} from {HIGHLIGHT}{peer_id}{RESET}")
            except Exception as e:
                print(f"{ERROR}Error receiving chunk {HIGHLIGHT}{chunk}{ERROR} from {HIGHLIGHT}{peer_id}{ERROR}: {e}{RESET}")
                break

        # 4) Tell peer we're done
        exit_token = cipher.encrypt("exit".encode("utf-8"))
        sock.sendall(exit_token)

        sock.close()
        del self.connections[peer_id]

    # Attempt to download chunks for the specified seed
    def manage_seed(self, seed):
        print(f"{INFO}Managing seed {HIGHLIGHT}{seed}{RESET}")
        
        if(self.files[seed].status == "completed"):
            print(f"{SUCCESS}Seed {HIGHLIGHT}{seed}{SUCCESS} is already completed{RESET}")
            return
        
        if len(self.seeds[seed]) < 1:
            print(f"{WARNING}Seed {HIGHLIGHT}{seed}{WARNING} is not available{RESET}")
            
        peer_threads = []
        
        # Create threads for each peer to download chunks
        for peer in self.seeds[seed]:
            peer_thread = threading.Thread(target=self.manage_peer, args=(peer, seed), name=peer, daemon=True)
            peer_thread.start()
            peer_threads.append(peer_thread)
            
        for peer_thread in peer_threads:
            peer_thread.join()

    # Main loop for downloading all seeds periodically
    def peer_main(self):
        while self.on:
            time.sleep(1)
            print(f"{INFO}Peer main loop{RESET}")
            seed_threads = []
            
            # Thread for each seed to manage downloading
            for seed in self.seeds.keys():
                seed_thread = threading.Thread(target=self.manage_seed, args=(seed,), name=seed, daemon=True)
                seed_thread.start()
                seed_threads.append(seed_thread)
            for seed_thread in seed_threads:
                seed_thread.join()
            print(f"{SUCCESS}All seeds managed{RESET}")

# Entry point: handles CLI and starts peer functionality

def main():
    # Check if the directory exists, if not create it
    if not os.path.exists(dir_name):
        os.makedirs(dir_name)
    if not os.path.exists(os.path.join(dir_name, "seeds.txt")):
         with open(os.path.join(dir_name, "seeds.txt"), "w") as f:
            pass

    # CLI options before starting peer
    print(f"{HIGHLIGHT}Welcome to the Peer-to-Peer File Sharing System{RESET}")
    print(f"{INFO}Please enter the operation you want to perform{RESET}")
    print(f"{INFO}start: {RESET}Start the peer")
    print(f"{INFO}seed: {RESET}Add a new seed")
    print(f"{INFO}fetch: {RESET}Fetch a new seed")
    print(f"{INFO}exit: {RESET}Exit the program\n")

    while True:

        operation = input(f"{HIGHLIGHT}Enter the operation: {RESET}")
        
        if operation == "start":
            break
                
        elif operation == "seed":
            
            
            seed = input(f"{INFO}Enter the seed: {RESET}")
            file_path = input(f"{INFO}Enter the file path: {RESET}")
            size = os.path.getsize(file_path)
            name = os.path.basename(file_path)
            
            # Append the seed and size to the seeds.txt file
            with open(os.path.join(dir_name, "seeds.txt"), "a") as f:
                f.write(seed + "," + str(size) + "\n")
                
            # Check if the seed directory exists, if not create it
            if not os.path.exists(os.path.join(dir_name, seed)):
                os.makedirs(os.path.join(dir_name, seed))
                
            # Check if the chunks directory exists, if not create it
            if not os.path.exists(os.path.join(dir_name, seed, "chunks")):
                os.makedirs(os.path.join(dir_name, seed, "chunks"))
                
            # Copy the file to the seed directory
            shutil.copy(file_path, os.path.join(dir_name, seed))
            
            no_of_chunks = size // chunk_size
            remainder = size % chunk_size
            
            
            with open(file_path, "rb") as f:
                i = 1
                chunk = f.read(chunk_size)
                while chunk:
                    with open(os.path.join(dir_name, seed, "chunks", str(i)), "wb") as chunk_file:
                        chunk_file.write(chunk)
                    i += 1
                    chunk = f.read(chunk_size)
            
            with open(os.path.join(dir_name, seed, "status.txt"), "w") as f:
                if remainder > 0:
                    no_of_chunks += 1
                message = {"name":name, "seed": seed, "size": size, "status": "completed", "chunks": list(range(1, no_of_chunks+1))}
                f.write(json.dumps(message))
                f.write("\n")
                
            print(f"{SUCCESS}Seed {HIGHLIGHT}{seed}{SUCCESS} added successfully{RESET}")
                
        elif operation == "fetch":
            
            seed = input(f"{INFO}Enter the seed of the file: {RESET}")
            size = int(input(f"{INFO}Enter the size of file: {RESET}"))
            name = input(f"{INFO}Enter the name of the file: {RESET}")
            
            # Append the seed and size to the seeds.txt file
            with open(os.path.join(dir_name, "seeds.txt"), "a") as f:
                f.write(seed + "," + str(size) + "\n")

            # Check if the seed directory exists, if not create it
            if not os.path.exists(os.path.join(dir_name, seed)):
                os.makedirs(os.path.join(dir_name, seed))
                
            # Check if the chunks directory exists, if not create it
            if not os.path.exists(os.path.join(dir_name, seed, "chunks")):
                os.makedirs(os.path.join(dir_name, seed, "chunks"))            

            # update the status file with the current status of the file
            with open(os.path.join(dir_name, seed, "status.txt"), "w") as f:
                message = {"name":name, "seed": seed, "size": size, "status": "downloading", "chunks": []}
                f.write(json.dumps(message))
                f.write("\n")

            print(f"{SUCCESS}Seed {HIGHLIGHT}{seed}{SUCCESS} added successfully{RESET}")
            
        elif operation == "exit":
            print(f"{SUCCESS}Exiting the program{RESET}")
            exit(0)
            
        else:
            print(f"{ERROR}Invalid operation{RESET}")
            continue
    # Start peer services and threads
    main_peer = me(tracker_ip)

    # Start the tracker connection thread
    tracker_thread = threading.Thread(target=main_peer.tracker_connection, args=(tracker_ip, tracker_port), daemon=True)
    tracker_thread.start()

    time.sleep(UPDATE_TIME*2)

    # Start the peer main thread 
    peer_thread = threading.Thread(target=main_peer.peer_main, name="peer_main", daemon=True)
    peer_thread.start()

    # Start the peer request handling thread
    peer_requests = threading.Thread(target=main_peer.handle_peer_requests, name="peer_requests", daemon=True)
    peer_requests.start()

    try:
        while True:
            time.sleep(1) # Keep the main thread alive
    except KeyboardInterrupt:
        # Gracefully handle keyboard interrupt
        print(f"{ERROR}Peer interrupted by user{RESET}")
        main_peer.on = False
    except Exception as e: #Print any other exceptions
        print(f"{ERROR}Error starting Peer: {e}{RESET}")
        main_peer.on = False

    tracker_thread.join()
    peer_thread.join()
    peer_requests.join()

    print(f"{SUCCESS}Peer services stopped{RESET}")
if __name__ == "__main__":
    main()