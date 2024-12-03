from socket import socket
from typing import Optional

class UdpStreamConfig:
    def __init__(self, ip: str, port: int, name: str):
        self.ip = ip
        self.port = port
        self.name = name
        self.self_ip = "192.168.67.98"
        self.handle: Optional[socket] = None
    def __repr__(self):
        return f"UdpStreamConfig(ip={self.ip}, port={self.port}, name={self.name}, handle={self.handle})"
        