import threading
from logging_config import get_logger

from udp_handler import UDPHandler
from hgn_sip.sip_handler import SIPHandler
from interslug.intercom_handler import IntercomSIPHandler

from config import FAKE_ID

main_logger = get_logger("main")

def main():
    main_logger.info("Starting main thread")
    bind_ip_address = "192.168.67.98"
    bind_sip_port = 5060
    main_logger.info(f"Creating SIPHandler. ip={bind_ip_address}, port={bind_sip_port}")

    intercom_sip_handler = IntercomSIPHandler(bind_ip_address, bind_sip_port, FAKE_ID)

    main_logger.info(f"Creating UDPHandler")
    udp_handler = UDPHandler()

    try:
        # Create SIP thread (which also registers the account)
        main_logger.info(f"Starting thread for SIPHandler")
        sip_thread = threading.Thread(target=intercom_sip_handler.run, name="thread-siphandler", daemon=True)
        sip_thread.start()
        # Create thread to process incoming packets
        main_logger.info(f"Starting thread for UDPHandler.receive")
        threading.Thread(target=udp_handler.receive, name="thread-udphandler-receive", daemon=True).start()
        # Create thread to occasionally transmit DHCP packet
        main_logger.info(f"Starting thread for UDPHandler.periodic_dhcp")
        threading.Thread(target=udp_handler.periodic_dhcp, name="thread-udphandler-periodic_dhcp", daemon=True).start()

        udp_handler.elevator_request(3, 6)
        udp_handler.elevator_request(3, 7)
        udp_handler.elevator_request(3, 8)
        udp_handler.elevator_request(3, 9)
        udp_handler.elevator_request(3, 10)
        udp_handler.elevator_request(3, 11)
        udp_handler.elevator_request(3, 12)

        input("Press Enter to exit...\n")
    finally:
        udp_handler.stop()
        intercom_sip_handler.stop()
if __name__ == "__main__":
    main()