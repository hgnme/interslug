import socket
import struct
import threading
import time
from config import UDP_BROADCAST_PORT, UDP_MULTICAST_GROUP, UDP_MULTICAST_PORT, REGULAR_PACKET_INTERVAL

class UDPHandler:
    def __init__(self):
        self.broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.multicast_socket = self._setup_multicast_socket()
        self.running = True

    def _setup_multicast_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', UDP_MULTICAST_PORT))
        mreq = struct.pack("4sl", socket.inet_aton(UDP_MULTICAST_GROUP), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        return sock

    def send_broadcast(self, message):
        self.broadcast_socket.sendto(message.encode(), ("<broadcast>", UDP_BROADCAST_PORT))

    def send_multicast(self, message):
        self.broadcast_socket.sendto(message.encode(), (UDP_MULTICAST_GROUP, UDP_MULTICAST_PORT))

    def respond(self, message, address):
        self.broadcast_socket.sendto(message.encode(), address)

    def receive(self):
        while self.running:
            data, addr = self.multicast_socket.recvfrom(1024)
            print(f"Received {data} from {addr}")
            # Add logic to respond or trigger actions

    def periodic_broadcast(self, message):
        def _send_periodic():
            while self.running:
                self.send_broadcast(message)
                time.sleep(REGULAR_PACKET_INTERVAL)

        thread = threading.Thread(target=_send_periodic, daemon=True)
        thread.start()

    def stop(self):
        self.running = False
        self.broadcast_socket.close()
        self.multicast_socket.close()