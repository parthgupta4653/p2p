import socket
import threading
import time
import json
import select

checkTime = 300

class Peer: 
    def __init__(self, id, seeds,sock):
        self.id = f"{id}"
        self.seeds = seeds
        self.sock = sock

class Tracker:
    def __init__(self):
        self.host = ""
        self.port = 10000
        self.seeds = {}
        self.connections = {}
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.bind((self.host, self.port))
        self.s.listen(20)

    def kick_peer(self, peer):
        peer.sock.close()
        del self.connections[peer.id]
        for seed in peer.seeds:
            self.seeds[seed].remove(peer)
            if not self.seeds[seed]:
                del self.seeds[seed]

    def __del__(self):
        for peer in self.connections.values():
            peer.sock.close()
        self.s.close()
    
    def send_update(self, peer):
        print(f"Sending update to {peer.id}")
        sock_peer = peer.sock
        sock_peer.setblocking(True)
        payload = { seed: [p.id for p in peers] 
                    for seed, peers in self.seeds.items() }
        for item in payload.values():
            if(peer.id in item):
                item.remove(peer.id)
        message = json.dumps(payload).encode('utf8')
        sock_peer.sendall(message)
        #sock_peer.sendall("Update sent".encode())
        print("Update sent")
        time.sleep(1)                    
                    
    def recv_msg(self, sock_peer, peer_addr):   
        sock_peer.setblocking(True)
        sock_peer.sendall("Send Port".encode())
        sock_peer.settimeout(2.0)
        peer_port,seeds = sock_peer.recv(1024).decode().split("&")
        peer_port = int(peer_port)
        seeds = json.loads(seeds)
        print(seeds)
        print(type(peer_addr))
        peer_ip = peer_addr[0]
        if f"{peer_ip}:{peer_port}" in self.connections.keys():
            print(f"Peer {peer_ip} is already connected")
            return
        
        peer = Peer(f"{peer_ip}:{peer_port}",seeds,sock_peer)
        
        self.connections[peer.id] = peer
        
        for seed in seeds:
            if seed not in self.seeds:
                self.seeds[seed] = []
            self.seeds[seed].append(peer)
            
        print(f"Connected to {peer.id}")
        sock_peer.sendall("Connected".encode())
        while True:
            flag, _, _ = select.select([sock_peer], [], [], checkTime)
            if(not flag):
                print(f"Peer {peer.id} timed out")
                break
            msg = sock_peer.recv(1024).decode()
            print(f"Received from {peer.id}: {msg}")
            if msg == "exit":
                break
            elif msg == "Send Update":
                self.send_update(peer)
        self.kick_peer(peer)
        
        
    
    def accept_connections(self):
        while True:
            sock_peer, peer_addr = self.s.accept()
            self.recv_msg_thread = threading.Thread(target=self.recv_msg, args=(sock_peer, peer_addr))
            self.recv_msg_thread.start()
        
    def run(self):
        self.accept_thread = threading.Thread(target=self.accept_connections)
        self.accept_thread.start()
        
        self.accept_thread.join()
        

tracker = Tracker()
print("Tracker is running...") 
tracker.run()