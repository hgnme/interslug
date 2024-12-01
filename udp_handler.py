import ipaddress
import select
import socket
import struct
import threading
import time
import netifaces
import logging
import xml.etree.ElementTree as ET
from config import UDP_BROADCAST_PORT, UDP_MULTICAST_GROUP, UDP_MULTICAST_PORT, UDP_MULTICAST_CALLLOG_PORT, REGULAR_PACKET_INTERVAL, FAKE_ID

class UDPHandler:
    def __init__(self):
        # Set up the UDP sockets
        self.broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.multicast_socket = self._setup_multicast_socket(UDP_MULTICAST_PORT)
        self.multicast_socket_callog = self._setup_multicast_socket(UDP_MULTICAST_CALLLOG_PORT)  # New socket for port 8302
        
        self.running = True

        logging.basicConfig(
            filename="all_messages.log",
            level=logging.INFO,
            format="%(asctime)s - %(message)s",
            filemode="a"
        )
        self.dhcp_logger = logging.getLogger('dhcp_logger')
        dhcp_handler = logging.FileHandler('dhcp_messages.log')
        dhcp_handler.setLevel(logging.INFO)
        dhcp_formatter = logging.Formatter('%(asctime)s - %(message)s')
        dhcp_handler.setFormatter(dhcp_formatter)
        self.dhcp_logger.addHandler(dhcp_handler)

        self.udp_logger = logging.getLogger('udp_logger')
        udp_handler = logging.FileHandler('udp_messages2.log')
        udp_handler.setLevel(logging.INFO)
        udp_formatter = logging.Formatter('%(asctime)s - %(message)s')
        udp_handler.setFormatter(udp_formatter)
        self.udp_logger.addHandler(udp_handler)
        # Get the local IP address and subnet of eth0
        self.local_ip, self.local_subnet = self.get_local_ip_and_subnet("eth0")
        self.local_network = ipaddress.IPv4Network(f"{self.local_ip}/{self.local_subnet}", strict=False)
        self.broadcast_socket.bind(('', UDP_BROADCAST_PORT))  # Bind to all interfaces


    def _setup_multicast_socket(self, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', UDP_MULTICAST_PORT))
        mreq = struct.pack("4sl", socket.inet_aton(UDP_MULTICAST_GROUP), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        return sock
    def get_local_ip_and_subnet(self, interface):
        # Get the local IP address and subnet mask for a given interface
        addrs = netifaces.ifaddresses(interface)
        ip = addrs[socket.AF_INET][0]['addr']
        subnet_mask = addrs[socket.AF_INET][0]['netmask']
        return ip, subnet_mask
    def parse_xml(self, data):
        """ Parses the XML data and returns the root element """
        try:
            return ET.fromstring(data)
        except ET.ParseError as e:
            self.udp_logger.error(f"Failed to parse XML: {e}")
            return None
    def send_broadcast(self, message):
        self.broadcast_socket.sendto(message.encode(), ("<broadcast>", UDP_BROADCAST_PORT))

    def send_multicast(self, message):
        self.broadcast_socket.sendto(message.encode(), (UDP_MULTICAST_GROUP, UDP_MULTICAST_PORT))

    def respond(self, message, address):
        self.broadcast_socket.sendto(message.encode(), address)
    def handle_dhcp_packet(self, xml_root, source_address):
        """ Handle DHCP request packet """
        if xml_root is not None:
            event = xml_root.find('event').text
            op = xml_root.find('op').text
            mac = xml_root.find('mac').text

            # Log or take action based on the DHCP event
            self.dhcp_logger.info(f"Received DHCP event: {event}, operation: {op}, ip: {source_address}, mac: {mac}")
    def handle_event_packet(self, xml_root, source_address, raw):
        """ Handle Event packet (multicast request for ID) """
        if xml_root is not None:
            active = xml_root.find('active').text
            packet_type = xml_root.find('type').text
            id_ = xml_root.find('id').text
            version = xml_root.find('version').text
            # Check if this is a 'discover' event asking for a specific ID
            if active == 'discover' and packet_type == 'req':
                self.udp_logger.info(f"Received multicast request for ID: {id_} from ip: {source_address}")
                # Respond with the SIP address
                # self.respond(f"{id_}@{self.local_ip}:5060", xml_root)
            else:
                self.udp_logger.info(f"Received multicast unknown from ip: {source_address}. {raw}")
    def receive(self):
        while self.running:
            # Use select to wait for data from either the broadcast or multicast socket
            rlist, _, _ = select.select([self.broadcast_socket, self.multicast_socket, self.multicast_socket_callog], [], [])
            
            for sock in rlist:
                data, addr = sock.recvfrom(1024)
                message = data.decode('utf-8', errors='ignore')

                # Check if the source IP address is in the same subnet
                source_ip = addr[0]
                log_addr = "{0}:{1}".format(addr[0],addr[1])
                if self.local_network.network_address <= ipaddress.IPv4Address(source_ip) <= self.local_network.broadcast_address:
                    if sock == self.multicast_socket_callog:
                        # Log the plain text message received from port 8302
                        self.udp_logger.info(f"Received callhistory message on port 8302: {message} from {log_addr}")
                    else: 
                        # Otherwise XML
                        # Parse the XML message
                        xml_root = self.parse_xml(message)

                        # Handle different packet types based on XML structure
                        if xml_root is not None:
                            # Handle DHCP packet
                            if xml_root.tag == 'dhcp':
                                print(f"received dhcp from {log_addr}")
                                self.handle_dhcp_packet(xml_root, log_addr)
                            # Handle Event packet (multicast)
                            elif xml_root.tag == 'event':
                                print(f"received event from {log_addr}")
                                self.handle_event_packet(xml_root, log_addr, message)
                            else:
                                print(f"received uncategorised xml from {log_addr}... {message}")
                                self.udp_logger.warning(f"Received uncategorised XML ({xml_root.tag}): {message} from {log_addr}")
                        else:
                            print(f"received uncategorised message from {log_addr}... {message}")
                            self.udp_logger.warning(f"Received uncategorised message: {message} from {log_addr}")
    
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