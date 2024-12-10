import select
import socket 
import struct
from udp_stream_config import UdpStreamConfig

class SocketManager:
    def __init__(self, udp_casts: list[UdpStreamConfig]):
        self.self_ip = "0.0.0.0"
        self.sockets = [self._setup_socket(socket_config) for socket_config in udp_casts]
        self.interface = "eth0"

    def _setup_socket(self, socket_config: UdpStreamConfig):
        # Generate a UDP socket object based on the provided config, which will contain:
        # {name: "xyz", "ip": "...", "port": 1234}
        
        # So many ANGRY UPPERCAST constants
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b'eth0')
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65535)  # Set to a higher value
        sock.bind((self.self_ip, socket_config.port))

        # IGMP Register as listener for Multicast (255.255.255.255 is broadcast)
        if socket_config.ip != "255.255.255.255":
            # Only subscribe if the destination is not broadcast addr
            mreq = struct.pack("4s4s", socket.inet_aton("238.9.9.1"), socket.inet_aton("192.168.67.98"))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            # mreq = struct.pack("4sl", socket.inet_aton(socket_config.ip), socket.INADDR_ANY)
            # sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        socket_config.handle = sock
        return socket_config

    def receive(self, timeout=None) -> list[socket.socket]:
        handles = [socket.handle for socket in self.sockets]
        rlist, _, _ = select.select(handles, [], [], timeout)
        return rlist
    
    def get_receiving_socket_name(self, socket: socket.socket) -> UdpStreamConfig:
        for huh in self.sockets:
            if socket == huh.handle:
                return huh
    def get_socket_by_name(self, name: str) -> UdpStreamConfig:
        for huh in self.sockets:
            if name == huh.name:
                return huh