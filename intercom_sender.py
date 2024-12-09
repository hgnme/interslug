from packet import Packet
from logging_config import get_logger
from config import FAKE_ID, SIP_LOCAL_PORT
import xml.etree.ElementTree as ET
from udp_stream_config import UdpStreamConfig



class GenericXML:
    def __init__(self, tag: str):
        self.tag = tag
        self.xml = ET.Element(tag)
    def to_string(self):
        return ET.tostring(self.xml, encoding="utf-8")
    def add_element(self, tag: str, parent: ET.Element = None): 
        target = parent if parent is not None else self.xml
        return ET.SubElement(target, tag)
    def set_element_text(self, tag: str, text: str):
        self.xml.find(tag).text = text

class GenericEventXML(GenericXML):
    def __init__(self, event_activity: str, event_type: str):
        self.activity = event_activity
        self.event_type = event_type
        xml = GenericXML("event")
        xml.add_element("active").text = event_activity
        xml.add_element("type").text = event_type
        self.xml = xml.xml

class RespondToIDRequest:
    def __init__(self, id: str, source_packet: Packet, start_sip=False):
        self.logger = get_logger("id_responder")
        self.id = id
        self.source_packet = source_packet
        local_ip = "192.168.67.98"
        sip_address = f"sip:{FAKE_ID}@{local_ip}:{SIP_LOCAL_PORT}"
        response = ET.Element("event")
        ET.SubElement(response, "active").text = "discover"
        ET.SubElement(response, "type").text = "ack"
        ET.SubElement(response, "url").text = sip_address
        response_xml = ET.tostring(response, encoding='utf-8')
        self.logger.info(f"Created SIP address response. target={source_packet.source_ip} sip_address={sip_address}")
        self.packet = Packet( 
            source_ip = source_packet.socket.self_ip, 
            source_port = source_packet.socket.port, 
            destination_ip = source_packet.source_ip, 
            destination_port = source_packet.socket.port,
            socket=source_packet.socket,
            data=response_xml
        )

    def send_it(self):
        send_packet(self.packet)
class SearchRequest:
    def __init__(self, socket: UdpStreamConfig):
        self.socket = socket
        xml = GenericEventXML("search","req")
        self.packet = Packet( 
            source_ip = self.socket.self_ip, 
            source_port = self.socket.port, 
            destination_ip = self.socket.ip, 
            destination_port = self.socket.port,
            socket=socket,
            data=xml.to_string()
        )
    def send_it(self):
        send_packet(self.packet)



class UnlockElevatorFloorRequest:
    def __init__(self, building: int, floor: int, apt: int, socket: UdpStreamConfig):
        self.logger = get_logger("elevator_request")
        self.socket = socket
        self.packets:list[Packet] = []
        xml = GenericEventXML("broadcast_data", "req")
        xml.add_element("broadcast_url").text = "elevaction"
        elev_xml = xml.add_element("elev")
        xml.add_element("to", elev_xml).text = "12"
        xml.add_element("build", elev_xml).text = f"{building}"
        xml.add_element("unit", elev_xml).text = "0"
        xml.add_element("floor", elev_xml).text = f"{floor}"
        xml.add_element("family", elev_xml).text = f"{apt}"
        self.packets.append(Packet( 
            source_ip = self.socket.self_ip, 
            source_port = self.socket.port, 
            destination_ip = self.socket.ip, 
            destination_port = self.socket.port,
            socket=socket,
            data=xml.to_string()
        ))
        xml.set_element_text("broadcast_url", "elev/wall/action")
        self.packets.append(Packet( 
            source_ip = self.socket.self_ip, 
            source_port = self.socket.port, 
            destination_ip = self.socket.ip, 
            destination_port = self.socket.port,
            socket=socket,
            data=xml.to_string()
        ))
        
        self.logger.info(f"Created Elevator Unlock Request. packets={self.packets}")
    def send_it(self):
        for packet in self.packets:
            send_packet(packet)

class DHCPBroadcast:
    def __init__(self, socket: UdpStreamConfig):
        self.logger = get_logger("dhcp_broadcaster")
        self.socket = socket
        self.mac_address = "dc:a6:32:5b:6f:1f"
        xml = GenericXML("dhcp")
        xml.add_element("event").text = "/discover" # dhcp->event
        xml.add_element("op").text = "req" # dhcp->op
        xml.add_element("mac").text = self.mac_address  # dhcp->mac

        self.packet = Packet( 
            source_ip = self.socket.self_ip, 
            source_port = self.socket.port, 
            destination_ip = self.socket.ip, 
            destination_port = self.socket.port,
            socket=socket,
            data=xml.to_string()
        )
        self.logger.info(f"Created DHCP Broadcast. body={self.packet.data}")
    def send_it(self):
        send_packet(self.packet)

def send_packet(packet: Packet):
    logger = get_logger("packet_sender")
    logger.debug(f"Sending packet. body={packet.data} source_ip={packet.source_ip} source_port={packet.source_port} dest_ip={packet.destination_ip} dest_port={packet.destination_port}")
    dest_addr = (packet.destination_ip, packet.destination_port)
    packet.socket.handle.sendto(packet.data, dest_addr)
    logger.debug(f"Packet sent.")