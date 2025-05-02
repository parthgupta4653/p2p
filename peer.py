import random
import socket
import threading
import time
import json
import os
import shutil
import sys


tracker_ip = "127.0.0.1"
tracker_port = 10000
update_time = 4
chunk_size = 256*1024
max_chunks_per_connection = 25

#dir_name = "peer1"
dir_name = sys.argv[1]


class File:
    def __init__(self,seed):
        self.path = os.path.join(dir_name, seed)
        
        with open(os.path.join(self.path, "status.txt"), "r") as f:
            file = f.readlines()[0]
            status = json.loads(file)
            self.seed = status["seed"]
            self.size = status["size"]
            self.name = status["name"]    
            self.status = status["status"]
            self.completed_chunks = set(status["chunks"])
            self.no_of_chunks = self.size // chunk_size + (1 if self.size % chunk_size > 0 else 0)
               
        
    def update_status_file(self):
        print(self.completed_chunks)
        if(len(self.completed_chunks) == self.no_of_chunks):
            self.status = "completed"
            print(f"File {self.seed} completed")
            with open(os.path.join(self.path, self.name), "wb") as output_file:
                for i in range(1, self.no_of_chunks + 1):
                    chunk_path = os.path.join(self.path, "chunks", str(i))
                    with open(chunk_path, "rb") as chunk_file:
                        output_file.write(chunk_file.read())
        
        with open(os.path.join(self.path, "status.txt"), "w") as f:
            message = {"seed": self.seed, "name":self.name, "size": self.size, "status": self.status, "chunks": list(self.completed_chunks)}
            f.write(json.dumps(message))
            f.write("\n")
            

class Peer: 
    def __init__(self, ip, sock):
        self.ip = None
        self.port = None
        self.id = f"{ip}"
        self.sock = sock
        self.requested_chunks = []
        self.available_chunks = {}
        
        
class me:
    def __init__(self, ip):
        self.ip = ip
        self.port = 0
        self.seeds = {}
        self.connections = {}
        self.tracker_sock = None
        self.on = True
        self.files = {}
        self.lock = threading.Lock()
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.bind(("", 0))
        self.s.listen(5)
        
        if not os.path.exists(os.path.join(dir_name, "seeds.txt")):
            print("No seeds file found")
            exit(1)
        
        with open(os.path.join(dir_name, "seeds.txt"), "r") as f:
            seeds = f.readlines()
            for seed_info in seeds:
                if seed_info:
                    seed_info = seed_info.strip().split(",")
                    self.seeds[seed_info[0]] = []
                    self.files[seed_info[0]] = File(seed_info[0])
    
    def update_from_tracker(self):
        while self.on:
            time.sleep(update_time)
            self.tracker_sock.setblocking(True)
            self.tracker_sock.sendall("Send Update".encode())
            print("Hello")
            msg = self.tracker_sock.recv(100000000).decode()
            print(msg)
            all_seeds = json.loads(msg)
            temp_seeds = {}
            for seed in all_seeds:
                if seed in self.seeds.keys():
                    temp_seeds[seed] = all_seeds[seed]
            print("Seeds and peers updated")
            if(temp_seeds != self.seeds):
                print("Seeds changed")
                self.seeds = temp_seeds
    
    def tracker_connection(self, tracker_ip, tracker_port):
        self.tracker_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tracker_sock.connect((tracker_ip, tracker_port))
        data = self.tracker_sock.recv(1024).decode()
        if(data == "Send Port"):
            message = str(self.s.getsockname()[1]) + "&" + json.dumps(list(self.seeds.keys()))
            self.tracker_sock.sendall(message.encode())
            print(message)
        else:
            print("Error in connection1")
        data = self.tracker_sock.recv(1024).decode()
        if(data == "Connected"):
            print("Connected to tracker")
            self.update_from_tracker()
        else:
            print("Error in connection")

    def recv_msg_peer(self, sock_peer, peer_addr):
        with self.lock:
            self.connections[peer_addr] = sock_peer
        
        print(f"Peer {peer_addr} connected")
        sock_peer.setblocking(True)
        
        req = sock_peer.recv(10000000)
        print("Received request from peer", req.decode())
        if req.decode().startswith("Send chunk list for"):
            seed = req.decode().split(" ")[-1]
            
            print(f"Received request for {seed} from {peer_addr}")
            
            if seed not in self.files.keys():
                sock_peer.sendall("Seed not available".encode())
                sock_peer.close()
                del self.connections[peer_addr]
                return
            
            sock_peer.sendall(json.dumps(list(self.files[seed].completed_chunks)).encode())
            print(f"Sent chunk list for {seed} to {peer_addr}")
        
        req = sock_peer.recv(10000000)
        while req.decode() != "exit":
            if req.decode().startswith("Requesting chunk"):
                chunk = int(req.decode().split(" ")[2])
                seed = req.decode().split(" ")[-1]

                print(f"Received request for {chunk} from {peer_addr}")
                with open(os.path.join(self.files[seed].path,"chunks", str(chunk)), "rb") as f:
                    data = f.read()
                    sock_peer.sendall(data)
                    print(f"Sent chunk {chunk} to {peer_addr}")
            req = sock_peer.recv(10000000)
        
        print(f"Peer {peer_addr} disconnected")
        with self.lock:
            if peer_addr in self.connections.keys():
                del self.connections[peer_addr]
        sock_peer.close()
            
    
    def handle_peer_requests(self):
        while self.on:
            sock_peer, peer_addr = self.s.accept()
            print(f"Accepted connection from {peer_addr}")
            self.recv_msg_thread = threading.Thread(target=self.recv_msg_peer, args=(sock_peer, peer_addr))
            self.recv_msg_thread.start()

    def manage_peer(self, peer, seed):
        print(f"Managing peer {peer} for seed {seed}")
        
        if peer in self.connections.keys():
            print(f"Peer {peer} is already connected")
            return
        
        peer = Peer(peer, None)
        
        peer.ip ,peer.port = peer.id.split(":")
        peer.port = int(peer.port)
        peer.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        peer.sock.connect((peer.ip, peer.port))
        self.connections[peer.id] = peer.sock
        
        peer.sock.setblocking(True)
        peer.sock.sendall(("Send chunk list for "+seed).encode())
        data = peer.sock.recv(1000000)
        if(data.decode() == "Seed not available"):
            print(f"Seed {seed} is not available with peer {peer.id}")
            peer.sock.close()
            del self.connections[peer.id]
            return
        
        available_chunks = json.loads(data)
        print(f"Received chunk list for {seed} from peer {peer.id}")
        print(available_chunks)
        if len(available_chunks) == 0:
            print(f"No chunks available with peer {peer.id}")
            peer.sock.close()
            del self.connections[peer.id]
            return
        chunks = []
        while len(chunks) < max_chunks_per_connection and available_chunks:
            with self.lock:
                chunk = random.choice(available_chunks)
                available_chunks.remove(chunk)
                if chunk not in self.files[seed].completed_chunks:
                    chunks.append(chunk)
                    self.files[seed].completed_chunks.add(chunk)
        print(chunks)
        for chunk in chunks:
            print(f"Requesting chunk {chunk} from peer {peer.id}")
            peer.sock.sendall(("Requesting chunk "+ str(chunk) + " for "+seed).encode())
            data = peer.sock.recv(1000000)     
            with open(os.path.join(self.files[seed].path,"chunks", str(chunk)), "wb") as f:
                f.write(data)
                print(f"Received chunk {chunk} from peer {peer.id}")
        
        with self.lock:
            print(f"Completed chunks for {seed}: {self.files[seed].completed_chunks}")
            self.files[seed].update_status_file()
        peer.sock.sendall("exit".encode())
        peer.sock.close()
        del self.connections[peer.id]
        
    def manage_seed(self, seed):
        print(f"Managing seed {seed}")
        
        if(self.files[seed].status == "completed"):
            print(f"Seed {seed} is already completed")
            return
        
        if len(self.seeds[seed]) < 1:
            print(f"Seed {seed} is not available")
            #return
            
        peer_threads = []
        for peer in self.seeds[seed]:
            peer_thread = threading.Thread(target=self.manage_peer, args=(peer, seed), name=peer, daemon=True)
            peer_thread.start()
            peer_threads.append(peer_thread)
            
        for peer_thread in peer_threads:
            peer_thread.join()
                
    
    def peer_main(self):
        while self.on:
            time.sleep(1)
            print("Peer main loop")
            seed_threads = []
            for seed in self.seeds.keys():
                seed_thread = threading.Thread(target=self.manage_seed, args=(seed,), name=seed, daemon=True)
                seed_thread.start()
                seed_threads.append(seed_thread)
            for seed_thread in seed_threads:
                seed_thread.join()
            print("Seed threads joined")
        

def main():
    if not os.path.exists(dir_name):
        os.makedirs(dir_name)
    if not os.path.exists(os.path.join(dir_name, "seeds.txt")):
         with open(os.path.join(dir_name, "seeds.txt"), "w") as f:
            pass
    
    while True:
        op = input("Enter the operation: ")
        
        if op == "start":
            break
                
        elif op == "seed":
            seed = input("Enter the seed: ")
            file_path = input("Enter the file path: ")
            size = os.path.getsize(file_path)
            name = os.path.basename(file_path)
            
            with open(os.path.join(dir_name, "seeds.txt"), "a") as f:
                f.write(seed + "," + str(size) + "\n")
                
            if not os.path.exists(os.path.join(dir_name, seed)):
                os.makedirs(os.path.join(dir_name, seed))
                
            if not os.path.exists(os.path.join(dir_name, seed, "chunks")):
                os.makedirs(os.path.join(dir_name, seed, "chunks"))
                
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
                
        elif op == "fetch":
            seed = input("Enter the seed: ")
            size = int(input("Enter the size: "))
            name = input("Enter the name: ")
            
            with open(os.path.join(dir_name, "seeds.txt"), "a") as f:
                f.write(seed + "," + str(size) + "\n")

            if not os.path.exists(os.path.join(dir_name, seed)):
                os.makedirs(os.path.join(dir_name, seed))
                
            if not os.path.exists(os.path.join(dir_name, seed, "chunks")):
                os.makedirs(os.path.join(dir_name, seed, "chunks"))            

            with open(os.path.join(dir_name, seed, "status.txt"), "w") as f:
                message = {"name":name, "seed": seed, "size": size, "status": "downloading", "chunks": []}
                f.write(json.dumps(message))
                f.write("\n")

    main_peer = me(tracker_ip)
    
    tracker_thread = threading.Thread(target=main_peer.tracker_connection, args=(tracker_ip, tracker_port), daemon=True)
    tracker_thread.start()
    
    time.sleep(update_time*2)
    
    peer_thread = threading.Thread(target=main_peer.peer_main, name="peer_main", daemon=True)
    peer_thread.start()
    
    peer_requests = threading.Thread(target=main_peer.handle_peer_requests, name="peer_requests", daemon=True)
    peer_requests.start()
    
    tracker_thread.join()
    
    

if __name__ == "__main__":
    main()