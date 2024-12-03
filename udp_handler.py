from ipaddress import ip_address, ip_network
import ipaddress
import socket
import threading
import time
import netifaces
from socket_manager import SocketManager
from logging_config import get_logger
from packet_handlers import PacketHandler, Packet
from intercom_sender import DHCPBroadcast, UnlockElevatorFloorRequest
from config import UDP_CAST_CONFIGS, DHCP_PACKET_INTERVAL

class UDPHandler:
    def __init__(self):
        # Initialize sockets using SocketManager
        self.logger = get_logger("udp_handler")
        self.socket_manager = SocketManager(UDP_CAST_CONFIGS)
        self.local_ip, self.local_subnet = self.get_local_ip_and_subnet("eth0")
        self.logger.info(f"Creating UDPHandler for {self.local_ip} subnet {self.local_subnet}")
        self.local_network = ipaddress.IPv4Network(f"{self.local_ip}/{self.local_subnet}", strict=False)
        self.running = True
        self.packet_counter = 0

    def get_local_ip_and_subnet(self, interface):
        addrs = netifaces.ifaddresses(interface)
        ip = addrs[socket.AF_INET][0]['addr']
        subnet_mask = addrs[socket.AF_INET][0]['netmask']
        return ip, subnet_mask

    def is_ip_in_local_subnet(self, source_ip):
        # Assuming self.local_ip and self.local_subnet are already set
        return (ip_address(source_ip) in self.local_network)
    
    def dhcp_broadcast(self):
        broadcast_socket = self.socket_manager.get_socket_by_name("intercom_reqs")
        self.logger.info("Sending DHCP Broadcast")
        obj = DHCPBroadcast(broadcast_socket)
        obj.send_it()

    def elevator_request(self):
        broadcast_socket = self.socket_manager.get_socket_by_name("intercom_reqs")
        self.logger.info("Sending elevator request")
        obj = UnlockElevatorFloorRequest(3, 3, 9, broadcast_socket)
        obj.send_it()

    def periodic_dhcp(self):
        while self.running:
            self.dhcp_broadcast()
            time.sleep(DHCP_PACKET_INTERVAL)

    def receive(self):
        while self.running:
            rlist = self.socket_manager.receive()
            for sock in rlist:
                self.packet_counter += 1
                data, addr = sock.recvfrom(4096)
                source_ip = addr[0]
                log_addr = "{0}:{1}".format(addr[0], addr[1])

                receiving_socket_name = self.socket_manager.get_receiving_socket_name(sock).name
                self.logger.info(f"({self.packet_counter}) Received packet from {log_addr} on from stream {receiving_socket_name}")
                self.logger.debug(f"({self.packet_counter}) Contents {data}")
                
                message = data.decode('utf-8', errors='ignore')
                if self.local_ip == source_ip:
                    self.logger.debug(f"({self.packet_counter}) ignoring packet sent by self")
                elif self.is_ip_in_local_subnet(source_ip):
                    packet_manifest = Packet(addr[0], addr[1], message, self.socket_manager.get_socket_by_name(receiving_socket_name))
                    self.logger.info(f"({self.packet_counter}) in-scope: Calling packet handler")
                    handler = PacketHandler(packet_manifest, self.packet_counter)
                    handler.handle_packet()
                else:
                    self.logger.debug("out-of-scope: dropping")
    def stop(self):
        self.running = False
        for socket in self.socket_manager.sockets:
            socket.handle.close()