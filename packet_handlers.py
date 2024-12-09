import xml.etree.ElementTree as ET
from logging_config import get_logger
from config import FAKE_ID
from intercom_sender import RespondToIDRequest
from packet import Packet
def parse_xml(data):
    try:
        return ET.fromstring(data)
    except ET.ParseError as e:
        return None

def handle_dhcp_packet(xml_root, source_address, dhcp_logger):
    if xml_root is not None:
        event = xml_root.find('event').text
        op = xml_root.find('op').text
        mac = xml_root.find('mac').text
        dhcp_logger.info(f"Received DHCP event: {event}, operation: {op}, ip: {source_address}, mac: {mac}")

def handle_event_packet(xml_root, source_address, raw, udp_logger):
    if xml_root is not None:
        active = xml_root.find('active').text
        packet_type = xml_root.find('type').text
        id_ = xml_root.find('id').text
        version = xml_root.find('version').text
        if active == 'discover' and packet_type == 'req':
            udp_logger.info(f"Received multicast request for ID: {id_} from ip: {source_address}")
        else:
            udp_logger.info(f"Received multicast unknown from ip: {source_address}. {raw}")
        

class PacketHandler:
    def __init__(self, packet_manifest: Packet, counter: int):
        self.logger = get_logger("packet_handler")
        self.packet = packet_manifest
        self.xml_data = None
        self.is_xml = None
        self.packet_type = None
        self.packet_id = counter

    def parse_xml(self, data):
        try:
            self.xml_data = ET.fromstring(data)
            self.is_xml = True
            return self.xml_data
        except ET.ParseError as e:
            self.is_xml = False
            return None
        
    def get_xml_value_from_tag(self, tag, xml = None) -> ET.Element:
        if xml is not None:
            return xml.find(tag)
        return self.xml_data.find(tag)
    
    def set_packet_type(self, packet_type: str, should_log = True):
        self.packet_type = packet_type
        if should_log:
            self.logger.debug(f"({self.packet_id}) Packet Type is: {self.packet_type}")

    def process_sip_id_request(self):
        self.logger.info(f"({self.packet_id}) Processing SIP ID request")
        fake_id = FAKE_ID
        request_id = self.get_xml_value_from_tag("id").text
        self.logger.debug(f"({self.packet_id}) Checking request ID {request_id} against fake ID {fake_id}")
        if request_id == fake_id:
            self.logger.debug(f"({self.packet_id}) ID Match. Should now reply with our SIP address")
            response = RespondToIDRequest(fake_id, self.packet)
            response.send_it()
    def decode_elevator_request(self):
        elev_xml = self.get_xml_value_from_tag("elev")
        elev_building = self.get_xml_value_from_tag("build",elev_xml).text
        elev_unit = self.get_xml_value_from_tag("unit",elev_xml).text
        elev_floor = self.get_xml_value_from_tag("floor",elev_xml).text
        elev_family = self.get_xml_value_from_tag("family",elev_xml).text
        apt_number = elev_family.zfill(2)
        unlocked_by = f"{elev_floor}{apt_number}"
        self.logger.info(f"({self.packet_id}) Elevator unlocked for Building {elev_building}, floor {elev_floor} by apt {unlocked_by}")
    
    def decode_search_ack(self):
        resp_id = self.get_xml_value_from_tag('id').text
        resp_ip = self.get_xml_value_from_tag('ip').text
        resp_mac = self.get_xml_value_from_tag('mac').text
        self.logger.info(f"search response. id, ip, mac.\t{resp_id},{resp_ip},{resp_mac}")
    def handle_event_packet(self):
        event_activity = self.get_xml_value_from_tag('active').text
        event_type = self.get_xml_value_from_tag('type').text
        self.logger.debug(f"({self.packet_id}) Contents:\n{self.packet}")
        if event_activity == "discover":
            # Someone wants a, or is reponding to a SIP address request.
            self.set_packet_type("xml->event->discover")
            if event_type == "req":
                self.set_packet_type("xml->event->discover->req")
                self.process_sip_id_request()
            elif event_type == "ack":
                self.set_packet_type("xml->event->discover->ack")
                self.logger.debug(f"({self.packet_id}) Found SIP ID Acknowledgment")
        elif event_activity == "broadcast_data":
            self.set_packet_type("xml->event->broadcast_data")
            event_url = self.get_xml_value_from_tag("broadcast_url").text
            elevator_urls = ["elevaction","/elev/wall/action"]
            if event_url in elevator_urls:
                self.set_packet_type("xml->event->elevaction")
                if event_type == "req":
                    self.set_packet_type("xml->event->elevaction->req")
                    self.decode_elevator_request()
        elif event_activity == "search":
            if event_type == "ack":
                self.set_packet_type("xml->event->search->ack")
                self.decode_search_ack()
        else:
            self.logger.info(f"({self.packet_id}) Packet is a unknown event ({event_activity}:{event_type})")

    def handle_xml_packet(self):
        xml = self.xml_data
        if xml.tag == "dhcp":
            return
            self.set_packet_type("xml->dhcp")
            # Handle DHCP Packet
        elif xml.tag == "event":
            self.set_packet_type("xml->event")
            self.handle_event_packet()
            
    def handle_packet(self):
        # self.logger.info(f"({self.packet_id}) Handling packet from {self.packet.source_ip}:{self.packet.source_port}")
        if self.parse_xml(self.packet.data) is not None:
            self.set_packet_type("xml", False)
            self.handle_xml_packet()
        else:
            self.set_packet_type("non-xml")
            self.logger.warning(f"({self.packet_id}) Packet is non-XML")
            self.logger.debug(f"({self.packet_id}) Contents:\n{self.packet}")

