from udp_stream_config import UdpStreamConfig
class Packet:
    def __init__(self, source_ip: str, source_port: int, data: str, socket: UdpStreamConfig, destination_ip: str = None, destination_port: int = None):
        self.source_ip = source_ip
        self.source_port = source_port
        self.data = data
        self.socket = socket
        self.destination_ip = destination_ip
        self.destination_port = destination_port
    def __repr__(self):
        return f"Packet(source_ip={self.source_ip}, source_port={self.source_port}, destination_ip={self.destination_ip}, destination_port={self.destination_port}, data={self.data})"